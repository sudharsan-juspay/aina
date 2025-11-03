"""
Log Service Module

Business logic for log searching, filtering, and analysis.
"""

from typing import Dict, List, Optional, Any
from loguru import logger

from src.clients.kibana_client import kibana_client
from src.clients.periscope_client import periscope_client
from src.core.config import config
from src.core.exceptions import ValidationError
from src.security.validators import QueryValidator


class LogService:
    """
    Service for log operations.

    Provides high-level log search, filtering, and analysis functionality
    built on top of Kibana and Periscope clients.

    Example:
        >>> log_service = LogService()
        >>> result = await log_service.search_logs(
        ...     query_text='{session_id} AND error',
        ...     max_results=100
        ... )
    """

    def __init__(self):
        """Initialize log service."""
        pass

    async def search_logs(
        self,
        query_text: str,
        max_results: int = 100,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        levels: Optional[List[str]] = None,
        include_fields: Optional[List[str]] = None,
        exclude_fields: Optional[List[str]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        index_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search logs using KQL query.

        Args:
            query_text: KQL query (validated)
            max_results: Maximum results
            start_time: Start time filter
            end_time: End time filter
            levels: Log levels to filter
            include_fields: Fields to include
            exclude_fields: Fields to exclude
            sort_by: Field to sort by
            sort_order: Sort direction (asc/desc)
            index_pattern: Index to search

        Returns:
            Search results with logs and metadata

        Example:
            >>> result = await log_service.search_logs(
            ...     query_text='abc123 AND payment',
            ...     max_results=50,
            ...     levels=['ERROR', 'WARN']
            ... )
        """
        # Build Elasticsearch query from KQL
        query_dsl = self._build_query_dsl(
            kql_query=query_text,
            start_time=start_time,
            end_time=end_time,
            levels=levels
        )

        # Build sort configuration
        sort_config = None
        if sort_by:
            # Validate field name
            QueryValidator.validate_field_name(sort_by)
            sort_config = [{sort_by: {"order": sort_order}}]

        # Execute search
        result = await kibana_client.search(
            index_pattern=index_pattern,
            query=query_dsl,
            size=max_results,
            sort=sort_config,
            include_fields=include_fields,
            exclude_fields=exclude_fields
        )

        # Process and return results
        return self._process_search_results(result, query_text)

    async def get_recent_logs(
        self,
        count: int = 100,
        level: Optional[str] = None,
        index_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get recent logs.

        Args:
            count: Number of logs to retrieve
            level: Filter by log level
            index_pattern: Index to search

        Returns:
            Recent logs

        Example:
            >>> result = await log_service.get_recent_logs(
            ...     count=50,
            ...     level='ERROR'
            ... )
        """
        # Build query
        if level:
            query_dsl = {"match": {"level": level.upper()}}
        else:
            query_dsl = {"match_all": {}}

        # Get timestamp field
        timestamp_field = config.get(
            'elasticsearch.timestamp_field',
            default='@timestamp'
        )

        # Sort by timestamp descending
        sort_config = [{timestamp_field: {"order": "desc"}}]

        # Execute search
        result = await kibana_client.search(
            index_pattern=index_pattern,
            query=query_dsl,
            size=count,
            sort=sort_config
        )

        return self._process_search_results(result, "recent logs")

    async def analyze_logs(
        self,
        time_range: str = "24h",
        group_by: Optional[str] = None,
        index_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze logs for patterns.

        Args:
            time_range: Time range for analysis
            group_by: Field to group by
            index_pattern: Index to analyze

        Returns:
            Analysis results with aggregations

        Example:
            >>> result = await log_service.analyze_logs(
            ...     time_range='24h',
            ...     group_by='level'
            ... )
        """
        # Build time-based query
        query_dsl = self._build_time_range_query(time_range)

        # Build aggregations
        aggs = {}
        if group_by:
            QueryValidator.validate_field_name(group_by)
            aggs[f"by_{group_by}"] = {
                "terms": {
                    "field": f"{group_by}.keyword",
                    "size": 100
                }
            }

        # Always include timestamp histogram
        timestamp_field = config.get(
            'elasticsearch.timestamp_field',
            default='@timestamp'
        )
        aggs["over_time"] = {
            "date_histogram": {
                "field": timestamp_field,
                "fixed_interval": self._get_interval_for_range(time_range)
            }
        }

        # Execute search
        result = await kibana_client.search(
            index_pattern=index_pattern,
            query=query_dsl,
            size=0,  # We only want aggregations
            aggs=aggs
        )

        return {
            "success": True,
            "time_range": time_range,
            "total_logs": result.get('hits', {}).get('total', {}).get('value', 0),
            "aggregations": result.get('aggregations', {}),
            "message": "Log analysis completed"
        }

    async def extract_errors(
        self,
        hours: int = 24,
        include_stack_traces: bool = True,
        limit: int = 100,
        index_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract error logs.

        Args:
            hours: Hours to look back
            include_stack_traces: Include stack traces
            limit: Maximum errors to return
            index_pattern: Index to search

        Returns:
            Error logs

        Example:
            >>> errors = await log_service.extract_errors(
            ...     hours=24,
            ...     limit=50
            ... )
        """
        # Build error query
        query_dsl = {
            "bool": {
                "must": [
                    {"match": {"level": "ERROR"}},
                    {
                        "range": {
                            config.get('elasticsearch.timestamp_field', default='@timestamp'): {
                                "gte": f"now-{hours}h",
                                "lte": "now"
                            }
                        }
                    }
                ]
            }
        }

        # Set fields to include
        include_fields = ["@timestamp", "level", "message", "service"]
        if include_stack_traces:
            include_fields.extend(["stack_trace", "exception", "error"])

        # Execute search
        result = await kibana_client.search(
            index_pattern=index_pattern,
            query=query_dsl,
            size=limit,
            include_fields=include_fields
        )

        errors = []
        for hit in result.get('hits', {}).get('hits', []):
            source = hit.get('_source', {})
            errors.append({
                "timestamp": source.get('@timestamp'),
                "level": source.get('level'),
                "message": source.get('message'),
                "stack_trace": source.get('stack_trace') if include_stack_traces else None,
                "service": source.get('service'),
                "source": source
            })

        return {
            "success": True,
            "time_range": f"{hours}h",
            "total_errors": len(errors),
            "errors": errors,
            "message": f"Found {len(errors)} errors in last {hours} hours"
        }

    def _build_query_dsl(
        self,
        kql_query: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        levels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Build Elasticsearch query DSL from KQL and filters."""
        # Base query with KQL
        query_parts = []

        # Add KQL query
        if kql_query:
            query_parts.append({
                "query_string": {
                    "query": kql_query,
                    "default_field": "*"
                }
            })

        # Add time range filter
        if start_time or end_time:
            timestamp_field = config.get(
                'elasticsearch.timestamp_field',
                default='@timestamp'
            )
            range_query: Dict[str, Any] = {}
            if start_time:
                range_query["gte"] = start_time
            if end_time:
                range_query["lte"] = end_time

            query_parts.append({
                "range": {
                    timestamp_field: range_query
                }
            })

        # Add level filter
        if levels:
            query_parts.append({
                "terms": {
                    "level.keyword": levels
                }
            })

        # Combine queries
        if len(query_parts) == 0:
            return {"match_all": {}}
        elif len(query_parts) == 1:
            return query_parts[0]
        else:
            return {"bool": {"must": query_parts}}

    def _build_time_range_query(self, time_range: str) -> Dict[str, Any]:
        """Build time range query."""
        timestamp_field = config.get(
            'elasticsearch.timestamp_field',
            default='@timestamp'
        )

        return {
            "range": {
                timestamp_field: {
                    "gte": f"now-{time_range}",
                    "lte": "now"
                }
            }
        }

    def _get_interval_for_range(self, time_range: str) -> str:
        """Get appropriate histogram interval for time range."""
        # Extract number and unit
        import re
        match = re.match(r'(\d+)([hdwm])', time_range)
        if not match:
            return "1h"

        amount = int(match.group(1))
        unit = match.group(2)

        # Determine appropriate interval
        if unit == 'h':
            return "15m" if amount <= 24 else "1h"
        elif unit == 'd':
            return "1h" if amount <= 7 else "1d"
        else:
            return "1d"

    def _process_search_results(
        self,
        result: Dict[str, Any],
        query_context: str
    ) -> Dict[str, Any]:
        """Process and normalize search results."""
        hits = result.get('hits', {})
        total = hits.get('total', {})

        # Handle different total formats
        if isinstance(total, dict):
            total_value = total.get('value', 0)
        else:
            total_value = total

        logs = []
        for hit in hits.get('hits', []):
            logs.append({
                "timestamp": hit.get('_source', {}).get('@timestamp'),
                "level": hit.get('_source', {}).get('level'),
                "message": hit.get('_source', {}).get('message'),
                "source": hit.get('_source', {})
            })

        return {
            "success": True,
            "total_hits": total_value,
            "logs": logs,
            "took": result.get('took', 0),
            "timed_out": result.get('timed_out', False),
            "message": f"Found {total_value} logs for query: {query_context}"
        }


# Global singleton instance
log_service = LogService()
