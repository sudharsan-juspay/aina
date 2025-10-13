#!/usr/bin/env python3
# Copyright (c) 2025 [Harivatsa G A]. All rights reserved.
# This work is licensed under CC BY-NC-ND 4.0.
# https://creativecommons.org/licenses/by-nc-nd/4.0/
# Attribution required. Commercial use and modifications prohibited.
"""
Kibana Log MCP Server

This server implements the Model Context Protocol (MCP) to provide Cursor AI 
with access to Kibana logs for debugging and issue resolution.
"""

import os
import sys
import asyncio
import json
import yaml
import time
import datetime
import httpx
from typing import Dict, List, Optional, Any, Union, Tuple
import argparse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import elasticsearch
from elasticsearch import AsyncElasticsearch
from loguru import logger
from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP, Context
from mcp import types
import uvicorn
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import traceback

# Store the dynamic auth token
DYNAMIC_AUTH_TOKEN = None

# Store the current selected index
CURRENT_INDEX = None

# Store the dynamic config overrides
DYNAMIC_CONFIG_OVERRIDES = {}

# Store the dynamic Periscope auth token
PERISCOPE_AUTH_TOKEN = None

# Load configuration
def load_config(config_path: str = None) -> Dict:
    """Load the configuration from a YAML file."""
    try:
        # Use absolute path with fallback to relative
        if config_path is None:
            # Get directory of the current script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "config.yaml")
            
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        sys.exit(1)

def configure_logging():
    """Configure the logger with the settings from the config file."""
    log_level = CONFIG["mcp_server"]["log_level"].upper()
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    # logger.add("kibana_mcp_server.log", rotation="10 MB", retention="30 days", level=log_level)

# Initialize the configuration
CONFIG = load_config()

# Configure logging
log_level = CONFIG["mcp_server"]["log_level"].upper()
logger.remove()
logger.add(sys.stderr, level=log_level)
# logger.add("kibana_mcp_server.log", rotation="10 MB", retention="30 days", level=log_level)

# Get authentication details
es_config = CONFIG["elasticsearch"]
kibana_host = es_config['host']
kibana_version = es_config.get("kibana_api", {}).get("version", "7.10.2")
kibana_base_path = es_config.get("kibana_api", {}).get("base_path", "/_plugin/kibana")

# Get current auth token (with dynamic token support)
def get_auth_token():
    global DYNAMIC_AUTH_TOKEN
    return DYNAMIC_AUTH_TOKEN or os.environ.get("KIBANA_AUTH_COOKIE") or es_config.get("auth_cookie", "")

# Get Periscope auth token (with dynamic token support)
def get_periscope_auth_token():
    global PERISCOPE_AUTH_TOKEN
    return PERISCOPE_AUTH_TOKEN or os.environ.get("PERISCOPE_AUTH_TOKEN") or CONFIG.get("periscope", {}).get("auth_token", "")

# Function to get a properly configured HTTP client
def get_http_client():
    """Get an HTTP client with proper configuration."""
    # Get verify_ssl from dynamic config or fallback to es_config
    verify_ssl = get_config_value('elasticsearch.verify_ssl', es_config.get('verify_ssl', True), expected_type=bool)
    
    # Ensure verify_ssl is a boolean (httpx requires boolean, not string)
    if isinstance(verify_ssl, str):
        verify_ssl = verify_ssl.lower() == "true"
    
    return httpx.AsyncClient(
        verify=verify_ssl,
        follow_redirects=True,
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
)

# Initialize the MCP server
mcp = FastMCP(
    CONFIG["mcp_server"]["name"],
    version=CONFIG["mcp_server"]["version"],
    dependencies=["elasticsearch>=8.0.0", "httpx>=0.24.0", "pydantic>=2.0.0"]
)

# Create a FastAPI app for HTTP transport
app = FastAPI(title="Kibana MCP Server")

# Add health endpoint for Docker healthchecks
@mcp.tool()
async def health():
    """Health check endpoint for container monitoring."""
    return {"status": "ok", "version": CONFIG["mcp_server"]["version"]}

# Helper function to interact with Kibana API
async def kibana_search(index_pattern: str, query: Dict, size: int = 10, sort: List = None, aggs: Dict = None) -> Dict:
    """Execute a search query through Kibana API."""
    global CURRENT_INDEX
    
    # Use the dynamically selected index if available, otherwise use the provided one
    actual_index = CURRENT_INDEX or index_pattern
    
    # Log which index we're using
    logger.debug(f"Searching in index: {actual_index} (user requested: {index_pattern})")
    
    # Prepare the search request - use dynamic config if available
    host = get_config_value('elasticsearch.host', kibana_host)
    base_path = get_config_value('elasticsearch.kibana_api.base_path', kibana_base_path)
    url = f"https://{host}{base_path}/internal/search/es"
    
    # Build request payload
    search_body = {
        "query": query,
        "size": size
    }
    
    # Get timestamp field from config - default to '@timestamp' which is the Elasticsearch standard
    timestamp_field = get_config_value('elasticsearch.timestamp_field', es_config.get('timestamp_field', '@timestamp'))
    
    # Check the index pattern to see if we have a specific config for it
    for source in CONFIG.get('log_sources', []):
        if source.get('index_pattern') and actual_index.startswith(source.get('index_pattern').rstrip('*')):
            if 'timestamp_field' in source:
                timestamp_field = source.get('timestamp_field')
                logger.debug(f"Using timestamp field '{timestamp_field}' for index {actual_index}")
                break
    
    # Add sort if provided and if we know the index has the field
    if sort:
        search_body["sort"] = sort
    else:
        # Default sort by timestamp if no sort is provided
        # We'll try not to sort if we're getting errors to avoid the "no mapping found" issue
        search_body["sort"] = [{timestamp_field: {"order": "desc"}}]
    
    # Add aggregations if provided
    if aggs:
        search_body["aggs"] = aggs
    
    # Format for the data API
    payload = {
        "params": {
            "index": actual_index,
            "body": search_body
        }
    }
    
    # Set request headers
    headers = {
        "kbn-version": kibana_version,
        "Content-Type": "application/json"
    }
    
    # Get the current auth token
    current_auth_token = get_auth_token()
    
    # Check if we have an auth token
    if not current_auth_token:
        logger.error("No authentication token available. Please set it via API, environment variable, or config.")
        return {"error": "No authentication token available"}
    
    # Set cookies
    cookies = {"_pomerium": current_auth_token} if current_auth_token else None
    
    # Debug output for development
    logger.debug(f"Kibana search request: {json.dumps(payload)}")
    
    # Execute request with retry logic
    max_retries = 3
    retry_count = 0
    last_error = None
    
    # Create a new client for this request
    async with get_http_client() as client:
        while retry_count < max_retries:
            try:
                # Make the request
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    cookies=cookies,
                    timeout=20
                )
                
                # Handle response
                status_code = response.status_code
                if status_code == 200:
                    # Parse the response JSON
                    try:
                        # Try the async way first
                        result = await response.json()
                    except (TypeError, AttributeError):
                        # Fall back to direct access if json is not async callable
                        if callable(response.json):
                            result = response.json()
                        else:
                            result = response.json
                    
                    # Ensure we have a dictionary/JSON object
                    if hasattr(result, '__call__'):
                        logger.error("Response JSON is a method, not a value")
                        result = {"error": "Invalid response format", "rawResponse": {"hits": {"hits": []}}}
                    
                    logger.debug(f"Kibana search response status: 200 OK")
                    return result
                else:
                    # Get error text - fix for httpx response.text
                    try:
                        # Try the async way first
                        error_text = await response.text()
                    except (TypeError, AttributeError):
                        # Fall back to property access if text is not callable
                        error_text = response.text
                        
                    logger.error(f"Kibana search failed: {status_code} {error_text}")
                    last_error = f"{status_code}: {error_text}"
                    
                    # If we get a 400 with "no mapping found" for timestamp, try without sorting
                    if (status_code == 400 and 
                        "No mapping found for" in error_text and 
                        "in order to sort on" in error_text):
                        
                        logger.warning(f"Timestamp field '{timestamp_field}' not found in index. Trying without sort.")
                        # Remove the sort and try again
                        if "sort" in search_body:
                            del search_body["sort"]
                            payload["params"]["body"] = search_body
                            logger.debug(f"Retrying without sort: {json.dumps(payload)}")
                            continue
                    
                    # If it's an authentication issue, let's return a clear error
                    if status_code in (401, 403):
                        logger.error(f"Authentication failed: {status_code} {error_text}")
                        last_error = "Authentication failed. Check your Kibana auth token."
            
            except Exception as e:
                logger.error(f"Error during Kibana search: {str(e)}")
                import traceback
                logger.error(f"Stack trace: {traceback.format_exc()}")
                last_error = str(e)
                
            # Increase retry counter
            retry_count += 1
            if retry_count < max_retries:
                logger.warning(f"Retrying Kibana search ({retry_count}/{max_retries})...")
                await asyncio.sleep(1)  # Wait before retrying
    
    # If we reached here, all retries failed
    final_error_message = f"Kibana API request failed after {max_retries} retries."
    error_details = last_error if last_error else "Unknown error after multiple retries."
    logger.error(f"{final_error_message} Last error: {error_details}")
    
    return {
        "error": final_error_message,
        "details": error_details,
        "took": 0,
        "timed_out": True,
        "_shards": {
            "total": 0, 
            "successful": 0, 
            "skipped": 0, 
            "failed": 0 
        },
        "hits": { 
            "total": {"value": 0, "relation": "eq"},
            "max_score": None,
            "hits": []
        },
        "rawResponse": { 
             "hits": {
                "total": {"value": 0, "relation": "eq"},
                "max_score": None,
                "hits": []
            }
        }
    }

# === MCP Tools ===

@mcp.tool()
async def get_recent_logs(count: int = 10, level: Optional[str] = None, ctx: Context = None) -> List[Dict]:
    """
    Retrieve the most recent Kibana logs.
    
    Args:
        count: Number of logs to retrieve (default: 10)
        level: Filter by log level (e.g., "info", "error", "warn")
        
    Returns:
        List of recent log entries
    """
    # Validate input
    max_logs = CONFIG["processing"]["max_logs"]
    if count > max_logs:
        count = max_logs
        ctx.info(f"Limited request to {max_logs} logs")
    
    # Build query
    query = {"match_all": {}}
    if level:
        query = {"match": {"level": level}}
    
    index_pattern = f"{es_config['index_prefix']}*"
    try:
        # Use Kibana API to search
        result = await kibana_search(index_pattern, query, size=count)
        
        if "error" in result:
            logger.error(f"Error retrieving recent logs: {result['error']}")
            return {"error": result["error"]}
        
        # Process results
        logs = []
        if "hits" in result and "hits" in result["hits"]:
            logs = [doc["_source"] for doc in result["hits"]["hits"]]
            
            # Normalize timestamp fields
            for log in logs:
                # Check for various timestamp field names and normalize
                timestamp = None
                for field in ["@timestamp", "timestamp", "time", "start_time", "created_at"]:
                    if field in log:
                        timestamp = log[field]
                        break
                
                # Add a normalized timestamp field if any timestamp was found
                if timestamp:
                    log["normalized_timestamp"] = timestamp
            
            logger.debug(f"Retrieved {len(logs)} recent logs")
        else:
            logger.warning(f"No hits found in search result: {result}")
            
        return logs
        
    except Exception as e:
        logger.error(f"Error retrieving recent logs: {e}")
        return {"error": str(e)}


@mcp.tool()
async def search_logs(
    query_text: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    levels: Optional[List[str]] = None,
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    max_results: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = "desc",
    ctx: Context = None
) -> Dict:
    """
    Search Kibana logs with flexible criteria.
    
    Args:
        query_text: Text to search for in log messages
        start_time: Start time for logs (ISO format or relative like '1h')
        end_time: End time for logs (ISO format)
        levels: List of log levels to include (e.g., ["error", "warn"])
        include_fields: Fields to include in results
        exclude_fields: Fields to exclude from results
        max_results: Maximum number of results to return
        sort_by: Field to sort results by (default: timestamp defined in config)
        sort_order: Order to sort results ("asc" or "desc", default: "desc")
        
    Returns:
        Dictionary with search results and metadata
    """
    try:
        # Validate input
        max_logs = CONFIG["processing"]["max_logs"]
        if max_results > max_logs:
            max_results = max_logs
            if ctx:
                ctx.info(f"Limited request to {max_logs} logs")
        
        # Build query
        must_clauses = []
        
        # Add text search if provided
        if query_text:
            must_clauses.append({
                "query_string": {
                    "query": query_text
                }
            })
        
        # Add time range if provided - try multiple timestamp fields
        if start_time or end_time:
            # Define potential timestamp fields to check
            timestamp_fields = ["@timestamp", "timestamp", "time", "start_time", "created_at"]
            
            # Build time range conditions
            time_range = {}
            if start_time:
                time_range["gte"] = start_time
            if end_time:
                time_range["lte"] = end_time
            
            # Build a should clause for any of the timestamp fields
            time_should_clauses = []
            for field in timestamp_fields:
                time_should_clauses.append({
                    "range": {
                        field: time_range
                    }
                })
            
            # Add the time filter as a should clause (match any timestamp field)
            if time_should_clauses:
                must_clauses.append({
                    "bool": {
                        "should": time_should_clauses,
                        "minimum_should_match": 1
                    }
                })
        
        # Add log level filter if provided
        if levels and len(levels) > 0:
            must_clauses.append({
                "terms": {
                    "level": levels
                }
            })
        
        # Construct the final query
        query = {"match_all": {}}
        if must_clauses:
            query = {
                "bool": {
                    "must": must_clauses
                }
            }
        
        # Prepare sort parameter
        sort_param = None
        if sort_by:
            # Using explicit sort field from parameter
            sort_param = [{sort_by: {"order": sort_order}}]
            logger.debug(f"Using explicit sort: {sort_param}")
        
        # Execute search against relevant indices
        index_pattern = f"{es_config['index_prefix']}*"
        result = await kibana_search(index_pattern, query, size=max_results, sort=sort_param)
        
        # Process results
        if isinstance(result, dict):
            if "rawResponse" in result:
                # Handle Kibana API format (new style)
                raw_response = result.get("rawResponse", {})
                hits = raw_response.get("hits", {}).get("hits", [])
                
                if not hits:
                    logger.warning(f"No logs found matching query. Response: {raw_response}")
                    
                # Extract documents and normalize
                docs = []
                for hit in hits:
                    if "_source" in hit:
                        doc = hit["_source"]
                        # Add metadata from the hit
                        doc["_index"] = hit.get("_index", "")
                        doc["_score"] = hit.get("_score", 0)
                        
                        # Apply field filtering if requested
                        if include_fields:
                            doc = {k: v for k, v in doc.items() if k in include_fields}
                        elif exclude_fields:
                            doc = {k: v for k, v in doc.items() if k not in exclude_fields}
                        
                        docs.append(doc)
                
                # Return search results
                return {
                    "success": True,
                    "total": len(docs),
                    "logs": docs,
                    "query": query_text or "All logs",
                    "indices_searched": index_pattern,
                    "sort_by": sort_by or "Default timestamp field"
                }
            elif "hits" in result:
                # Handle Elasticsearch direct API format (old style)
                hits = result.get("hits", {}).get("hits", [])
                
                # Process results
                logs = []
                if "hits" in result and "hits" in result["hits"]:
                    logger.debug(f"Number of hits: {len(result['hits']['hits'])}")
                    logs = [doc["_source"] for doc in result["hits"]["hits"]]
                    
                    # Apply field filtering if specified
                    if include_fields:
                        logs = [{k: v for k, v in log.items() if k in include_fields} for log in logs]
                    elif exclude_fields:
                        logs = [{k: v for k, v in log.items() if k not in exclude_fields} for log in logs]
                        
                    # Normalize timestamp fields
                    for log in logs:
                        # Check for various timestamp field names and normalize
                        timestamp = None
                        for field in ["@timestamp", "timestamp", "time", "start_time", "created_at"]:
                            if field in log:
                                timestamp = log[field]
                                break
                        
                        # Add a normalized timestamp field if any timestamp was found
                        if timestamp:
                            log["normalized_timestamp"] = timestamp
                else:
                    logger.warning(f"No hits found in search result: {result}")
                
                # Get total count, handling both int and dict formats
                total = 0
                if "hits" in result and "total" in result["hits"]:
                    if isinstance(result["hits"]["total"], dict) and "value" in result["hits"]["total"]:
                        total = result["hits"]["total"]["value"]
                    elif isinstance(result["hits"]["total"], int):
                        total = result["hits"]["total"]
                    else:
                        logger.warning(f"Unexpected total format: {result['hits']['total']}")
                        total = len(logs)
                else:
                    total = len(logs)
                
                # Return search results
                return {
                    "success": True,
                    "total": total,
                    "logs": logs,
                    "query": query_text or "All logs",
                    "indices_searched": index_pattern,
                    "sort_by": sort_by or "Default timestamp field"
                }
            elif "error" in result:
                # Handle error case
                logger.error(f"Error searching logs: {result.get('error')}")
                return {
                    "success": False,
                    "error": result.get("error"),
                    "logs": [],
                    "query": query_text or "All logs"
                }
            else:
                # Unknown format
                logger.error(f"Unexpected result format: {result}")
                return {
                    "success": False,
                    "error": "Unexpected response format from Kibana",
                    "logs": [],
                    "query": query_text or "All logs"
                }
        else:
            logger.error(f"Non-dict result received: {type(result)}")
            return {
                "success": False,
                "error": f"Unexpected response type: {type(result)}",
                "logs": [],
                "query": query_text or "All logs"
            }
    
    except Exception as e:
        logger.error(f"Error searching logs: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return error with mock data
        return {
            "success": False,
            "error": str(e),
            "logs": [],
            "query": query_text or "All logs"
        }


@mcp.tool()
async def analyze_logs(
    time_range: str = "1h",
    group_by: Optional[str] = "level",
    ctx: Context = None
) -> Dict:
    """
    Analyze logs to identify patterns and provide statistics.
    
    Args:
        time_range: Time range to analyze (e.g. "1h", "1d", "7d")
        group_by: Field to group results by (e.g. "level", "service", "status")
        
    Returns:
        Dict containing analysis results and aggregations
    """
    # Parse time range
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Convert time range to datetime
    unit = time_range[-1]
    value = int(time_range[:-1])
    
    if unit == 'h':
        start_time = now - datetime.timedelta(hours=value)
    elif unit == 'd':
        start_time = now - datetime.timedelta(days=value)
    elif unit == 'w':
        start_time = now - datetime.timedelta(weeks=value)
    else:
        start_time = now - datetime.timedelta(hours=1)  # Default to 1 hour
        
    # Format start time as ISO
    start_time_iso = start_time.isoformat()
    
    # Define potential timestamp fields to check
    timestamp_fields = ["@timestamp", "timestamp", "time", "start_time", "created_at"]
    
    # Build time range conditions for any timestamp field
    time_should_clauses = []
    for field in timestamp_fields:
        time_should_clauses.append({
            "range": {
                field: {
                    "gte": start_time_iso
                }
            }
        })
    
    # Build query for time range
    query = {
        "bool": {
            "should": time_should_clauses,
            "minimum_should_match": 1
        }
    }
    
    try:
        # Execute search to get logs
        index_pattern = f"{es_config['index_prefix']}*"
        result = await kibana_search(index_pattern, query, size=0)
        
        if "error" in result:
            logger.error(f"Error analyzing logs: {result['error']}")
            return {"error": result["error"]}
        
        # Since we can't do aggregations directly with the Kibana API,
        # we'll fetch a sample of logs and do the aggregation in memory
        sample_result = await kibana_search(index_pattern, query, size=1000)
        
        if "error" in sample_result:
            logger.error(f"Error fetching sample logs: {sample_result['error']}")
            return {"error": sample_result["error"]}
        
        # Process results
        logs = []
        if "hits" in sample_result and "hits" in sample_result["hits"]:
            logs = [doc["_source"] for doc in sample_result["hits"]["hits"]]
        else:
            logger.warning(f"No hits found in search result: {sample_result}")
            return {
                "total_logs": 0,
                "time_range": time_range,
                "error_rate": 0,
                "aggregations": {}
            }
            
        total_logs = len(logs)
        
        # Perform aggregation
        aggregations = {}
        if group_by:
            counts = {}
            for log in logs:
                if group_by in log:
                    key = log[group_by]
                    if key not in counts:
                        counts[key] = 0
                    counts[key] += 1
            
            aggregations[group_by] = counts
        
        # Calculate error rate
        error_count = 0
        for log in logs:
            if "level" in log and log["level"].lower() in ["error", "fatal", "critical"]:
                error_count += 1
                
        error_rate = error_count / total_logs if total_logs > 0 else 0
        
        return {
            "total_logs": total_logs,
            "time_range": time_range,
            "error_rate": error_rate,
            "aggregations": aggregations
        }
            
    except Exception as e:
        logger.error(f"Error analyzing logs: {e}")
        return {"error": str(e)}


@mcp.tool()
async def extract_errors(
    hours: int = 24,
    include_stack_traces: bool = True,
    limit: int = 10,
    ctx: Context = None
) -> Dict:
    """
    Extract error logs with optional stack traces.
    
    Args:
        hours: Number of hours to look back
        include_stack_traces: Whether to include stack traces in results
        limit: Maximum number of errors to return
        
    Returns:
        Dict containing error logs and metadata
    """
    # Calculate time range
    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = now - datetime.timedelta(hours=hours)
    start_time_iso = start_time.isoformat()
    
    # Define potential timestamp fields to check
    timestamp_fields = ["@timestamp", "timestamp", "time", "start_time", "created_at"]
    
    # Build time range conditions for any timestamp field
    time_should_clauses = []
    for field in timestamp_fields:
        time_should_clauses.append({
            "range": {
                field: {
                    "gte": start_time_iso
                }
            }
        })
    
    # Build query for errors within time range
    query = {
        "bool": {
            "must": [
                {
                    "terms": {
                        "level": ["error", "fatal", "critical"]
                    }
                }
            ],
            "should": time_should_clauses,
            "minimum_should_match": 1
        }
    }
    
    try:
        # Execute search
        index_pattern = f"{es_config['index_prefix']}*"
        result = await kibana_search(index_pattern, query, size=limit)
        
        if "error" in result:
            logger.error(f"Error extracting errors: {result['error']}")
            return {"error": result["error"]}
        
        # Process results
        errors = []
        if "hits" in result and "hits" in result["hits"]:
            for doc in result["hits"]["hits"]:
                error = doc["_source"]
                
                # Extract stack trace if available and requested
                stack_trace = None
                if include_stack_traces:
                    if "error" in error and "stack_trace" in error["error"]:
                        stack_trace = error["error"]["stack_trace"]
                    elif "stack_trace" in error:
                        stack_trace = error["stack_trace"]
                        
                # Find timestamp
                timestamp = None
                for field in timestamp_fields:
                    if field in error:
                        timestamp = error[field]
                        break
                
                # Add to results
                errors.append({
                    "timestamp": timestamp,
                    "level": error.get("level", "error"),
                    "message": error.get("message", ""),
                    "service": error.get("service", ""),
                    "stack_trace": stack_trace
                })
        else:
            logger.warning(f"No hits found in search result: {result}")
        
        return {
            "errors": errors,
            "total": result["hits"]["total"]["value"] if "hits" in result and "total" in result["hits"] else len(errors),
            "hours": hours
        }
            
    except Exception as e:
        logger.error(f"Error extracting errors: {e}")
        return {"error": str(e)}







# === Helper Functions ===



# New MCP tool to set auth token
@mcp.tool()
async def summarize_logs(
    query_text: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    levels: Optional[List[str]] = None,
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    max_results: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = "desc",
    ctx: Context = None
) -> Dict:
    """
    Search logs and generate AI-powered analysis using Neurolink.
    
    This function accepts the same parameters as search_logs() and internally calls it
    to fetch logs, then uses Neurolink to generate structured analysis including:
    - Summary of log activities
    - Key insights and patterns
    - Errors and exceptions
    - Function calls
    - Timestamp-based flow
    - Anomalies detection
    - Focus points for developers
    - Recommendations for next steps
    
    Args:
        query_text: Text to search for in log messages
        start_time: Start time for logs (ISO format or relative like '1h')
        end_time: End time for logs (ISO format)
        levels: List of log levels to include (e.g., ["error", "warn"])
        include_fields: Fields to include in results
        exclude_fields: Fields to exclude from results
        max_results: Maximum number of results to return
        sort_by: Field to sort results by (default: timestamp defined in config)
        sort_order: Order to sort results ("asc" or "desc", default: "desc")
        
    Returns:
        Dictionary with AI-generated analysis and original search metadata
    """
    try:
        # Check if this is a function-based mode query by examining the query_text
        is_function_based = False
        if query_text and ("FunctionCallResult" in query_text or "FunctionCalled" in query_text):
            is_function_based = True
            logger.info(f"Detected function-based mode query: {query_text}")
            
            # For function-based mode, we should always sort by timestamp in ascending order
            if not sort_by:
                sort_by = "timestamp"
            if not sort_order or sort_order.lower() != "asc":
                sort_order = "asc"
                logger.info("Function-based mode: Setting sort_order to 'asc'")

        # First, call search_logs to get the log data
        logger.info(f"Fetching logs for summarization with max_results={max_results}")
        search_result = await search_logs(
            query_text=query_text,
            start_time=start_time,
            end_time=end_time,
            levels=levels,
            include_fields=include_fields,
            exclude_fields=exclude_fields,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
            ctx=ctx
        )
        
        # Check if search was successful
        if not search_result.get("success", False):
            return {
                "success": False,
                "error": f"Failed to fetch logs: {search_result.get('error', 'Unknown error')}",
                "analysis": {
                    "summary": f"Error: {search_result.get('error', 'Unknown error')}",
                    "key_insights": [],
                    "errors": [],
                    "function_calls": [],
                    "timestamp_flow": "",
                    "anomalies": [],
                    "focus_areas": [],
                    "recommendations": []
                },
                "search_metadata": search_result
            }
        
        logs = search_result.get("logs", [])
        if not logs:
            return {
                "success": True,
                "analysis": {
                    "summary": "No logs found matching the search criteria.",
                    "key_insights": [],
                    "errors": [],
                    "function_calls": [],
                    "timestamp_flow": "No logs to analyze",
                    "anomalies": [],
                    "focus_areas": [],
                    "recommendations": []
                },
                "search_metadata": {
                    "total_logs": 0,
                    "query": search_result.get("query"),
                    "indices_searched": search_result.get("indices_searched"),
                    "sort_by": search_result.get("sort_by"),
                    "sort_order": sort_order
                }
            }
        
        logger.info(f"Processing {len(logs)} logs for AI analysis")
        
        # Generate AI analysis using Neurolink
        analysis = await _generate_log_analysis_with_neurolink(logs, is_function_based)
        
        return {
            "success": True,
            "analysis": analysis,
            "search_metadata": {
                "total_logs": len(logs),
                "query": search_result.get("query"),
                "indices_searched": search_result.get("indices_searched"),
                "sort_by": search_result.get("sort_by"),
                "sort_order": sort_order,
                "is_function_based": is_function_based
            }
        }
        
    except Exception as e:
        logger.error(f"Error in summarize_logs: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return {
            "success": False,
            "error": str(e),
            "analysis": {
                "summary": f"Error occurred during analysis: {str(e)}",
                "key_insights": [],
                "errors": [],
                "function_calls": [],
                "timestamp_flow": "",
                "anomalies": [],
                "focus_areas": [],
                "recommendations": []
            },
            "search_metadata": None
        }

async def _generate_log_analysis_with_neurolink(logs: List[Dict], is_function_based: bool = False) -> Dict:
    """
    Generate AI-powered log analysis using Neurolink.
    
    Args:
        logs: List of log entries to analyze
        is_function_based: Whether this is a function-based mode analysis
        
    Returns:
        Dictionary containing structured analysis
    """
    import subprocess
    import json
    import tempfile
    import os
    
    # Base prompt template for Neurolink
    BASE_PROMPT_TEMPLATE = """
You are a senior system engineer and log analysis expert. The following data consists of raw backend logs generated during the execution of various services and operations in a production environment. These logs may contain function calls, status updates, error traces, and system-level metadata.

Your task is to deeply analyze the provided log chunk and generate a structured, HIGHLY DETAILED and comprehensive summary with absolutely no loss of technical detail. Be precise, thorough, and exhaustive in your analysis. Do not summarize or condense information - provide complete details for each section.

Given the following logs:

{LOGS_CHUNK}

Generate an extremely detailed analysis with the following sections:

1. Summary
   Provide a comprehensive overview of what these logs represent. Mention which services or systems are involved, describe the general activity captured in this chunk, and include all relevant technical details about the environment, versions, and components involved.

2. Key Insights
   Extract ALL important insights or recurring themes. Include detailed descriptions of system behaviors, unexpected events, patterns, retry mechanisms, performance delays, or configuration mismatches. Provide specific examples from the logs for each insight.

3. Errors and Exceptions
   List ALL errors, exceptions, or stack traces encountered in the logs. Include complete message snippets, error codes, affected modules or functions, and potential root causes. Group related errors together and explain their relationships.

4. Function Calls
   Identify ALL functions or methods invoked throughout the logs. Provide a comprehensive list organized by service/component. Mention frequently recurring calls with their parameters and return values, and highlight those that seem critical or error-prone. Show the relationships between function calls.

5. Timestamp-Based Flow
   Reconstruct the detailed chronological flow of the logs. Provide a step-by-step timeline of how the system events unfolded in order, using available timestamps to show progression or delays. Include specific timestamps and durations between key events.

6. Anomalies
   Highlight ALL anomalies, inconsistencies, time gaps, suspicious behavior, or abnormal responses in the logs. For each anomaly, provide specific evidence from the logs, potential causes, and severity assessment.

7. Important Focus Areas
   List ALL areas that need developer attention, such as failing services, slow processes, missing data, degraded performance, or broken workflows. For each area, provide detailed evidence from the logs and explain why it requires attention.

8. Recommendations
   Based on your analysis, suggest comprehensive next steps, fixes, or areas for further investigation. Provide specific, actionable recommendations for each issue identified, with technical details on how to implement them.

The output must be extremely detailed, well-structured and technically sound. DO NOT provide generic or brief summaries. Include ALL relevant technical details, patterns, and insights from the logs. Focus on helping a backend engineer understand system behavior and quickly locate problems.

Please respond with a valid JSON object containing the extremely detailed analysis in the following format:
{
  "summary": "...",
  "key_insights": ["...", "..."],
  "errors": ["...", "..."],
  "function_calls": ["...", "..."],
  "timestamp_flow": "...",
  "anomalies": ["...", "..."],
  "focus_areas": ["...", "..."],
  "recommendations": ["...", "..."]
}
"""

    # Enhanced function-based prompt template
    FUNCTION_BASED_PROMPT_TEMPLATE = """
You are a senior system engineer and log analysis expert specializing in function call tracing and execution flow analysis. The following data consists of backend logs focused on function calls and their results during the execution of various services and operations in a production environment.

Your task is to deeply analyze the provided log chunk and generate a structured, HIGHLY DETAILED and comprehensive summary with absolutely no loss of technical detail. Be precise, thorough, and exhaustive in your analysis. Do not summarize or condense information - provide complete details for each section.

Given the following logs:

{LOGS_CHUNK}

Generate an extremely detailed analysis with the following sections:

1. Summary
   Provide a comprehensive overview of what these logs represent. Mention which services or systems are involved, describe the general activity captured in this chunk, and include all relevant technical details about the environment, versions, and components involved.

2. Key Insights
   Extract ALL important insights about function execution patterns, data flows, state transitions, and system behaviors. Include detailed descriptions of notable sequences, parameter patterns, and critical function chains. Provide specific examples from the logs for each insight.

3. Errors and Exceptions
   List ALL errors, exceptions, or failures encountered in function calls. Include complete error messages, error codes, affected functions, and potential root causes. Group related errors together and explain their relationships.

4. Function Calls
   Create a comprehensive list of ALL functions called, organized by service/module. For each function, include parameters, return values, and execution context. Highlight the most critical functions in the execution flow and their relationships. Show the complete call hierarchy where possible.

5. Timestamp-Based Flow
   Reconstruct the detailed chronological execution flow of functions. Provide a step-by-step timeline showing the sequence of calls, their timing, and any notable delays or gaps between related calls. Include specific timestamps and durations between key events.

6. Anomalies
   Identify ALL anomalies in function execution, such as unexpected parameter values, missing expected calls, unusual sequences, or abnormal return values. For each anomaly, provide specific evidence from the logs, potential causes, and severity assessment.

7. Important Focus Areas
   List ALL specific functions or code areas that need developer attention, such as error-prone functions, performance bottlenecks, or potential logic issues. For each area, provide detailed evidence from the logs and explain why it requires attention.

8. Recommendations
   Based on your analysis of the function execution flow, suggest comprehensive and specific improvements, optimizations, or fixes for the identified issues. Provide detailed, actionable recommendations for each issue, with technical details on how to implement them.

The output must be extremely detailed, well-structured and technically sound. DO NOT provide generic or brief summaries. Include ALL relevant technical details, patterns, and insights from the logs. Focus on helping a backend engineer understand the execution flow and quickly identify issues in the function call chain.

Please respond with a valid JSON object containing the extremely detailed analysis in the following format:
{
  "summary": "...",
  "key_insights": ["...", "..."],
  "errors": ["...", "..."],
  "function_calls": ["...", "..."],
  "timestamp_flow": "...",
  "anomalies": ["...", "..."],
  "focus_areas": ["...", "..."],
  "recommendations": ["...", "..."]
}
"""
    
    try:
        # Select the appropriate prompt template based on the mode
        PROMPT_TEMPLATE = FUNCTION_BASED_PROMPT_TEMPLATE if is_function_based else BASE_PROMPT_TEMPLATE
        
        # Check if we have many logs - if so, chunk them
        if len(logs) > 25:
            logger.info(f"Chunking {len(logs)} logs into smaller pieces for analysis")
            chunk_size = max(1, len(logs) // 4)  # Split into 4 chunks
            chunks = [logs[i:i + chunk_size] for i in range(0, len(logs), chunk_size)]
            
            # Analyze each chunk
            chunk_analyses = []
            for i, chunk in enumerate(chunks):
                logger.info(f"Analyzing chunk {i+1}/{len(chunks)} with {len(chunk)} logs")
                chunk_analysis = await _analyze_log_chunk_with_neurolink(chunk, PROMPT_TEMPLATE)
                if chunk_analysis:
                    chunk_analyses.append(chunk_analysis)
            
            # If we have multiple chunk analyses, combine them
            if len(chunk_analyses) > 1:
                logger.info("Combining chunk analyses into final summary")
                return await _combine_analyses_with_neurolink(chunk_analyses, PROMPT_TEMPLATE, is_function_based)
            elif len(chunk_analyses) == 1:
                return chunk_analyses[0]
            else:
                # Fallback if all chunks failed
                return _generate_fallback_analysis(logs, is_function_based)
        else:
            # Analyze all logs at once
            logger.info(f"Analyzing all {len(logs)} logs in single request")
            analysis = await _analyze_log_chunk_with_neurolink(logs, PROMPT_TEMPLATE)
            return analysis if analysis else _generate_fallback_analysis(logs, is_function_based)
            
    except Exception as e:
        logger.error(f"Error in _generate_log_analysis_with_neurolink: {str(e)}")
        return _generate_fallback_analysis(logs, is_function_based)

async def _analyze_log_chunk_with_neurolink(logs: List[Dict], prompt_template: str) -> Optional[Dict]:
    """
    Analyze a chunk of logs using Neurolink.
    
    Args:
        logs: List of log entries
        prompt_template: Template with {LOGS_CHUNK} placeholder
        
    Returns:
        Analysis dictionary or None if failed
    """
    import subprocess
    import json
    import tempfile
    import os
    import asyncio
    
    try:
        logger.info(f"Starting _analyze_log_chunk_with_neurolink with {len(logs)} logs")
        
        # Format logs as text
        logs_text = ""
        for i, log in enumerate(logs):
            logs_text += f"--- Log Entry {i+1} ---\n"
            try:
                logs_text += json.dumps(log, indent=2, default=str)
            except Exception as e:
                logger.error(f"Error serializing log entry {i+1}: {e}")
                logs_text += f"Error serializing log: {str(e)}"
            logs_text += "\n\n"
        
        logger.info(f"Formatted logs text length: {len(logs_text)}")
        
        # Create the prompt
        try:
            # Use simple string replacement instead of .format() to avoid issues with JSON content
            prompt = prompt_template.replace("{LOGS_CHUNK}", logs_text)
            logger.info(f"Created prompt, length: {len(prompt)}")
        except Exception as e:
            logger.error(f"Error formatting prompt: {e}")
            logger.error(f"Logs text sample: {logs_text[:500]}")
            return None
        
        # Set up environment for Neurolink
        # Start with a copy of the current environment
        env = os.environ.copy()
        
        # Load AI provider keys from config.yaml and override environment variables
        # CONFIG is globally available and loaded from config.yaml
        ai_provider_keys_from_config = CONFIG.get("ai_providers", {})
        logger.info(f"Config ai_providers section: {ai_provider_keys_from_config}")
        if ai_provider_keys_from_config:
            logger.info(f"Loading AI provider API keys from config.yaml: {list(ai_provider_keys_from_config.keys())}")
            for key, value in ai_provider_keys_from_config.items():
                logger.info(f"Processing config key: {key} = {value[:10] if value else 'empty'}...")
                if value:  # Only set if the key has a value in config
                    env[key.upper()] = str(value) # Ensure keys are uppercase and values are strings
                    logger.info(f"Set {key.upper()} from config.yaml for Neurolink subprocess")
                elif key.upper() in env:
                    # If the key is empty in config but exists in os.environ, keep the os.environ one
                    logger.debug(f"Kept {key.upper()} from os.environ as it was empty in config.yaml")
        else:
            logger.warning("No ai_providers section found in config.yaml")
        
        # Check for Google AI API key (recommended provider)
        # This check is now after config.yaml keys have been potentially set
        logger.info(f"Environment variables check - GOOGLE_AI_API_KEY exists: {'GOOGLE_AI_API_KEY' in env}")
        if "GOOGLE_AI_API_KEY" in env:
            logger.info(f"GOOGLE_AI_API_KEY value: {env['GOOGLE_AI_API_KEY'][:10]}...")
        
        if "GOOGLE_AI_API_KEY" not in env or not env["GOOGLE_AI_API_KEY"]:
            logger.warning("GOOGLE_AI_API_KEY not found in environment or config.yaml. Neurolink may use a different provider or fallback.")
            # Try to find any available API keys
            available_keys = [k for k, v in env.items() if k.endswith('_API_KEY') and v]
            if available_keys:
                logger.info(f"Available API keys for Neurolink: {available_keys}")
            else:
                logger.error("No AI provider API keys found. Neurolink will likely fail.")
                return None
        else:
            logger.info("GOOGLE_AI_API_KEY is configured for Neurolink.")
            logger.debug(f"GOOGLE_AI_API_KEY starts with: {env['GOOGLE_AI_API_KEY'][:8]}...")

        # Create temp file for the prompt
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name
        
        try:
            # Read the prompt from the temp file since Neurolink expects prompt as positional argument
            with open(prompt_file, 'r') as f:
                prompt_content = f.read()
            
            # Get AI response settings from config
            ai_settings = CONFIG.get("ai_response_settings", {})
            max_tokens = ai_settings.get("max_tokens", 8000000)
            timeout_ms = ai_settings.get("timeout_ms", 600000)
            temperature = ai_settings.get("temperature", 0.2)
            detailed_mode = ai_settings.get("detailed_mode", True)
            
            # Run Neurolink with Google AI Studio as the preferred provider
            cmd = [
                "npx", "@juspay/neurolink", "generate-text", 
                prompt_content,  # Prompt as positional argument
                "--provider", "google-ai",
                "--max-tokens", str(max_tokens),  # Use value from config
                "--timeout", str(timeout_ms),  # Use value from config
                "--temperature", str(temperature),  # Use value from config
            ]
            
            # Add detailed mode flag if enabled
            if detailed_mode:
                cmd.extend(["--detailed-mode", "true"])
            
            logger.info(f"Running Neurolink command: {' '.join(cmd[:3])}... (prompt truncated)")
            logger.info(f"Command environment has GOOGLE_AI_API_KEY: {'GOOGLE_AI_API_KEY' in env}")
            logger.info(f"Using AI settings: max_tokens={max_tokens}, timeout={timeout_ms}ms, temperature={temperature}, detailed_mode={detailed_mode}")
            
            # Run the command asynchronously
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                
                # Convert timeout from ms to seconds for asyncio
                timeout_seconds = timeout_ms / 1000
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)  # Use timeout from config
                
                logger.info(f"Neurolink process completed with return code: {process.returncode}")
                if stderr:
                    logger.info(f"Neurolink stderr: {stderr.decode()}")
                
                if process.returncode != 0:
                    logger.error(f"Neurolink command failed with return code {process.returncode}")
                    logger.error(f"stderr: {stderr.decode()}")
                    return None
            except Exception as e:
                logger.error(f"Error running Neurolink subprocess: {str(e)}")
                return None
            
            # Parse the response
            response_text = stdout.decode().strip()
            # Log more of the response for debugging
            logger.info(f"Neurolink raw response (first 1000 chars): {response_text[:1000]}")
            logger.info(f"Neurolink raw response (last 500 chars): {response_text[-500:]}")
            
            # Neurolink returns responses in markdown format with ```json code blocks
            # Extract JSON from markdown code blocks first
            if '```json' in response_text:
                start_marker = '```json'
                end_marker = '```'
                start_idx = response_text.find(start_marker) + len(start_marker)
                end_idx = response_text.find(end_marker, start_idx)
                if start_idx != -1 and end_idx != -1:
                    json_str = response_text[start_idx:end_idx].strip()
                    try:
                        analysis = json.loads(json_str)
                        logger.info(f"Successfully parsed JSON from markdown: {json_str[:200]}...")
                        # Log the size of each section for debugging
                        for key, value in analysis.items():
                            if isinstance(value, str):
                                logger.info(f"Section '{key}' length: {len(value)} chars")
                            elif isinstance(value, list):
                                logger.info(f"Section '{key}' items: {len(value)}, total chars: {sum(len(str(item)) for item in value)}")
                        return analysis
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON from markdown: {e}")
                        logger.error(f"Problematic JSON string: {json_str[:200]}...")
            
            # Try to extract JSON from the response (fallback)
            try:
                # First, try to parse the entire response as JSON (if it's pure JSON)
                neurolink_response = json.loads(response_text)
                logger.debug(f"Successfully parsed entire response as JSON")
                return neurolink_response
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse entire response as JSON: {e}")
                # Try to find JSON in the raw response
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                if start_idx != -1 and end_idx != -1:
                    try:
                        json_str = response_text[start_idx:end_idx]
                        analysis = json.loads(json_str)
                        logger.info(f"Successfully extracted JSON from response: {json_str[:200]}...")
                        # Log the size of each section for debugging
                        for key, value in analysis.items():
                            if isinstance(value, str):
                                logger.info(f"Section '{key}' length: {len(value)} chars")
                            elif isinstance(value, list):
                                logger.info(f"Section '{key}' items: {len(value)}, total chars: {sum(len(str(item)) for item in value)}")
                        return analysis
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse extracted JSON: {e}")
                        logger.error(f"Problematic JSON string: {json_str[:200]}...")
                
                # If all JSON parsing fails, parse as text
                logger.info("No valid JSON found, parsing as text")
                return _parse_text_response_to_analysis(response_text)
                
        finally:
            # Clean up temp file
            try:
                os.unlink(prompt_file)
            except:
                pass
                
    except asyncio.TimeoutError:
        logger.error(f"Neurolink request timed out after {timeout_seconds} seconds")
        return None
    except Exception as e:
        logger.error(f"Error calling Neurolink: {str(e)}")
        return None

async def _combine_analyses_with_neurolink(analyses: List[Dict], prompt_template: str, is_function_based: bool = False) -> Dict:
    """
    Combine multiple chunk analyses into a final summary using Neurolink.
    
    Args:
        analyses: List of analysis dictionaries from chunks
        prompt_template: Template for the prompt
        is_function_based: Whether this is a function-based mode analysis
        
    Returns:
        Combined analysis dictionary
    """
    try:
        # Format the analyses as text for combination
        combined_text = "=== CHUNK ANALYSES TO COMBINE ===\n\n"
        for i, analysis in enumerate(analyses):
            combined_text += f"--- Analysis {i+1} ---\n"
            combined_text += json.dumps(analysis, indent=2)
            combined_text += "\n\n"
        
        # Use the same prompt template but with the analyses as input
        modified_prompt = prompt_template.replace(
            "Given the following logs:",
            "Given the following pre-analyzed log summaries from different chunks:"
        )
        
        if is_function_based:
            modified_prompt = modified_prompt.replace(
                "backend logs focused on function calls and their results",
                "pre-analyzed summaries of function call logs from different time periods or chunks"
            )
        else:
            modified_prompt = modified_prompt.replace(
                "raw backend logs generated during the execution",
                "pre-analyzed summaries of backend logs from different time periods or chunks"
            )
        
        # Add special instructions for combining analyses
        modified_prompt = modified_prompt.replace(
            "Generate a detailed analysis with the following sections:",
            "Generate a comprehensive combined analysis with the following sections. Focus on creating a cohesive narrative across all chunks, highlighting patterns, progressions, and relationships:"
        )
        
        # Analyze the combined analyses
        result = await _analyze_log_chunk_with_neurolink([{"combined_analyses": combined_text}], modified_prompt)
        return result if result else _generate_fallback_combined_analysis(analyses, is_function_based)
        
    except Exception as e:
        logger.error(f"Error combining analyses: {str(e)}")
        return _generate_fallback_combined_analysis(analyses, is_function_based)

def _parse_text_response_to_analysis(response_text: str) -> Dict:
    """
    Parse a text response into structured analysis format.
    
    Args:
        response_text: Raw text response from Neurolink
        
    Returns:
        Structured analysis dictionary
    """
    # Initialize default structure with empty values
    analysis = {
        "summary": "",
        "key_insights": [],
        "errors": [],
        "function_calls": [],
        "timestamp_flow": "",
        "anomalies": [],
        "focus_areas": [],
        "recommendations": []
    }
    
    try:
        # First try to extract JSON from the response
        import json
        import re
        
        # Look for JSON objects in the text
        json_pattern = r'(\{[\s\S]*\})'
        json_matches = re.findall(json_pattern, response_text)
        
        for potential_json in json_matches:
            try:
                parsed_json = json.loads(potential_json)
                if isinstance(parsed_json, dict):
                    # Check if this looks like our expected format
                    if any(key in parsed_json for key in analysis.keys()):
                        logger.info("Found valid JSON structure in response")
                        
                        # Copy over the values from the parsed JSON
                        for key in analysis.keys():
                            if key in parsed_json and parsed_json[key]:
                                analysis[key] = parsed_json[key]
                        
                        # If we found a valid analysis JSON, return it
                        return analysis
            except json.JSONDecodeError:
                continue
        
        # If no valid JSON was found, fall back to text parsing
        logger.info("No valid JSON found, parsing as text")
        
        # Simple parsing - look for sections in the text
        lines = response_text.split('\n')
        current_section = None
        current_content = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check for section headers - more robust pattern matching
            if re.search(r'(^|\s)1\.(\s|$)|summary', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'summary'
                current_content = []
                # Extract content after the header if it exists
                if ':' in line:
                    current_content.append(line.split(':', 1)[1].strip())
            elif re.search(r'(^|\s)2\.(\s|$)|key insights', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'key_insights'
                current_content = []
            elif re.search(r'(^|\s)3\.(\s|$)|errors|exceptions', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'errors'
                current_content = []
            elif re.search(r'(^|\s)4\.(\s|$)|function calls', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'function_calls'
                current_content = []
            elif re.search(r'(^|\s)5\.(\s|$)|timestamp|flow', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'timestamp_flow'
                current_content = []
            elif re.search(r'(^|\s)6\.(\s|$)|anomalies', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'anomalies'
                current_content = []
            elif re.search(r'(^|\s)7\.(\s|$)|focus areas|important', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'focus_areas'
                current_content = []
            elif re.search(r'(^|\s)8\.(\s|$)|recommendations', line.lower()):
                if current_section and current_content:
                    _add_content_to_analysis(analysis, current_section, current_content)
                current_section = 'recommendations'
                current_content = []
            elif line.startswith('-') or line.startswith('*') or re.match(r'^\d+\.', line):
                # This is a list item, add it to the current section
                if current_section:
                    # Remove the bullet point or number and add the content
                    cleaned = re.sub(r'^[-*]\s*|^\d+\.\s*', '', line).strip()
                    if cleaned:
                        current_content.append(cleaned)
            else:
                # Regular content line
                if current_section:
                    current_content.append(line)
        
        # Add the last section
        if current_section and current_content:
            _add_content_to_analysis(analysis, current_section, current_content)
        
        # If no structured content was found, put everything in summary
        if not any(v for v in analysis.values() if v):
            analysis['summary'] = response_text
            
    except Exception as e:
        logger.error(f"Error parsing text response: {str(e)}")
        analysis['summary'] = response_text
    
    # Ensure all sections have at least default values
    if not analysis['summary']:
        analysis['summary'] = "No summary available from analysis"
    
    # Return the analysis with all sections guaranteed to be present
    return analysis

def _add_content_to_analysis(analysis: Dict, section: str, content: List[str]):
    """Helper function to add parsed content to analysis structure."""
    content_text = ' '.join(content).strip()
    if not content_text:
        return
        
    if section in ['summary', 'timestamp_flow']:
        analysis[section] = content_text
    elif section in ['key_insights', 'errors', 'function_calls', 'anomalies', 'focus_areas', 'recommendations']:
        # Split content into list items if it contains bullet points or numbered items
        items = []
        for line in content:
            if line.strip():
                # Remove bullet points and numbers
                cleaned = line.strip().lstrip('•-*').lstrip('0123456789.').strip()
                if cleaned:
                    items.append(cleaned)
        analysis[section] = items if items else [content_text]

def _generate_fallback_analysis(logs: List[Dict], is_function_based: bool = False) -> Dict:
    """
    Generate a basic analysis when Neurolink is not available.
    
    Args:
        logs: List of log entries
        is_function_based: Whether this is a function-based mode analysis
        
    Returns:
        Basic analysis dictionary
    """
    try:
        # Basic analysis without AI
        error_count = 0
        warn_count = 0
        info_count = 0
        functions = set()
        errors = []
        timestamps = []
        
        # Extract function calls and other information from logs
        for log in logs:
            # Get level and count errors/warnings
            level = str(log.get('level', '')).lower()
            if 'error' in level:
                error_count += 1
                message = str(log.get('message', log.get('msg', '')))
                if message:
                    errors.append(message[:200])  # Truncate long messages
            elif 'warn' in level:
                warn_count += 1
            elif 'info' in level:
                info_count += 1
            
            # Extract function names from messages
            message = str(log.get('message', log.get('msg', '')))
            
            # Track timestamps for flow analysis
            timestamp = log.get('@timestamp', log.get('timestamp', None))
            if timestamp:
                timestamps.append(timestamp)
            
            # More aggressive function name extraction for function-based mode
            import re
            
            if is_function_based:
                # Look for "FunctionCalled" or "FunctionCallResult" patterns
                if "FunctionCalled" in message or "FunctionCallResult" in message:
                    # Extract function name - common patterns in logs
                    func_patterns = [
                        r'FunctionCalled:\s*(\w+)',
                        r'FunctionCallResult:\s*(\w+)',
                        r'Function\s+(\w+)\s+called',
                        r'Calling\s+function\s+(\w+)',
                        r'(\w+)\(\)',
                        r'(\w+)\(.*\)',
                        r'method\s+(\w+)',
                        r'service\.(\w+)',
                    ]
                    
                    for pattern in func_patterns:
                        matches = re.findall(pattern, message)
                        if matches:
                            functions.update(matches)
                            break
            else:
                # Standard function extraction for regular mode
                func_matches = re.findall(r'(\w+)\(', message)
                functions.update(func_matches)
                
                # Also look for common function call patterns
                service_method_matches = re.findall(r'(\w+)\.(\w+)', message)
                for match in service_method_matches:
                    if len(match[1]) > 2:  # Avoid short property accesses
                        functions.add(f"{match[0]}.{match[1]}")
        
        # Sort timestamps and create a basic flow
        timestamp_flow = "No timestamp information available"
        if timestamps:
            try:
                timestamps.sort()
                first_time = timestamps[0]
                last_time = timestamps[-1]
                timestamp_flow = f"Logs span from {first_time} to {last_time}"
            except:
                pass
        
        # Create appropriate summary based on mode
        if is_function_based:
            summary = f"Analyzed {len(logs)} log entries in function-based mode. Found {len(functions)} unique function calls, {error_count} errors, and {warn_count} warnings."
            
            # More detailed insights for function-based mode
            key_insights = [
                f"Total log entries: {len(logs)}",
                f"Unique functions identified: {len(functions)}",
                f"Error rate: {error_count/len(logs)*100:.1f}%" if logs else "No logs to analyze"
            ]
            
            # Add function call frequency if we have enough data
            if len(functions) > 0:
                key_insights.append(f"Most frequent functions: {', '.join(list(functions)[:5])}")
            
            # Focus areas for function-based mode
            focus_areas = []
            if error_count > 0:
                focus_areas.append(f"Functions with errors need investigation ({error_count} errors found)")
            if len(functions) < 3 and len(logs) > 10:
                focus_areas.append("Limited function visibility despite log volume")
            
            return {
                "summary": summary,
                "key_insights": key_insights,
                "errors": errors[:10],  # Limit to 10 errors
                "function_calls": list(functions),
                "timestamp_flow": timestamp_flow,
                "anomalies": [
                    "Function-based analysis requires AI processing for anomaly detection",
                    "Consider enabling AI provider for better insights"
                ],
                "focus_areas": focus_areas,
                "recommendations": [
                    "Configure an AI provider API key for detailed function flow analysis",
                    "Use sort_by=timestamp and sort_order=asc for optimal function flow visualization",
                    "Increase max_results for more complete function chain visibility"
                ]
            }
        else:
            # Standard fallback analysis
            return {
                "summary": f"Analyzed {len(logs)} log entries. Found {error_count} errors, {warn_count} warnings, and {info_count} info messages.",
                "key_insights": [
                    f"Total log entries: {len(logs)}",
                    f"Error rate: {error_count/len(logs)*100:.1f}%" if logs else "No logs to analyze"
                ],
                "errors": errors[:10],  # Limit to 10 errors
                "function_calls": list(functions)[:20],  # Limit to 20 functions
                "timestamp_flow": timestamp_flow,
                "anomalies": [],
                "focus_areas": ["High error rate needs investigation"] if error_count > len(logs) * 0.1 else [],
                "recommendations": ["Configure an AI provider API key for deeper insights"]
            }
    except Exception as e:
        logger.error(f"Error in fallback analysis: {str(e)}")
        return {
            "summary": f"Basic analysis of {len(logs)} logs completed with limited insights",
            "key_insights": ["Fallback analysis due to processing error"],
            "errors": [],
            "function_calls": [],
            "timestamp_flow": "Not available",
            "anomalies": [],
            "focus_areas": [],
            "recommendations": ["Check system configuration"]
        }

# === Periscope Time Conversion Helpers ===

def convert_time_to_microseconds(time_input: Union[str, int, None], timezone: Optional[str] = None) -> int:
    """
    Convert various time formats to microseconds since epoch.

    Args:
        time_input: Can be:
            - None (returns current time)
            - int (assumed to be microseconds)
            - "2h", "1d", "7d" (relative time from now)
            - ISO 8601 timestamp string (with or without timezone)
            - Naive datetime string like "2025-10-04 10:20:00" (requires timezone param)
        timezone: Optional timezone name (e.g., 'Asia/Kolkata', 'UTC', 'US/Eastern')
                  Used when time_input is a naive datetime string without timezone info.
                  If not provided and time_input is naive, assumes UTC.

    Returns:
        Microseconds since epoch (always in UTC)

    Examples:
        >>> convert_time_to_microseconds("2025-10-04T10:20:00+05:30")  # IST with offset
        >>> convert_time_to_microseconds("2025-10-04T10:20:00", "Asia/Kolkata")  # IST naive
        >>> convert_time_to_microseconds("2025-10-04T04:50:00Z")  # UTC with Z
        >>> convert_time_to_microseconds("2h")  # 2 hours ago
    """
    if time_input is None:
        return int(time.time() * 1000000)

    if isinstance(time_input, int):
        return time_input

    # Handle relative time strings like "2h", "1d", "7d"
    if isinstance(time_input, str):
        import re
        from datetime import datetime
        from zoneinfo import ZoneInfo

        match = re.match(r'^(\d+)([hdwm])$', time_input.lower())
        if match:
            value = int(match.group(1))
            unit = match.group(2)

            now = time.time()
            if unit == 'h':
                seconds_ago = value * 3600
            elif unit == 'd':
                seconds_ago = value * 86400
            elif unit == 'w':
                seconds_ago = value * 604800
            elif unit == 'm':
                seconds_ago = value * 2592000  # 30 days
            else:
                seconds_ago = 0

            return int((now - seconds_ago) * 1000000)

        # Try to parse as ISO 8601 timestamp
        try:
            # Replace 'Z' with '+00:00' for proper timezone handling
            normalized_input = time_input.replace('Z', '+00:00')

            # Try parsing as timezone-aware datetime
            try:
                dt = datetime.fromisoformat(normalized_input)

                # If the datetime is naive (no timezone info), apply the timezone parameter
                if dt.tzinfo is None:
                    if timezone:
                        try:
                            # Apply the specified timezone to the naive datetime
                            tz = ZoneInfo(timezone)
                            dt = dt.replace(tzinfo=tz)
                            logger.debug(f"Applied timezone {timezone} to naive datetime {time_input}")
                        except Exception as e:
                            logger.warning(f"Invalid timezone '{timezone}': {e}. Assuming UTC.")
                            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                    else:
                        # Default to UTC for naive datetimes
                        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                        logger.debug(f"Applied default UTC timezone to naive datetime {time_input}")

                # Convert to microseconds (timestamp() always returns UTC epoch)
                return int(dt.timestamp() * 1000000)

            except ValueError:
                # Try alternative datetime formats
                # Format: "2025-10-04 10:20:00" (space instead of T)
                try:
                    dt = datetime.strptime(time_input, "%Y-%m-%d %H:%M:%S")
                    if timezone:
                        try:
                            tz = ZoneInfo(timezone)
                            dt = dt.replace(tzinfo=tz)
                        except Exception as e:
                            logger.warning(f"Invalid timezone '{timezone}': {e}. Assuming UTC.")
                            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                    else:
                        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                    return int(dt.timestamp() * 1000000)
                except ValueError:
                    pass

                raise

        except Exception as e:
            logger.warning(f"Could not parse time input '{time_input}': {e}")
            return int(time.time() * 1000000)

    return int(time.time() * 1000000)

# === Periscope Helper Functions ===

async def periscope_search(
    sql_query: str,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    size: int = 50,
    org_identifier: str = "default"
) -> Dict:
    """
    Execute a search query through Periscope API.

    Args:
        sql_query: SQL query to execute (will be base64 encoded)
        start_time: Start time in microseconds (defaults to 24h ago)
        end_time: End time in microseconds (defaults to now)
        size: Number of results to return
        org_identifier: Organization identifier

    Returns:
        Dict containing search results
    """
    import base64

    # Get Periscope host from config
    periscope_host = get_config_value('periscope.host', 'periscope.breezesdk.store')

    # Build URL
    url = f"https://{periscope_host}/api/{org_identifier}/_search?type=logs&search_type=ui&use_cache=true"

    # Encode SQL query to base64
    sql_base64 = base64.b64encode(sql_query.encode()).decode()

    # Calculate default time range if not provided (last 24 hours in microseconds)
    if not end_time:
        end_time = int(time.time() * 1000000)
    if not start_time:
        start_time = end_time - (24 * 60 * 60 * 1000000)

    # Build request payload
    payload = {
        "query": {
            "sql": sql_base64,
            "start_time": start_time,
            "end_time": end_time,
            "from": 0,
            "size": size,
            "quick_mode": False,
            "sql_mode": "full"
        },
        "encoding": "base64"
    }

    # Set headers
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": f"https://{periscope_host}"
    }

    # Get auth token
    auth_token = get_periscope_auth_token()
    if not auth_token:
        logger.error("No Periscope authentication token available")
        return {"error": "No Periscope authentication token available"}

    # Set cookies
    cookies = {"auth_tokens": auth_token}

    logger.debug(f"Periscope search request: {json.dumps(payload)}")

    # Execute request with retry logic
    max_retries = 3
    retry_count = 0
    last_error = None

    async with get_http_client() as client:
        while retry_count < max_retries:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    cookies=cookies,
                    timeout=20
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.debug(f"Periscope search response status: 200 OK")
                    return result
                else:
                    error_text = response.text
                    logger.error(f"Periscope search failed: {response.status_code} {error_text}")
                    last_error = f"{response.status_code}: {error_text}"

                    if response.status_code in (401, 403):
                        logger.error("Periscope authentication failed")
                        last_error = "Authentication failed. Check your Periscope auth token."
                        break

            except Exception as e:
                logger.error(f"Error during Periscope search: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                last_error = str(e)

            retry_count += 1
            if retry_count < max_retries:
                logger.warning(f"Retrying Periscope search ({retry_count}/{max_retries})...")
                await asyncio.sleep(1)

    return {
        "error": f"Periscope API request failed after {max_retries} retries.",
        "details": last_error
    }

# === Periscope MCP Tools ===

@mcp.tool()
async def set_periscope_auth_token(auth_token: str, ctx: Context = None) -> Dict:
    """
    Set the Periscope authentication token for the current session.

    Args:
        auth_token: The auth_tokens value from Periscope (base64 encoded JSON)

    Returns:
        Dict with status information
    """
    global PERISCOPE_AUTH_TOKEN

    try:
        if not auth_token or auth_token.strip() == "":
            return {
                "success": False,
                "message": "Authentication token cannot be empty"
            }

        old_token = PERISCOPE_AUTH_TOKEN
        PERISCOPE_AUTH_TOKEN = auth_token

        if old_token:
            logger.info("Periscope authentication token updated")
        else:
            logger.info("Periscope authentication token set")

        return {
            "success": True,
            "message": "Periscope authentication token updated successfully"
        }

    except Exception as e:
        logger.error(f"Error setting Periscope authentication token: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }

@mcp.tool()
async def get_periscope_streams(
    org_identifier: str = "default",
    ctx: Context = None
) -> Dict:
    """
    Get available Periscope log streams.

    Args:
        org_identifier: Organization identifier (default: "default")

    Returns:
        Dict containing available streams
    """
    try:
        periscope_host = get_config_value('periscope.host', 'periscope.breezesdk.store')
        url = f"https://{periscope_host}/api/{org_identifier}/streams?type=logs"

        headers = {
            "accept": "application/json"
        }

        auth_token = get_periscope_auth_token()
        if not auth_token:
            return {
                "success": False,
                "error": "No Periscope authentication token available"
            }

        cookies = {"auth_tokens": auth_token}

        async with get_http_client() as client:
            response = await client.get(url, headers=headers, cookies=cookies)

            if response.status_code == 200:
                streams = response.json()
                return {
                    "success": True,
                    "streams": streams,
                    "total": len(streams) if isinstance(streams, list) else 0,
                    "org_identifier": org_identifier
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get streams: {response.status_code} {response.text}"
                }

    except Exception as e:
        logger.error(f"Error getting Periscope streams: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
async def get_periscope_stream_schema(
    stream_name: str,
    org_identifier: str = "default",
    ctx: Context = None
) -> Dict:
    """
    Get schema for a specific Periscope log stream.

    Args:
        stream_name: Name of the stream (e.g., "envoy_logs", "vayu_logs")
        org_identifier: Organization identifier (default: "default")

    Returns:
        Dict containing stream schema with fields, stats, and settings
    """
    try:
        periscope_host = get_config_value('periscope.host', 'periscope.breezesdk.store')
        url = f"https://{periscope_host}/api/{org_identifier}/streams/{stream_name}/schema?type=logs"

        headers = {
            "accept": "application/json"
        }

        auth_token = get_periscope_auth_token()
        if not auth_token:
            return {
                "success": False,
                "error": "No Periscope authentication token available"
            }

        cookies = {"auth_tokens": auth_token}

        async with get_http_client() as client:
            response = await client.get(url, headers=headers, cookies=cookies)

            if response.status_code == 200:
                schema_data = response.json()
                return {
                    "success": True,
                    "stream_name": stream_name,
                    "schema": schema_data.get("schema", []),
                    "stats": schema_data.get("stats", {}),
                    "settings": schema_data.get("settings", {}),
                    "total_fields": schema_data.get("total_fields", 0)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get schema: {response.status_code} {response.text}"
                }

    except Exception as e:
        logger.error(f"Error getting Periscope stream schema: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
async def get_all_periscope_schemas(
    org_identifier: str = "default",
    ctx: Context = None
) -> Dict:
    """
    Get schemas for all available Periscope log streams.
    This is a convenience tool that lists all streams and fetches their schemas.

    Args:
        org_identifier: Organization identifier (default: "default")

    Returns:
        Dict containing all stream schemas
    """
    try:
        # First, get all streams
        streams_result = await get_periscope_streams(org_identifier, ctx)

        if not streams_result.get("success"):
            return streams_result

        streams = streams_result.get("streams", [])
        if not streams:
            return {
                "success": True,
                "message": "No streams found",
                "schemas": {}
            }

        # Fetch schema for each stream
        schemas = {}
        for stream in streams:
            stream_name = stream.get("name") if isinstance(stream, dict) else stream
            if stream_name:
                schema_result = await get_periscope_stream_schema(stream_name, org_identifier, ctx)
                if schema_result.get("success"):
                    schemas[stream_name] = schema_result

        return {
            "success": True,
            "total_streams": len(schemas),
            "schemas": schemas,
            "org_identifier": org_identifier
        }

    except Exception as e:
        logger.error(f"Error getting all Periscope schemas: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
async def search_periscope_logs(
    sql_query: str,
    start_time: Optional[Union[str, int]] = None,
    end_time: Optional[Union[str, int]] = None,
    max_results: int = 50,
    org_identifier: str = "default",
    timezone: Optional[str] = None,
    ctx: Context = None
) -> Dict:
    """
    Search Periscope logs using SQL queries.

    Args:
        sql_query: SQL query to execute (e.g., 'SELECT * FROM "envoy_logs" WHERE status_code LIKE \'%50%\'')
        start_time: Start time - can be microseconds (int), relative ("2h", "1d"), or ISO timestamp (defaults to 24h ago)
        end_time: End time - can be microseconds (int), relative time, or ISO timestamp (defaults to now)
        max_results: Maximum number of results to return (default: 50)
        org_identifier: Organization identifier (default: "default")
        timezone: Timezone for naive datetime strings (e.g., "Asia/Kolkata", "UTC"). If not provided, assumes UTC.

    Returns:
        Dictionary with search results and metadata

    Examples:
        # Using IST timezone with naive datetime
        search_periscope_logs('SELECT * FROM "envoy_logs"',
                            start_time="2025-10-04 10:20:00",
                            end_time="2025-10-04 11:00:00",
                            timezone="Asia/Kolkata")

        # Using ISO timestamps with timezone offsets (no timezone param needed)
        search_periscope_logs('SELECT * FROM "envoy_logs"',
                            start_time="2025-10-04T10:20:00+05:30",
                            end_time="2025-10-04T11:00:00+05:30")

        # Using relative times
        search_periscope_logs('SELECT * FROM "envoy_logs"', start_time="2h")
    """
    try:
        # Convert time inputs to microseconds with timezone support
        start_time_us = convert_time_to_microseconds(start_time, timezone) if start_time else None
        end_time_us = convert_time_to_microseconds(end_time, timezone) if end_time else None

        result = await periscope_search(
            sql_query=sql_query,
            start_time=start_time_us,
            end_time=end_time_us,
            size=max_results,
            org_identifier=org_identifier
        )

        if "error" in result:
            return {
                "success": False,
                "error": result["error"],
                "logs": []
            }

        # Extract hits from Periscope response
        hits = result.get("hits", [])

        return {
            "success": True,
            "total": len(hits),
            "logs": hits,
            "query": sql_query,
            "org_identifier": org_identifier
        }

    except Exception as e:
        logger.error(f"Error searching Periscope logs: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        return {
            "success": False,
            "error": str(e),
            "logs": []
        }

@mcp.tool()
async def search_periscope_errors(
    hours: int = 24,
    stream: str = "envoy_logs",
    error_codes: Optional[str] = None,
    org_identifier: str = "default",
    ctx: Context = None
) -> Dict:
    """
    Search for error logs in Periscope.

    Args:
        hours: Number of hours to look back (default: 24)
        stream: Stream name to search (default: "envoy_logs")
        error_codes: Error code pattern (default: "4%" for 4xx or "5%" for 5xx, None for >=400)
        org_identifier: Organization identifier (default: "default")

    Returns:
        Dict containing error logs
    """
    try:
        # Calculate time range
        end_time = int(time.time() * 1000000)
        start_time = end_time - (hours * 60 * 60 * 1000000)

        # Build SQL query for errors
        if error_codes:
            sql_query = f'SELECT * FROM "{stream}" WHERE status_code LIKE \'{error_codes}\''
        else:
            sql_query = f'SELECT * FROM "{stream}" WHERE status_code >= 400'

        result = await search_periscope_logs(
            sql_query=sql_query,
            start_time=start_time,
            end_time=end_time,
            max_results=100,
            org_identifier=org_identifier,
            ctx=ctx
        )

        if result.get("success"):
            return {
                "success": True,
                "errors": result.get("logs", []),
                "total": result.get("total", 0),
                "hours": hours,
                "stream": stream
            }
        else:
            return result

    except Exception as e:
        logger.error(f"Error searching Periscope errors: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "errors": []
        }

def _generate_fallback_combined_analysis(analyses: List[Dict], is_function_based: bool = False) -> Dict:
    """
    Generate a combined analysis when Neurolink combination fails.
    
    Args:
        analyses: List of analysis dictionaries
        is_function_based: Whether this is a function-based mode analysis
        
    Returns:
        Combined analysis dictionary
    """
    try:
        combined = {
            "summary": "",
            "key_insights": [],
            "errors": [],
            "function_calls": [],
            "timestamp_flow": "",
            "anomalies": [],
            "focus_areas": [],
            "recommendations": []
        }
        
        # Combine all sections
        summaries = []
        for analysis in analyses:
            if analysis.get('summary'):
                summaries.append(analysis['summary'])
            
            # Combine list sections
            for key in ['key_insights', 'errors', 'function_calls', 'anomalies', 'focus_areas', 'recommendations']:
                if key in analysis and isinstance(analysis[key], list):
                    combined[key].extend(analysis[key])
            
            # For timestamp flow, we'll concatenate with separators
            if analysis.get('timestamp_flow'):
                if combined['timestamp_flow']:
                    combined['timestamp_flow'] += " → " + analysis['timestamp_flow']
                else:
                    combined['timestamp_flow'] = analysis['timestamp_flow']
        
        # Create a comprehensive summary
        if summaries:
            combined['summary'] = " ".join(summaries)
        else:
            combined['summary'] = f"Combined analysis of {len(analyses)} chunks"
        
        # If timestamp flow wasn't populated, set a default
        if not combined['timestamp_flow']:
            combined['timestamp_flow'] = "Combined analysis from multiple chunks"
        
        # Remove duplicates from lists while preserving order
        for key in ['key_insights', 'errors', 'function_calls', 'anomalies', 'focus_areas', 'recommendations']:
            if combined[key]:
                # Use dict.fromkeys to preserve order while removing duplicates
                combined[key] = list(dict.fromkeys(combined[key]))
        
        # Add a special insight for function-based mode
        if is_function_based:
            combined['key_insights'].insert(0, f"Function-based analysis combined from {len(analyses)} chunks")
            
            # Add recommendations specific to function-based mode
            if "Configure an AI provider API key for detailed function flow analysis" not in combined['recommendations']:
                combined['recommendations'].append("Configure an AI provider API key for detailed function flow analysis")
        
        return combined
        
    except Exception as e:
        logger.error(f"Error in fallback combined analysis: {str(e)}")
        return {
            "summary": f"Combined analysis of {len(analyses)} chunks with limited processing",
            "key_insights": ["Fallback combination due to processing error"],
            "errors": [],
            "function_calls": [],
            "timestamp_flow": "Not available",
            "anomalies": [],
            "focus_areas": [],
            "recommendations": ["Check system configuration for AI analysis"]
        }

@mcp.tool()
async def set_auth_token(auth_token: str, ctx: Context = None) -> Dict:
    """
    Set the Kibana authentication token for the current session.
    
    Args:
        auth_token: The authentication token to use for Kibana requests
        
    Returns:
        Dict with status information
    """
    global DYNAMIC_AUTH_TOKEN
    
    try:
        # Validate the token is not empty
        if not auth_token or auth_token.strip() == "":
            return {
                "success": False,
                "message": "Authentication token cannot be empty"
            }
        
        # Set the dynamic auth token
        old_token = DYNAMIC_AUTH_TOKEN
        DYNAMIC_AUTH_TOKEN = auth_token
        
        # Log the token change (masked for security)
        if old_token:
            logger.info("Authentication token updated")
        else:
            logger.info("Authentication token set")
        
        return {
            "success": True,
            "message": "Authentication token updated successfully"
        }
        
    except Exception as e:
        logger.error(f"Error setting authentication token: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }

@mcp.tool()
async def extract_session_id(
    order_id: str,
    ctx: Context = None
) -> Dict:
    """
    Extract session IDs from logs related to a specific order ID by parsing the log message.
    
    This function searches for logs containing the order ID and "callStartPayment",
    then parses the 'message' field of these logs to extract the session ID
    based on the pattern: "{num} | {some_id} | {session_id} | ..."
    The session ID is the third segment after splitting by " | ".
    
    Args:
        order_id: The order ID to search for in logs
        
    Returns:
        Dictionary with extracted session IDs and related information
    """
    try:
        logger.info(f"Extracting session ID for order: {order_id} using direct parsing.")
        
        # Ensure order_id is a string and not empty
        if not order_id or not isinstance(order_id, str):
            logger.warning(f"Invalid order_id provided for session extraction: {order_id}")
            return {
                "success": False,
                "message": "Invalid or missing order_id provided.",
                "session_ids_data": [],
                "order_id": order_id
            }

        query_text = f'{order_id} AND \\"callStartPayment\\"'
        
        # Fetch up to 3 logs to ensure we have enough data to find the pattern
        # The user's last edit set this to 1, but AI rules suggest 1-3 for robustness.
        # Using 3 here.
        search_results_dict = await search_logs(
            query_text=query_text,
            max_results=3, 
            ctx=ctx
        )
        
        if not search_results_dict or not search_results_dict.get("success"):
            error_message = search_results_dict.get('error', 'Unknown error') if search_results_dict else 'No response from search_logs'
            logger.info(f"Failed to fetch logs for order ID: {order_id}. Error: {error_message}")
            return {
                "success": False,
                "message": f"Failed to fetch logs for order ID: {order_id}. Error: {error_message}",
                "session_ids_data": [],
                "order_id": order_id
            }
        
        actual_logs = search_results_dict.get("logs", [])
        if not actual_logs:
            logger.info(f"No log entries found in successful search for order ID: {order_id}")
            return {
                "success": True, # Search itself was successful, but no relevant log entries
                "message": f"No log entries matching the order ID and 'callStartPayment' found for order ID: {order_id}",
                "session_ids_data": [],
                "order_id": order_id
            }

        logger.info(f"Found {len(actual_logs)} log entries for order ID: {order_id} to parse for session ID.")
        
        extracted_sessions_details = []
        for i, log_entry in enumerate(actual_logs):
            session_id_info = {
                "log_index": i,
                "original_log_snippet": "",
                "session_id": None,
                "status": "not_found_in_log" 
            }
            if isinstance(log_entry, dict) and "message" in log_entry and isinstance(log_entry["message"], str):
                message_content = log_entry["message"]
                session_id_info["original_log_snippet"] = message_content[:250] # Store a snippet

                parts = message_content.split(" | ")
                
                if len(parts) >= 3:
                    # The session ID is the third segment (index 2)
                    extracted_id = parts[2].strip()
                    if extracted_id: # Ensure it's not an empty string
                        session_id_info["session_id"] = extracted_id
                        session_id_info["status"] = "extracted"
                        logger.info(f"Log entry {i}: Extracted session ID: {extracted_id} from message: {message_content[:100]}...")
                        # Optional: if we only need one, we can break here
                        # extracted_sessions_details.append(session_id_info)
                        # break 
                    else:
                        session_id_info["status"] = "pattern_match_empty_segment"
                        logger.warning(f"Log entry {i}: Matched segment count, but session ID segment was empty. Message snippet: {message_content[:100]}...")
                else:
                    session_id_info["status"] = "pattern_mismatch_not_enough_segments"
                    logger.warning(f"Log entry {i}: Message did not match expected segment count for session ID. Message snippet: {message_content[:100]}...")
            else:
                session_id_info["status"] = "invalid_log_format_or_missing_message"
                session_id_info["original_log_snippet"] = str(log_entry)[:250]
                logger.warning(f"Log entry {i}: Invalid log entry format or missing 'message' field: {str(log_entry)[:250]}...")
            
            extracted_sessions_details.append(session_id_info)

        successfully_extracted_ids = [s["session_id"] for s in extracted_sessions_details if s["status"] == "extracted" and s["session_id"]]
        
        if successfully_extracted_ids:
            # As per AI rules, if session_id is found, use it.
            # If multiple are found from the logs, we will take the first one.
            final_message = f"Successfully extracted session ID: {successfully_extracted_ids[0]} from {len(actual_logs)} log(s) processed."
            # Return only the first successfully extracted ID for consistency with previous behavior
            # where one session_id was expected.
            return {
                "success": True,
                "message": final_message,
                "session_id": successfully_extracted_ids[0], # Primary extracted ID
                "all_extraction_attempts": extracted_sessions_details, # Detailed attempts for debugging
                "order_id": order_id
            }
        else:
            final_message = f"Processed {len(actual_logs)} log(s) for order ID {order_id}, but no session IDs could be definitively extracted based on the 'X | Y | SESSION_ID | ...' pattern."
            return {
                "success": True, # Function ran, but no ID extracted
                "message": final_message,
                "session_id": None,
                "all_extraction_attempts": extracted_sessions_details,
                "order_id": order_id
            }
                
    except Exception as e:
        logger.error(f"Error in extract_session_id (direct parsing): {str(e)}")
        import traceback
        logger.error(f"Stack trace for extract_session_id: {traceback.format_exc()}")
        return {
            "success": False,
            "message": f"An unexpected error occurred while extracting session ID by direct parsing: {str(e)}",
            "session_id": None,
            "all_extraction_attempts": [],
            "order_id": order_id
        }

@mcp.tool()
async def discover_indexes(ctx: Context = None) -> Dict:
    """
    Discover available Elasticsearch indexes.
    
    Returns a list of available index patterns that can be used for searching logs.
    
    Returns:
        Dict: A dictionary containing the list of available index patterns.
    """
    global CURRENT_INDEX
    
    try:
        # Get the current auth token
        current_auth_token = get_auth_token()
        
        # Check if we have an auth token
        if not current_auth_token:
            return {
                "success": False,
                "error": "No authentication token available. Please set it via API or environment variable."
            }

        # Set cookies
        cookies = {"_pomerium": current_auth_token}
        
        # Set headers
        headers = {
            "kbn-version": kibana_version,
            "Content-Type": "application/json"
        }
        
        # Create a new client for this request
        async with get_http_client() as client:
            # First try using Kibana's index pattern API
            url = f"https://{kibana_host}{kibana_base_path}/api/saved_objects/_find?type=index-pattern"
            
            try:
                response = await client.get(url, headers=headers, cookies=cookies)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if "saved_objects" in result:
                        index_patterns = []
                        
                        for pattern in result["saved_objects"]:
                            if "attributes" in pattern and "title" in pattern["attributes"]:
                                index_patterns.append(pattern["attributes"]["title"])
                        
                        # Get information about current index
                        current_index_info = CURRENT_INDEX or es_config.get("index_prefix", None)
                        current_message = f"Current index: {current_index_info}" if current_index_info else "No index currently selected."
                        
                        return {
                            "success": True,
                            "message": f"Found {len(index_patterns)} index patterns. {current_message}",
                            "index_patterns": index_patterns,
                            "current_index": current_index_info
                        }
                    else:
                        logger.warning(f"No index patterns found in Kibana")
                else:
                    logger.warning(f"Failed to get index patterns: {response.status_code}")
            except Exception as e:
                logger.warning(f"Exception getting index patterns: {e}")
            
            # Fallback: Try to get indices directly from Elasticsearch
            try:
                # Try to access ES cat indices
                url = f"https://{kibana_host}/_plugin/kibana/internal/search/es"
                
                # Format for the data API
                payload = {
                    "params": {
                        "index": "_cat/indices",
                        "body": {
                            "format": "json"
                        }
                    }
                }
                
                response = await client.post(url, json=payload, headers=headers, cookies=cookies)
                
                if response.status_code == 200:
                    result = response.json()
                    if "rawResponse" in result:
                        indices = result["rawResponse"]
                        
                        if isinstance(indices, list):
                            index_names = [index.get("index") for index in indices if "index" in index]
                            
                            # Extract unique prefixes by removing timestamp patterns
                            index_prefixes = set()
                            for name in index_names:
                                # Extract the prefix (everything before the date pattern)
                                parts = name.split('-')
                                if len(parts) > 1:
                                    try:
                                        # Check if the last part contains a date
                                        if parts[-1].isdigit() and len(parts[-1]) == 8:  # YYYYMMDD
                                            prefix = '-'.join(parts[:-1])
                                            index_prefixes.add(prefix)
                                        else:
                                            index_prefixes.add(name)
                                    except:
                                        index_prefixes.add(name)
                                else:
                                    index_prefixes.add(name)
                            
                            # Convert to list and add wildcard
                            index_patterns = [f"{prefix}-*" for prefix in index_prefixes]
                            
                            # Get information about current index
                            current_index_info = CURRENT_INDEX or es_config.get("index_prefix", None)
                            current_message = f"Current index: {current_index_info}" if current_index_info else "No index currently selected."
                            
                            return {
                                "success": True,
                                "message": f"Found {len(index_patterns)} index patterns through direct ES query. {current_message}",
                                "index_patterns": index_patterns,
                                "current_index": current_index_info
                            }
                
                logger.warning(f"Failed to get indices directly: {response.status_code}")
            except Exception as e:
                logger.warning(f"Exception getting indices directly: {e}")
        
        # If we get here, we failed to get indices through any method
        return {
            "success": False,
            "error": "Failed to retrieve index patterns from Kibana or Elasticsearch."
        }
        
    except Exception as e:
        logger.error(f"Error discovering indexes: {e}")
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return {
            "success": False,
            "error": f"Error discovering indexes: {str(e)}"
        }

@mcp.tool()
async def set_current_index(index_pattern: str, ctx: Context = None) -> Dict:
    """
    Set the current index pattern to use for log searches.
    
    Args:
        index_pattern (str): The index pattern to use for searching logs.
        
    Returns:
        Dict: A dictionary indicating success or failure.
    """
    global CURRENT_INDEX
    
    try:
        # Validate that the index pattern is not empty
        if not index_pattern or not isinstance(index_pattern, str):
            return {
                "success": False,
                "error": "Invalid index pattern provided."
            }
        
        # Store the new index pattern
        CURRENT_INDEX = index_pattern
        
        logger.info(f"Current index pattern set to: {CURRENT_INDEX}")
        
        return {
            "success": True,
            "message": f"Current index pattern set to: {CURRENT_INDEX}"
        }
        
    except Exception as e:
        logger.error(f"Error setting current index: {e}")
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return {
            "success": False,
            "error": f"Error setting current index: {str(e)}"
        }

@mcp.tool()
async def set_config(configs_to_set: Dict[str, Any], ctx: Context = None) -> Dict:
    """
    Set one or more configuration values dynamically.
    
    Args:
        configs_to_set: A dictionary where keys are dot-notation paths
                        to the config keys (e.g., 'elasticsearch.host')
                        and values are the values to set. Values will be
                        auto-converted to boolean, int, or float if they
                        match common patterns (e.g., "true", "false", "123", "12.34").
                        Otherwise, they are treated as strings.
    
    Returns:
        Dict containing overall success status and a list of messages for each config.
    """
    global DYNAMIC_CONFIG_OVERRIDES, CONFIG
    results = []
    all_successful = True

    for key_path, value in configs_to_set.items():
        try:
            converted_value = value 

            if isinstance(value, str):
                if value.lower() == "true":
                    converted_value = True
                elif value.lower() == "false":
                    converted_value = False
                elif value.isdigit():
                    converted_value = int(value)
                elif value.replace(".", "", 1).isdigit() and value.count(".") == 1:
                    converted_value = float(value)
            
            DYNAMIC_CONFIG_OVERRIDES[key_path] = converted_value
            
            keys = key_path.split('.')
            current_config_level = CONFIG
            for i, key_part in enumerate(keys[:-1]):
                if key_part not in current_config_level or not isinstance(current_config_level[key_part], dict):
                    current_config_level[key_part] = {} 
                current_config_level = current_config_level[key_part]
            
            current_config_level[keys[-1]] = converted_value
            
            message = f"Successfully set: {key_path} = {converted_value} (type: {type(converted_value).__name__})"
            logger.info(message)
            results.append({"key_path": key_path, "status": "success", "message": message})

        except Exception as e:
            error_message = f"Error setting {key_path} to {value}: {str(e)}"
            logger.error(error_message)
            results.append({"key_path": key_path, "status": "error", "message": error_message, "trace": traceback.format_exc()})
            all_successful = False
            
    return {
        "overall_success": all_successful,
        "details": results
    }

@mcp.tool()
async def get_ai_rules(ctx: Context = None) -> Dict:
    """
    Get the AI rules file content.
    
    IMPORTANT: Reading these rules must be the first and foremost step before using this API.
    
    Returns:
        Dict containing success status and the rules content
    """
    try:
        # Get directory of the current script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        rules_path = os.path.join(script_dir, "AI_rules_file.txt")
        
        if os.path.exists(rules_path):
            with open(rules_path, 'r') as file:
                rules_content = file.read()
            
            return {
                "success": True,
                "message": "AI rules retrieved successfully. IMPORTANT: Review these rules carefully before using the API.",
                "rules": rules_content
            }
        else:
            return {
                "success": False,
                "message": "AI rules file not found",
                "rules": "File not found: AI_rules_file.txt"
            }
    except Exception as e:
        logger.error(f"Error retrieving AI rules: {e}")
        return {
            "success": False,
            "message": f"Error retrieving AI rules: {str(e)}",
            "rules": None
        }

# Modified get_config function to check dynamic overrides first
def get_config_value(key_path, default=None, expected_type=None):
    """
    Get a configuration value, checking dynamic overrides first.
    
    Args:
        key_path: Dot-notation path to the config key
        default: Default value if key doesn't exist
        expected_type: Optional type to convert the value to
    
    Returns:
        The config value with proper type conversion
    """
    global DYNAMIC_CONFIG_OVERRIDES, CONFIG
    
    # Check if we have a dynamic override
    if key_path in DYNAMIC_CONFIG_OVERRIDES:
        value = DYNAMIC_CONFIG_OVERRIDES[key_path]
        # Convert to expected type if specified
        if expected_type is not None and not isinstance(value, expected_type):
            try:
                return expected_type(value)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert '{key_path}' value to {expected_type.__name__}")
                return value
        return value
    
    # Otherwise get from the config
    keys = key_path.split('.')
    current = CONFIG
    try:
        for key in keys:
            current = current[key]
        
        # Convert to expected type if specified
        if expected_type is not None and not isinstance(current, expected_type):
            try:
                return expected_type(current)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert '{key_path}' value to {expected_type.__name__}")
        
        return current
    except (KeyError, TypeError):
        return default

# Add the HTTP endpoints
def setup_http_transport(app):
    # ... existing code ...

    @app.post("/api/set_config")
    async def api_set_config(request_data: dict):
        """Set one or more configuration values dynamically."""
        # Pass the entire request_data dictionary to the set_config tool
        result = await set_config(request_data)
        return result
    
    @app.get("/api/get_ai_rules")
    async def api_get_ai_rules():
        """
        Get the AI rules file content.
        
        IMPORTANT: Reading these rules must be the first and foremost step before using this API.
        """
        return await get_ai_rules()
    
    # ... existing code ...

# Start the server if run directly
if __name__ == "__main__":
    # Get auth cookie from environment variable - no longer strictly required
    auth_cookie = os.environ.get('KIBANA_AUTH_COOKIE')
    if not auth_cookie:
        logger.warning("No authentication cookie provided in environment. You can set it via API or config.")
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='Kibana Log MCP Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    parser.add_argument('--transport', choices=['http', 'stdio'], default='http', 
                      help='Transport to use for MCP')
    args = parser.parse_args()
    
    # Initialize and run MCP server
    transport = args.transport
    host = args.host
    port = args.port
    
    logger.info(f"Starting Kibana Log MCP Server on {host}:{port} using {transport} transport")
    
    if transport == 'http':
        # For HTTP transport, add routes to the FastAPI app
        @app.get("/")
        async def root(request: Request, format: Optional[str] = None):
            # If format=sse or accept header is text/event-stream, use SSE
            accept_header = request.headers.get("accept", "")
            if format == "sse" or "text/event-stream" in accept_header:
                # Use the existing SSE implementation
                return await stream_logs_sse(request)
            
            # Otherwise return regular JSON response
            return {"message": "Kibana MCP Server", "version": CONFIG["mcp_server"]["version"]}
        
        # Add support for Server-Sent Events (SSE) endpoint for Cursor MCP integration
        @app.get("/sse")
        async def sse_endpoint(request: Request):
            """Serve SSE requests from Cursor for MCP integration."""
            logger.info("SSE connection established for MCP")
            return await mcp.handle_sse(request)
        
        # Add MCP endpoints required by Smithery with lazy loading support
        @app.get("/mcp")
        async def mcp_get(request: Request):
            # Implement lazy loading for tool listing - don't check authentication here
            try:
                # Get request ID from query parameters
                request_id = request.query_params.get("id", "1")
                
                # Get the JSON-RPC method from query parameters
                method = request.query_params.get("method", "")
                
                # Only handle list_tools method
                if method == "list_tools":
                    # Define tool schemas manually without authentication
                    tools = [
                        {
                            "name": "health",
                            "description": "Health check endpoint for container monitoring.",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        },
                        {
                            "name": "set_auth_token",
                            "description": "Set the Kibana authentication token for the current session.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "auth_token": {
                                        "type": "string",
                                        "description": "The authentication token to use for Kibana requests"
                                    }
                                },
                                "required": ["auth_token"]
                            }
                        },
                        {
                            "name": "search_logs",
                            "description": "Search Kibana logs with flexible criteria.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query_text": {
                                        "type": "string",
                                        "description": "Text to search for in log messages"
                                    },
                                    "start_time": {
                                        "type": "string",
                                        "description": "Start time for logs (ISO format or relative like '1h')"
                                    },
                                    "end_time": {
                                        "type": "string",
                                        "description": "End time for logs (ISO format)"
                                    },
                                    "levels": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of log levels to include (e.g., [\"error\", \"warn\"])"
                                    },
                                    "include_fields": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Fields to include in results"
                                    },
                                    "exclude_fields": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Fields to exclude from results"
                                    },
                                    "max_results": {
                                        "type": "integer",
                                        "description": "Maximum number of results to return"
                                    },
                                    "sort_by": {
                                        "type": "string",
                                        "description": "Field to sort results by"
                                    },
                                    "sort_order": {
                                        "type": "string",
                                        "description": "Order to sort results (\"asc\" or \"desc\")"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "get_recent_logs",
                            "description": "Retrieve the most recent Kibana logs.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "count": {
                                        "type": "integer",
                                        "description": "Number of logs to retrieve"
                                    },
                                    "level": {
                                        "type": "string",
                                        "description": "Filter by log level (e.g., \"info\", \"error\", \"warn\")"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "analyze_logs",
                            "description": "Analyze logs to identify patterns and provide statistics.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "time_range": {
                                        "type": "string",
                                        "description": "Time range to analyze (e.g. \"1h\", \"1d\", \"7d\")"
                                    },
                                    "group_by": {
                                        "type": "string",
                                        "description": "Field to group results by (e.g. \"level\", \"service\", \"status\")"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "extract_errors",
                            "description": "Extract error logs with optional stack traces.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "hours": {
                                        "type": "integer",
                                        "description": "Number of hours to look back"
                                    },
                                    "include_stack_traces": {
                                        "type": "boolean",
                                        "description": "Whether to include stack traces in results"
                                    },
                                    "limit": {
                                        "type": "integer",
                                        "description": "Maximum number of errors to return"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "correlate_with_code",
                            "description": "Correlate error logs with code locations.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "error_message": {
                                        "type": "string",
                                        "description": "Error message to search for"
                                    },
                                    "repo_path": {
                                        "type": "string",
                                        "description": "Path to the code repository (optional)"
                                    }
                                },
                                "required": ["error_message"]
                            }
                        },
                        {
                            "name": "stream_logs_realtime",
                            "description": "Stream logs in real-time for monitoring.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "duration_seconds": {
                                        "type": "integer",
                                        "description": "Duration to stream logs for"
                                    },
                                    "filter_expression": {
                                        "type": "string",
                                        "description": "Expression to filter logs (e.g. \"level:error\")"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "extract_session_id",
                            "description": "Extract session IDs from logs related to a specific order ID.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "The order ID to search for in logs"
                                    }
                                },
                                "required": ["order_id"]
                            }
                        },
                        {
                            "name": "discover_indexes",
                            "description": "Discover available Elasticsearch indexes for searching logs",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        },
                        {
                            "name": "set_current_index",
                            "description": "Set the current index pattern to use for log searches",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "index_pattern": {
                                        "type": "string",
                                        "description": "The index pattern to use for searching logs"
                                    }
                                },
                                "required": ["index_pattern"]
                            }
                        },
                        {
                            "name": "set_periscope_auth_token",
                            "description": "Set the Periscope authentication token for the current session",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "auth_token": {
                                        "type": "string",
                                        "description": "The auth_tokens value from Periscope (base64 encoded JSON)"
                                    }
                                },
                                "required": ["auth_token"]
                            }
                        },
                        {
                            "name": "get_periscope_streams",
                            "description": "Get available Periscope log streams",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "org_identifier": {
                                        "type": "string",
                                        "description": "Organization identifier (default: 'default')"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "get_periscope_stream_schema",
                            "description": "Get schema for a specific Periscope log stream",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "stream_name": {
                                        "type": "string",
                                        "description": "Name of the stream (e.g., 'envoy_logs', 'vayu_logs')"
                                    },
                                    "org_identifier": {
                                        "type": "string",
                                        "description": "Organization identifier (default: 'default')"
                                    }
                                },
                                "required": ["stream_name"]
                            }
                        },
                        {
                            "name": "get_all_periscope_schemas",
                            "description": "Get schemas for all available Periscope log streams",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "org_identifier": {
                                        "type": "string",
                                        "description": "Organization identifier (default: 'default')"
                                    }
                                },
                                "required": []
                            }
                        },
                        {
                            "name": "search_periscope_logs",
                            "description": "Search Periscope logs using SQL queries",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "sql_query": {
                                        "type": "string",
                                        "description": "SQL query to execute (e.g., 'SELECT * FROM \"envoy_logs\" WHERE status_code LIKE ''%50%''')"
                                    },
                                    "start_time": {
                                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                                        "description": "Start time - can be microseconds (int), relative ('2h', '1d'), or ISO timestamp"
                                    },
                                    "end_time": {
                                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                                        "description": "End time - can be microseconds (int), relative time, or ISO timestamp"
                                    },
                                    "max_results": {
                                        "type": "integer",
                                        "description": "Maximum number of results to return (default: 50)"
                                    },
                                    "org_identifier": {
                                        "type": "string",
                                        "description": "Organization identifier (default: 'default')"
                                    }
                                },
                                "required": ["sql_query"]
                            }
                        },
                        {
                            "name": "search_periscope_errors",
                            "description": "Search for error logs in Periscope",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "hours": {
                                        "type": "integer",
                                        "description": "Number of hours to look back (default: 24)"
                                    },
                                    "stream": {
                                        "type": "string",
                                        "description": "Stream name to search (default: 'envoy_logs')"
                                    },
                                    "error_codes": {
                                        "type": "string",
                                        "description": "Error code pattern (e.g., '4%' for 4xx or '5%' for 5xx)"
                                    },
                                    "org_identifier": {
                                        "type": "string",
                                        "description": "Organization identifier (default: 'default')"
                                    }
                                },
                                "required": []
                            }
                        }
                    ]
                    
                    # Return JSON-RPC response
                    return {
                        "jsonrpc": "2.0",
                        "result": tools,
                        "id": request_id
                    }
                else:
                    # For other methods, return error
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32601,
                            "message": f"Method '{method}' not found or not supported via GET"
                        },
                        "id": request_id
                    }
            except Exception as e:
                logger.error(f"Error handling MCP GET request: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Return JSON-RPC error
                return {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    },
                    "id": request.query_params.get("id", "1")
                }
            
        @app.post("/mcp")
        async def mcp_post(request: Request):
            # Handle MCP POST requests (tool invocation)
            try:
                # Parse request body
                body = await request.json()
                
                # Get request ID and method
                request_id = body.get("id", "1")
                method = body.get("method", "")
                params = body.get("params", {})
                
                # Log the request
                logger.debug(f"MCP POST request: {method} with params {params}")
                
                # Special handling for health check
                if method == "health":
                    # Return health status directly
                    return {
                        "jsonrpc": "2.0",
                        "result": {"status": "ok", "version": CONFIG["mcp_server"]["version"]},
                        "id": request_id
                    }
                # Special handling for set_auth_token
                elif method == "set_auth_token":
                    # Set auth token
                    auth_token = params.get("auth_token", "")
                    if not auth_token:
                        return {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32602,
                                "message": "Invalid params: auth_token is required"
                            },
                            "id": request_id
                        }
                    
                    # Call the set_auth_token function
                    result = await set_auth_token(auth_token)
                    
                    # Return result
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                # Handle other tool calls
                elif method == "get_recent_logs":
                    result = await get_recent_logs(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "search_logs":
                    result = await search_logs(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "analyze_logs":
                    result = await analyze_logs(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "extract_errors":
                    result = await extract_errors(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }

                elif method == "extract_session_id":
                    result = await extract_session_id(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "discover_indexes":
                    result = await discover_indexes(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "set_current_index":
                    result = await set_current_index(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "set_periscope_auth_token":
                    result = await set_periscope_auth_token(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "get_periscope_streams":
                    result = await get_periscope_streams(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "get_periscope_stream_schema":
                    result = await get_periscope_stream_schema(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "get_all_periscope_schemas":
                    result = await get_all_periscope_schemas(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "search_periscope_logs":
                    result = await search_periscope_logs(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                elif method == "search_periscope_errors":
                    result = await search_periscope_errors(**params)
                    return {
                        "jsonrpc": "2.0",
                        "result": result,
                        "id": request_id
                    }
                else:
                    # Method not found
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32601,
                            "message": f"Method '{method}' not found"
                        },
                        "id": request_id
                    }
            except Exception as e:
                logger.error(f"Error handling MCP POST request: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Return JSON-RPC error
                return {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    },
                    "id": body.get("id", "1") if isinstance(body, dict) else "1"
                }
            
        @app.delete("/mcp")
        async def mcp_delete(request: Request):
            # Handle MCP DELETE requests (session cleanup)
            return await mcp.handle_http_transport(request)
        
        # Add new endpoint for setting auth token via HTTP
        @app.post("/api/set_auth_token")
        async def api_set_auth_token(request_data: dict):
            if "auth_token" not in request_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="auth_token is required in the request body"
                )
            
            auth_token = request_data["auth_token"]
            
            # Set the token
            global DYNAMIC_AUTH_TOKEN
            old_token = DYNAMIC_AUTH_TOKEN
            DYNAMIC_AUTH_TOKEN = auth_token
            
            # Log the token change (masked for security)
            if old_token:
                logger.info("Authentication token updated via API")
            else:
                logger.info("Authentication token set via API")
            
            return {
                "success": True,
                "message": "Authentication token updated successfully"
            }
        
        # Register MCP tools as FastAPI endpoints
        @app.post("/api/search_logs")
        async def api_search_logs(request_data: dict):
            return await search_logs(**request_data)
            
        @app.post("/api/get_recent_logs")
        async def api_get_recent_logs(request_data: dict):
            return await get_recent_logs(**request_data)
            
        @app.post("/api/analyze_logs")
        async def api_analyze_logs(request_data: dict):
            return await analyze_logs(**request_data)
            
        @app.post("/api/extract_errors")
        async def api_extract_errors(request_data: dict):
            return await extract_errors(**request_data)
            

            

            
        @app.post("/api/summarize_logs")
        async def api_summarize_logs(request_data: dict):
            return await summarize_logs(**request_data)
            
        @app.get("/tools")
        async def api_tools():
            return {
                "tools": [
                    {
                        "name": "set_auth_token",
                        "description": "Set the Kibana authentication token for the current session"
                    },
                    {
                        "name": "search_logs",
                        "description": "Search Kibana logs with flexible criteria"
                    },
                    {
                        "name": "get_recent_logs",
                        "description": "Retrieve the most recent Kibana logs"
                    },
                    {
                        "name": "analyze_logs",
                        "description": "Analyze logs to identify patterns and provide statistics"
                    },
                    {
                        "name": "extract_errors",
                        "description": "Extract error logs with optional stack traces"
                    },

                    {
                        "name": "summarize_logs",
                        "description": "Search logs and generate AI-powered analysis using Neurolink"
                    },
                    {
                        "name": "discover_indexes",
                        "description": "Discover available Elasticsearch indexes for searching logs"
                    },
                    {
                        "name": "set_current_index",
                        "description": "Set the current index pattern to use for log searches"
                    },
                    {
                        "name": "set_periscope_auth_token",
                        "description": "Set the Periscope authentication token for the current session"
                    },
                    {
                        "name": "get_periscope_streams",
                        "description": "Get available Periscope log streams"
                    },
                    {
                        "name": "get_periscope_stream_schema",
                        "description": "Get schema for a specific Periscope log stream"
                    },
                    {
                        "name": "get_all_periscope_schemas",
                        "description": "Get schemas for all available Periscope log streams"
                    },
                    {
                        "name": "search_periscope_logs",
                        "description": "Search Periscope logs using SQL queries"
                    },
                    {
                        "name": "search_periscope_errors",
                        "description": "Search for error logs in Periscope"
                    }
                ]
            }
        

        
        @app.post("/api/extract_session_id")
        async def api_extract_session_id(request_data: dict):
            order_id = request_data.get("order_id")
            if not order_id:
                return {"success": False, "message": "Order ID is required"}
            return await extract_session_id(order_id=order_id)
        
        @app.get("/api/discover_indexes")
        async def api_discover_indexes():
            """Discover available Elasticsearch indexes."""
            result = await discover_indexes()
            return JSONResponse(content=result)
            
        @app.post("/api/set_current_index")
        async def api_set_current_index(request_data: dict):
            """Set the current index pattern to use."""
            index_pattern = request_data.get("index_pattern")
            if not index_pattern:
                return {"success": False, "message": "Index pattern is required"}
            return await set_current_index(index_pattern=index_pattern)

        # Periscope HTTP API endpoints
        @app.post("/api/set_periscope_auth_token")
        async def api_set_periscope_auth_token(request_data: dict):
            """Set the Periscope authentication token."""
            auth_token = request_data.get("auth_token")
            if not auth_token:
                return {"success": False, "message": "Auth token is required"}
            return await set_periscope_auth_token(auth_token=auth_token)

        @app.get("/api/get_periscope_streams")
        async def api_get_periscope_streams(org_identifier: str = "default"):
            """Get available Periscope streams."""
            return await get_periscope_streams(org_identifier=org_identifier)

        @app.post("/api/get_periscope_stream_schema")
        async def api_get_periscope_stream_schema(request_data: dict):
            """Get schema for a specific Periscope stream."""
            stream_name = request_data.get("stream_name")
            if not stream_name:
                return {"success": False, "message": "Stream name is required"}
            org_identifier = request_data.get("org_identifier", "default")
            return await get_periscope_stream_schema(stream_name=stream_name, org_identifier=org_identifier)

        @app.get("/api/get_all_periscope_schemas")
        async def api_get_all_periscope_schemas(org_identifier: str = "default"):
            """Get all Periscope schemas."""
            return await get_all_periscope_schemas(org_identifier=org_identifier)

        @app.post("/api/search_periscope_logs")
        async def api_search_periscope_logs(request_data: dict):
            """Search Periscope logs using SQL."""
            return await search_periscope_logs(**request_data)

        @app.post("/api/search_periscope_errors")
        async def api_search_periscope_errors(request_data: dict):
            """Search for errors in Periscope."""
            return await search_periscope_errors(**request_data)

        # Start the FastAPI app
        uvicorn.run(app, host=host, port=port)
    else:
        mcp.run(transport=transport) 