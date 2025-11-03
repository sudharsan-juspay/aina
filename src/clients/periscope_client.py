"""
Periscope Client Module

Client for interacting with Periscope log analysis API.
"""

import time
from typing import Dict, List, Optional, Any
from loguru import logger
import re
from datetime import datetime, timedelta
import pytz

from src.core.config import config
from src.core.exceptions import PeriscopeAPIError, AuthenticationError
from src.core.constants import (
    HEADER_CONTENT_TYPE,
    CONTENT_TYPE_JSON,
    DEFAULT_PERISCOPE_ORG,
)
from src.security.auth import auth_manager, AUTH_CONTEXT_PERISCOPE
from src.security.sanitizers import sanitize_stream_name, sanitize_error_code_pattern
from .http_manager import http_manager
from .retry_manager import default_retry_manager
from src.utils.cache import cache_search, cache_schema
from src.observability.tracing import get_tracer

tracer = get_tracer(__name__)


class PeriscopeClient:
    """
    Client for Periscope API operations.

    Handles SQL-based log queries, stream discovery, and schema inspection.

    Example:
        >>> periscope = PeriscopeClient()
        >>> result = await periscope.search(
        ...     sql_query='SELECT * FROM "envoy_logs" WHERE status_code >= 500',
        ...     start_time="24h"
        ... )
    """

    def __init__(self):
        """Initialize Periscope client."""
        pass

    def convert_time_to_microseconds(
        self,
        time_input: str | int,
        timezone: Optional[str] = None
    ) -> int:
        """
        Convert time input to microseconds since epoch.

        Supports:
        - Relative time: "24h", "7d", "1w"
        - ISO timestamps: "2025-10-04T10:20:00+05:30"
        - Naive datetime with timezone param: "2025-10-04 10:20:00", timezone="Asia/Kolkata"
        - Microseconds: 1759527600000000

        Args:
            time_input: Time in various formats
            timezone: Timezone for naive datetime (e.g., "Asia/Kolkata")

        Returns:
            Microseconds since epoch (UTC)

        Example:
            >>> micros = periscope.convert_time_to_microseconds("24h")
            >>> micros = periscope.convert_time_to_microseconds(
            ...     "2025-10-04 10:20:00",
            ...     timezone="Asia/Kolkata"
            ... )
        """
        # If already microseconds
        if isinstance(time_input, int):
            return time_input

        # Relative time (e.g., "24h", "7d")
        relative_pattern = r'^(\d+)([hdwm])$'
        match = re.match(relative_pattern, str(time_input))
        if match:
            amount = int(match.group(1))
            unit = match.group(2)

            # Convert to seconds
            multipliers = {'h': 3600, 'd': 86400, 'w': 604800, 'm': 2592000}
            seconds = amount * multipliers[unit]

            # Get current time in the specified timezone (or UTC)
            if timezone:
                try:
                    tz = pytz.timezone(timezone)
                    now = datetime.now(tz)
                    logger.debug(f"Using timezone {timezone} for relative time calculation. Current time: {now}")
                except Exception as e:
                    logger.warning(f"Invalid timezone '{timezone}': {e}, using UTC")
                    now = datetime.now(pytz.UTC)
            else:
                now = datetime.now(pytz.UTC)
                logger.debug(f"Using UTC for relative time calculation. Current time: {now}")

            # Calculate timestamp (subtract the time delta)
            past_time = now - timedelta(seconds=seconds)
            
            # Convert to microseconds
            return int(past_time.timestamp() * 1_000_000)

        # Try parsing as ISO datetime
        try:
            # Check if it has timezone info
            if '+' in str(time_input) or str(time_input).endswith('Z'):
                # Parse with timezone
                if str(time_input).endswith('Z'):
                    dt = datetime.fromisoformat(str(time_input).replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(str(time_input))

                # Convert to UTC microseconds
                return int(dt.timestamp() * 1_000_000)

            # Naive datetime - apply timezone parameter
            else:
                # Parse as naive datetime
                try:
                    dt = datetime.fromisoformat(str(time_input))
                except ValueError:
                    # Try parsing with space instead of T
                    dt = datetime.strptime(str(time_input), "%Y-%m-%d %H:%M:%S")

                # Apply timezone
                if timezone:
                    try:
                        tz = pytz.timezone(timezone)
                        dt = tz.localize(dt)
                        logger.debug(f"Applied timezone {timezone} to naive datetime")
                    except Exception as e:
                        logger.warning(f"Invalid timezone '{timezone}': {e}, using UTC")
                        dt = pytz.UTC.localize(dt)
                else:
                    # Default to UTC
                    dt = pytz.UTC.localize(dt)
                    logger.debug("Applied default UTC timezone to naive datetime")

                # Convert to microseconds
                return int(dt.timestamp() * 1_000_000)

        except Exception as e:
            logger.error(f"Failed to parse time input '{time_input}': {e}")
            raise ValueError(f"Invalid time format: {time_input}") from e

    @cache_search
    async def search(
        self,
        sql_query: str,
        start_time: str | int = "24h",
        end_time: Optional[str | int] = None,
        timezone: Optional[str] = None,
        max_results: int = 50,
        org_identifier: str = DEFAULT_PERISCOPE_ORG
    ) -> Dict[str, Any]:
        """
        Execute SQL query on Periscope.

        Args:
            sql_query: SQL query to execute
            start_time: Start time (ISO, relative, or microseconds)
            end_time: End time (optional)
            timezone: Timezone for naive datetimes (e.g., "Asia/Kolkata")
            max_results: Maximum results to return
            org_identifier: Organization identifier

        Returns:
            Search results

        Raises:
            AuthenticationError: If no auth token
            PeriscopeAPIError: If search fails

        Example:
            >>> result = await periscope.search(
            ...     'SELECT * FROM "envoy_logs" WHERE status_code = 500',
            ...     start_time="2025-10-04 10:20:00",
            ...     timezone="Asia/Kolkata"
            ... )
        """
        with tracer.start_as_current_span("periscope.search") as span:
            span.set_attribute("periscope.query", sql_query)
            span.set_attribute("periscope.org", org_identifier)
            span.set_attribute("periscope.max_results", max_results)

            # Get auth token
            auth_token = auth_manager.get_token(AUTH_CONTEXT_PERISCOPE)
            if not auth_token:
                raise AuthenticationError(
                    "No Periscope authentication token available. "
                    "Please set it using set_periscope_auth_token endpoint."
                )

            # Convert times to microseconds
            start_micros = self.convert_time_to_microseconds(start_time, timezone)

            if end_time:
                end_micros = self.convert_time_to_microseconds(end_time, timezone)
            else:
                # Default to now
                end_micros = int(time.time() * 1_000_000)

            # Get Periscope host from config
            periscope_host = config.get('periscope.host', default='periscope.breezesdk.store')

            # Build URL - using legacy server format
            url = f"https://{periscope_host}/api/{org_identifier}/_search?type=logs&search_type=ui&use_cache=true"

            # Encode SQL to base64
            import base64
            sql_base64 = base64.b64encode(sql_query.encode()).decode()

            # Build payload - using legacy server format
            payload = {
                "query": {
                    "sql": sql_base64,
                    "start_time": start_micros,
                    "end_time": end_micros,
                    "from": 0,
                    "size": max_results,
                    "quick_mode": False,
                    "sql_mode": "full"
                },
                "encoding": "base64"
            }

            # Set headers - using legacy server format
            headers = {
                "accept": "application/json",
                HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
                "origin": f"https://{periscope_host}"
            }

            logger.debug(
                f"Periscope search: {sql_query[:100]}... "
                f"time_range={start_time} to {end_time or 'now'}"
            )

            # Set cookies - Periscope uses cookie-based auth
            cookies = {"auth_tokens": auth_token}

            # Execute with retry
            async def _execute_search():
                async with http_manager.get_client() as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                        cookies=cookies
                    )

                    if response.status_code == 200:
                        result = response.json()
                        logger.debug(f"Periscope search successful")
                        return result

                    if response.status_code in (401, 403):
                        raise AuthenticationError(
                            "Periscope authentication failed",
                            details={"status_code": response.status_code}
                        )

                    error_text = response.text
                    raise PeriscopeAPIError(
                        "Periscope search failed",
                        status_code=response.status_code,
                        response_body=error_text
                    )

            try:
                return await default_retry_manager.retry_async(_execute_search)
            except (AuthenticationError, PeriscopeAPIError):
                raise
            except Exception as e:
                raise PeriscopeAPIError(
                    f"Periscope search error: {str(e)}",
                    details={"error": str(e)}
                ) from e

    async def search_errors(
        self,
        hours: int = 24,
        stream: str = "envoy_logs",
        error_codes: Optional[str] = None,
        org_identifier: str = DEFAULT_PERISCOPE_ORG,
        timezone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for error logs (4xx/5xx).

        Args:
            hours: Hours to look back
            stream: Stream name to search
            error_codes: Error code pattern (e.g., "5%")
            org_identifier: Organization identifier
            timezone: Timezone for relative time (e.g., "Asia/Kolkata")

        Returns:
            Error logs

        Example:
            >>> errors = await periscope.search_errors(
            ...     hours=24,
            ...     stream="envoy_logs",
            ...     error_codes="5%",
            ...     timezone="Asia/Kolkata"
            ... )
        """
        # Validate inputs
        stream = sanitize_stream_name(stream)
        if error_codes:
            error_codes = sanitize_error_code_pattern(error_codes)

        # Build SQL query
        if error_codes:
            where_clause = f"WHERE status_code LIKE '{error_codes}'"
        else:
            where_clause = "WHERE status_code >= '400'"

        sql_query = f'SELECT * FROM "{stream}" {where_clause}'

        # Execute search with timezone
        return await self.search(
            sql_query=sql_query,
            start_time=f"{hours}h",
            org_identifier=org_identifier,
            timezone=timezone
        )

    async def get_streams(
        self,
        org_identifier: str = DEFAULT_PERISCOPE_ORG
    ) -> List[Dict[str, Any]]:
        """
        Get available Periscope streams.

        Args:
            org_identifier: Organization identifier

        Returns:
            List of stream information

        Example:
            >>> streams = await periscope.get_streams()
        """
        with tracer.start_as_current_span("periscope.get_streams") as span:
            span.set_attribute("periscope.org", org_identifier)
            auth_token = auth_manager.get_token(AUTH_CONTEXT_PERISCOPE)
            if not auth_token:
                raise AuthenticationError("No Periscope auth token available")

            # Get Periscope host from config
            periscope_host = config.get('periscope.host', default='periscope.breezesdk.store')

            # Build URL - using legacy server format
            url = f"https://{periscope_host}/api/{org_identifier}/streams?type=logs"

            headers = {
                "accept": "application/json"
            }

            # Use cookie-based auth
            cookies = {"auth_tokens": auth_token}

            async with http_manager.get_client() as client:
                response = await client.get(url, headers=headers, cookies=cookies)

                if response.status_code == 200:
                    data = response.json()
                    # Response format is {"list": [...], "total": 10}
                    if isinstance(data, dict) and "list" in data:
                        return data["list"]
                    # Fallback for direct list
                    return data if isinstance(data, list) else []

                raise PeriscopeAPIError(
                    f"Failed to get streams: {response.status_code} {response.text}",
                    status_code=response.status_code,
                    response_body=response.text
                )

    @cache_schema
    async def get_stream_schema(
        self,
        stream_name: str,
        org_identifier: str = DEFAULT_PERISCOPE_ORG
    ) -> Dict[str, Any]:
        """
        Get schema for a Periscope stream.

        Args:
            stream_name: Stream name
            org_identifier: Organization identifier

        Returns:
            Stream schema information

        Example:
            >>> schema = await periscope.get_stream_schema("envoy_logs")
        """
        with tracer.start_as_current_span("periscope.get_stream_schema") as span:
            span.set_attribute("periscope.stream_name", stream_name)
            span.set_attribute("periscope.org", org_identifier)

            # Validate stream name
            stream_name = sanitize_stream_name(stream_name)

            auth_token = auth_manager.get_token(AUTH_CONTEXT_PERISCOPE)
            if not auth_token:
                raise AuthenticationError("No Periscope auth token available")

            # Get Periscope host from config
            periscope_host = config.get('periscope.host', default='periscope.breezesdk.store')

            # Build URL - using legacy server format
            url = f"https://{periscope_host}/api/{org_identifier}/streams/{stream_name}/schema?type=logs"

            headers = {
                "accept": "application/json"
            }

            # Use cookie-based auth
            cookies = {"auth_tokens": auth_token}

            async with http_manager.get_client() as client:
                response = await client.get(url, headers=headers, cookies=cookies)

                if response.status_code == 200:
                    return response.json()

                raise PeriscopeAPIError(
                    f"Failed to get schema for stream '{stream_name}': {response.status_code} {response.text}",
                    status_code=response.status_code,
                    response_body=response.text
                )


# Global singleton instance
periscope_client = PeriscopeClient()
