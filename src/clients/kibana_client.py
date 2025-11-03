"""
Kibana Client Module

Client for interacting with Kibana API.
"""

import json
from typing import Dict, List, Optional, Any
from loguru import logger

from src.core.config import config
from src.core.exceptions import KibanaAPIError, AuthenticationError
from src.core.constants import (
    HEADER_KBN_VERSION,
    HEADER_CONTENT_TYPE,
    CONTENT_TYPE_JSON,
    DEFAULT_KIBANA_VERSION,
    DEFAULT_KIBANA_BASE_PATH,
)
from src.security.auth import auth_manager, AUTH_CONTEXT_KIBANA
from .http_manager import http_manager
from .retry_manager import default_retry_manager
from src.observability.tracing import get_tracer

tracer = get_tracer(__name__)


class KibanaClient:
    """
    Client for Kibana API operations.

    Handles authentication, request formatting, and response parsing
    for Kibana/Elasticsearch queries.

    Example:
        >>> kibana = KibanaClient()
        >>> result = await kibana.search(
        ...     index_pattern="breeze-v2*",
        ...     query={"match_all": {}},
        ...     size=100
        ... )
    """

    def __init__(self):
        """Initialize Kibana client."""
        self._current_index: Optional[str] = None

    def get_current_index(self) -> Optional[str]:
        """Get currently selected index pattern."""
        return self._current_index

    def set_current_index(self, index_pattern: str) -> None:
        """
        Set current index pattern.

        Args:
            index_pattern: Elasticsearch index pattern
        """
        self._current_index = index_pattern
        logger.info(f"Current index set to: {index_pattern}")

    async def search(
        self,
        index_pattern: Optional[str],
        query: Dict[str, Any],
        size: int = 10,
        sort: Optional[List[Dict]] = None,
        aggs: Optional[Dict] = None,
        include_fields: Optional[List[str]] = None,
        exclude_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute search query through Kibana API.

        Args:
            index_pattern: Index pattern to search (None = use current)
            query: Elasticsearch query DSL
            size: Number of results to return
            sort: Sort configuration
            aggs: Aggregations configuration
            include_fields: Fields to include in results
            exclude_fields: Fields to exclude from results

        Returns:
            Search results dictionary

        Raises:
            AuthenticationError: If no auth token available
            KibanaAPIError: If search fails

        Example:
            >>> result = await kibana.search(
            ...     index_pattern="logs-*",
            ...     query={"match": {"level": "ERROR"}},
            ...     size=50
            ... )
        """
        with tracer.start_as_current_span("kibana.search") as span:
            span.set_attribute("kibana.index_pattern", index_pattern or self._current_index)
            span.set_attribute("kibana.query_size", size)

            # Use current index if not specified
            actual_index = index_pattern or self._current_index
            if not actual_index:
                raise KibanaAPIError(
                    "No index pattern specified and no current index set",
                    details={"hint": "Call set_current_index() first"}
                )

            # Get auth token
            auth_token = auth_manager.get_token(AUTH_CONTEXT_KIBANA)
            if not auth_token:
                raise AuthenticationError(
                    "No Kibana authentication token available. "
                    "Please set it using set_auth_token endpoint."
                )

            # Get configuration
            host = config.get('elasticsearch.host')
            base_path = config.get(
                'elasticsearch.kibana_api.base_path',
                default=DEFAULT_KIBANA_BASE_PATH
            )
            kibana_version = config.get(
                'elasticsearch.kibana_api.version',
                default=DEFAULT_KIBANA_VERSION
            )

            # Build URL
            url = f"https://{host}{base_path}/internal/search/es"

            # Build request body
            search_body: Dict[str, Any] = {
                "query": query,
                "size": size
            }

            # Add sort if provided
            if sort:
                search_body["sort"] = sort

            # Add aggregations if provided
            if aggs:
                search_body["aggs"] = aggs

            # Add field filtering
            if include_fields or exclude_fields:
                search_body["_source"] = {}
                if include_fields:
                    search_body["_source"]["includes"] = include_fields
                if exclude_fields:
                    search_body["_source"]["excludes"] = exclude_fields

            # Format payload for Kibana API
            payload = {
                "params": {
                    "index": actual_index,
                    "body": search_body
                }
            }

            # Set headers
            headers = {
                HEADER_KBN_VERSION: kibana_version,
                HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON
            }

            # Set cookies
            cookies = {"_pomerium": auth_token}

            logger.debug(f"Kibana search: index={actual_index}, size={size}")

            # Execute request with retry logic
            async def _execute_search():
                async with http_manager.get_client() as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                        cookies=cookies
                    )

                    # Handle response
                    if response.status_code == 200:
                        result = response.json()

                        # Kibana API wraps response in 'rawResponse'
                        if "rawResponse" in result:
                            actual_result = result["rawResponse"]
                            logger.debug(f"Kibana search successful (rawResponse format): {actual_result.get('hits', {}).get('total', 0)} hits")
                            return actual_result
                        else:
                            logger.debug(f"Kibana search successful: {result.get('hits', {}).get('total', 0)} hits")
                            return result

                    # Handle authentication errors
                    if response.status_code in (401, 403):
                        raise AuthenticationError(
                            "Kibana authentication failed. Check your auth token.",
                            details={"status_code": response.status_code}
                        )

                    # Handle other errors
                    error_text = response.text
                    raise KibanaAPIError(
                        f"Kibana search failed",
                        status_code=response.status_code,
                        response_body=error_text
                    )

            try:
                return await default_retry_manager.retry_async(_execute_search)
            except KibanaAPIError:
                raise
            except AuthenticationError:
                raise
            except Exception as e:
                raise KibanaAPIError(
                    f"Kibana search error: {str(e)}",
                    details={"error": str(e)}
                ) from e

    async def discover_indexes(self) -> List[str]:
        """
        Discover available Elasticsearch indexes.

        Returns:
            List of index patterns

        Raises:
            AuthenticationError: If no auth token available
            KibanaAPIError: If discovery fails

        Example:
            >>> indexes = await kibana.discover_indexes()
            >>> print(indexes)
            ['breeze-v2*', 'istio-logs-v2*', 'envoy-edge*']
        """
        with tracer.start_as_current_span("kibana.discover_indexes"):
            auth_token = auth_manager.get_token(AUTH_CONTEXT_KIBANA)
            if not auth_token:
                raise AuthenticationError(
                    "No authentication token available for index discovery"
                )

            host = config.get('elasticsearch.host')
            base_path = config.get(
                'elasticsearch.kibana_api.base_path',
                default=DEFAULT_KIBANA_BASE_PATH
            )
            kibana_version = config.get(
                'elasticsearch.kibana_api.version',
                default=DEFAULT_KIBANA_VERSION
            )

            headers = {
                HEADER_KBN_VERSION: kibana_version,
                HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON
            }
            cookies = {"_pomerium": auth_token}

            # Try to get index patterns from Kibana saved objects API
            url = f"https://{host}{base_path}/api/saved_objects/_find?type=index-pattern"

            async with http_manager.get_client() as client:
                try:
                    response = await client.get(url, headers=headers, cookies=cookies)

                    if response.status_code == 200:
                        data = response.json()
                        saved_objects = data.get('saved_objects', [])
                        index_patterns = [
                            obj.get('attributes', {}).get('title', '')
                            for obj in saved_objects
                            if obj.get('attributes', {}).get('title')
                        ]
                        if index_patterns:
                            logger.info(f"Discovered {len(index_patterns)} index patterns from Kibana")
                            return index_patterns
                except Exception as e:
                    logger.warning(f"Failed to get index patterns from Kibana: {e}")

            # Fallback: Get indices directly from Elasticsearch
            es_url = f"https://{host}/_cat/indices?format=json"

            async with http_manager.get_client() as client:
                try:
                    response = await client.get(es_url, headers=headers, cookies=cookies)

                    if response.status_code == 200:
                        indices = response.json()
                        index_names = [idx.get('index', '') for idx in indices if idx.get('index')]

                        # Extract unique patterns
                        patterns = set()
                        for name in index_names:
                            # Extract pattern (e.g., "breeze-v2-2023-01-01" -> "breeze-v2*")
                            parts = name.split('-')
                            if len(parts) >= 2:
                                pattern = f"{'-'.join(parts[:2])}*"
                                patterns.add(pattern)

                        logger.info(f"Discovered {len(patterns)} index patterns from Elasticsearch")
                        return sorted(list(patterns))
                except Exception as e:
                    logger.warning(f"Failed to get indices from Elasticsearch: {e}")

            # If all methods fail
            raise KibanaAPIError(
                "Failed to discover indexes",
                details={"hint": "Check authentication and network connectivity"}
            )


# Global singleton instance
kibana_client = KibanaClient()
