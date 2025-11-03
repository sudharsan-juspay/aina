"""
HTTP Manager Module

Manages HTTP connections with connection pooling and configuration.
"""

import httpx
from typing import Optional
from loguru import logger

from src.core.config import config
from src.core.constants import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    MAX_KEEPALIVE_CONNECTIONS,
    MAX_CONNECTIONS,
)


class HTTPManager:
    """
    HTTP connection manager with pooling.

    Features:
    - Connection pooling
    - Configurable timeouts
    - SSL verification control
    - Automatic redirect following
    - Thread-safe operation

    Example:
        >>> http_manager = HTTPManager()
        >>> async with http_manager.get_client() as client:
        ...     response = await client.get('https://example.com')
    """

    def __init__(self):
        """Initialize HTTP manager."""
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = httpx.Timeout(
            timeout=DEFAULT_REQUEST_TIMEOUT,
            connect=DEFAULT_CONNECT_TIMEOUT
        )
        # Increased limits for higher throughput, as per performance plan
        self._limits = httpx.Limits(
            max_keepalive_connections=50,
            max_connections=200
        )

    def get_client(
        self,
        verify_ssl: Optional[bool] = None,
        timeout: Optional[float] = None,
        follow_redirects: bool = True
    ) -> httpx.AsyncClient:
        """
        Get configured HTTP client.

        Args:
            verify_ssl: Whether to verify SSL certificates (None = use config)
            timeout: Request timeout in seconds (None = use default)
            follow_redirects: Whether to follow redirects

        Returns:
            Configured AsyncClient

        Example:
            >>> client = http_manager.get_client(verify_ssl=False)
            >>> async with client:
            ...     response = await client.get('https://example.com')
        """
        # Get verify_ssl from config if not specified
        if verify_ssl is None:
            verify_ssl = config.get('elasticsearch.verify_ssl', default=True, expected_type=bool)

        # Ensure verify_ssl is boolean
        if isinstance(verify_ssl, str):
            verify_ssl = verify_ssl.lower() in ('true', '1', 'yes')

        # Create timeout config
        if timeout is not None:
            timeout_config = httpx.Timeout(timeout=timeout, connect=DEFAULT_CONNECT_TIMEOUT)
        else:
            timeout_config = self._timeout

        # Create and return client
        return httpx.AsyncClient(
            verify=verify_ssl,
            follow_redirects=follow_redirects,
            timeout=timeout_config,
            limits=self._limits,
            http2=True  # Enable HTTP/2 for performance
        )

    def get_sync_client(
        self,
        verify_ssl: Optional[bool] = None,
        timeout: Optional[float] = None,
        follow_redirects: bool = True
    ) -> httpx.Client:
        """
        Get configured synchronous HTTP client.

        Args:
            verify_ssl: Whether to verify SSL certificates
            timeout: Request timeout in seconds
            follow_redirects: Whether to follow redirects

        Returns:
            Configured Client
        """
        if verify_ssl is None:
            verify_ssl = config.get('elasticsearch.verify_ssl', default=True, expected_type=bool)

        if isinstance(verify_ssl, str):
            verify_ssl = verify_ssl.lower() in ('true', '1', 'yes')

        if timeout is not None:
            timeout_config = httpx.Timeout(timeout=timeout, connect=DEFAULT_CONNECT_TIMEOUT)
        else:
            timeout_config = self._timeout

        return httpx.Client(
            verify=verify_ssl,
            follow_redirects=follow_redirects,
            timeout=timeout_config,
            limits=self._limits
        )

    async def close(self):
        """Close HTTP client and cleanup resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("HTTP client closed")

    def __del__(self):
        """Cleanup on deletion."""
        # Note: Can't use async cleanup in __del__
        # Clients should be properly closed using close()
        pass


# Global singleton instance
http_manager = HTTPManager()
