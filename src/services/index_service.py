"""
Index Service Module

Business logic for Elasticsearch index management.
"""

from typing import Dict, List, Optional, Any
from loguru import logger

from src.clients.kibana_client import kibana_client
from src.core.exceptions import IndexNotFoundError
from src.security.validators import QueryValidator


class IndexService:
    """
    Service for index management operations.

    Provides index discovery and selection functionality.

    Example:
        >>> index_service = IndexService()
        >>> indexes = await index_service.discover_indexes()
        >>> await index_service.set_current_index('breeze-v2*')
    """

    def __init__(self):
        """Initialize index service."""
        pass

    async def discover_indexes(self) -> Dict[str, Any]:
        """
        Discover available Elasticsearch indexes.

        Returns:
            Dictionary with list of available index patterns

        Example:
            >>> result = await index_service.discover_indexes()
            >>> print(result['indexes'])
            ['breeze-v2*', 'istio-logs-v2*', 'envoy-edge*']
        """
        try:
            # Get indexes from Kibana client
            indexes = await kibana_client.discover_indexes()

            # Get current index
            current_index = kibana_client.get_current_index()

            return {
                "success": True,
                "indexes": indexes,
                "current_index": current_index,
                "count": len(indexes),
                "message": f"Discovered {len(indexes)} index patterns"
            }

        except Exception as e:
            logger.error(f"Failed to discover indexes: {e}")
            raise IndexNotFoundError(
                "Failed to discover indexes",
                details={"error": str(e)}
            ) from e

    async def set_current_index(self, index_pattern: str) -> Dict[str, Any]:
        """
        Set current index pattern for searches.

        Args:
            index_pattern: Elasticsearch index pattern to use

        Returns:
            Success confirmation

        Raises:
            ValidationError: If index pattern is invalid

        Example:
            >>> result = await index_service.set_current_index('breeze-v2*')
        """
        # Validate index pattern
        index_pattern = QueryValidator.validate_index_pattern(index_pattern)

        # Set in Kibana client
        kibana_client.set_current_index(index_pattern)

        return {
            "success": True,
            "index_pattern": index_pattern,
            "message": f"Current index set to: {index_pattern}"
        }

    def get_current_index(self) -> Optional[str]:
        """
        Get currently selected index pattern.

        Returns:
            Current index pattern or None

        Example:
            >>> current = index_service.get_current_index()
        """
        return kibana_client.get_current_index()

    async def get_index_info(self, index_pattern: str) -> Dict[str, Any]:
        """
        Get information about a specific index.

        Args:
            index_pattern: Index pattern to get info for

        Returns:
            Index information including doc count, size, etc.

        Example:
            >>> info = await index_service.get_index_info('breeze-v2*')
        """
        # Validate
        index_pattern = QueryValidator.validate_index_pattern(index_pattern)

        # Get index stats by searching with size 0
        try:
            result = await kibana_client.search(
                index_pattern=index_pattern,
                query={"match_all": {}},
                size=0
            )

            total_docs = result.get('hits', {}).get('total', {})
            if isinstance(total_docs, dict):
                doc_count = total_docs.get('value', 0)
            else:
                doc_count = total_docs

            return {
                "success": True,
                "index_pattern": index_pattern,
                "doc_count": doc_count,
                "message": f"Index has {doc_count} documents"
            }

        except Exception as e:
            logger.error(f"Failed to get index info for {index_pattern}: {e}")
            raise IndexNotFoundError(
                f"Failed to get info for index: {index_pattern}",
                index_pattern=index_pattern,
                details={"error": str(e)}
            ) from e


# Global singleton instance
index_service = IndexService()
