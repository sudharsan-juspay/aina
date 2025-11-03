"""
Session Service Module

Business logic for session ID extraction from logs.
"""

import re
from typing import Dict, List, Optional, Any
from loguru import logger

from src.clients.kibana_client import kibana_client
from src.core.exceptions import SessionNotFoundError
from src.security.validators import QueryValidator


class SessionService:
    """
    Service for session ID operations.

    Provides session ID extraction from order IDs using log analysis.

    Example:
        >>> session_service = SessionService()
        >>> result = await session_service.extract_session_id(
        ...     order_id='ORDER_12345'
        ... )
    """

    # Pattern for extracting session ID from log messages
    # Format: message:num | some_id | session_id | ...
    SESSION_ID_PATTERN = re.compile(r'message:\d+\s*\|\s*[^|]+\s*\|\s*([^|]+)\s*\|')

    def __init__(self):
        """Initialize session service."""
        pass

    async def extract_session_id(
        self,
        order_id: str,
        max_logs: int = 3
    ) -> Dict[str, Any]:
        """
        Extract session ID from order ID.

        Searches for logs containing the order ID and "callStartPayment",
        then extracts the session ID from the log message format.

        Args:
            order_id: Order ID to search for
            max_logs: Maximum logs to analyze (default: 3)

        Returns:
            Dictionary with session ID and extraction details

        Raises:
            SessionNotFoundError: If session ID cannot be found

        Example:
            >>> result = await session_service.extract_session_id('ORDER_12345')
            >>> print(result['session_id'])
            'abc-123-def-456'
        """
        # Validate order ID
        order_id = QueryValidator.validate_order_id(order_id)

        # Build KQL query to find logs with order ID and callStartPayment
        kql_query = f'{order_id} AND "callStartPayment"'

        # Search logs
        try:
            search_result = await kibana_client.search(
                index_pattern=None,  # Use current index
                query={
                    "query_string": {
                        "query": kql_query,
                        "default_field": "*"
                    }
                },
                size=max_logs
            )
        except Exception as e:
            logger.error(f"Failed to search logs for order ID {order_id}: {e}")
            raise SessionNotFoundError(
                f"Failed to search logs for order ID: {order_id}",
                order_id=order_id,
                details={"error": str(e)}
            ) from e

        # Extract session IDs from logs
        extraction_attempts = []
        session_ids_found = []

        hits = search_result.get('hits', {}).get('hits', [])

        if not hits:
            raise SessionNotFoundError(
                f"No logs found for order ID: {order_id}",
                order_id=order_id,
                details={
                    "query": kql_query,
                    "hint": "Verify order ID and ensure logs exist"
                }
            )

        for hit in hits:
            source = hit.get('_source', {})
            message = source.get('message', '')

            # Try to extract session ID from message
            session_id_info = self._extract_session_id_from_message(message)

            extraction_attempts.append({
                "message": message[:200] if message else None,  # Truncate for safety
                "session_id": session_id_info.get('session_id'),
                "status": session_id_info.get('status'),
                "timestamp": source.get('@timestamp')
            })

            if session_id_info.get('session_id'):
                session_ids_found.append(session_id_info['session_id'])

        # Determine primary session ID
        if session_ids_found:
            # Use the first found session ID
            primary_session_id = session_ids_found[0]

            return {
                "success": True,
                "order_id": order_id,
                "session_id": primary_session_id,
                "status": "extracted",
                "extraction_attempts": extraction_attempts,
                "all_session_ids": list(set(session_ids_found)),  # Unique session IDs
                "logs_searched": len(hits),
                "message": f"Session ID extracted successfully: {primary_session_id}"
            }
        else:
            # No session ID found in any logs
            raise SessionNotFoundError(
                f"Could not extract session ID from logs for order ID: {order_id}",
                order_id=order_id,
                details={
                    "logs_searched": len(hits),
                    "extraction_attempts": extraction_attempts,
                    "hint": "Session ID pattern not found in log messages"
                }
            )

    def _extract_session_id_from_message(self, message: str) -> Dict[str, Any]:
        """
        Extract session ID from log message.

        Expected format: message:num | some_id | session_id | ...

        Args:
            message: Log message to parse

        Returns:
            Dictionary with session_id and status
        """
        if not message:
            return {"session_id": None, "status": "empty_message"}

        # Try to match the pattern
        match = self.SESSION_ID_PATTERN.search(message)

        if match:
            session_id = match.group(1).strip()

            # Validate session ID format
            try:
                QueryValidator.validate_session_id(session_id)
                return {
                    "session_id": session_id,
                    "status": "extracted"
                }
            except Exception as e:
                logger.warning(f"Invalid session ID format: {session_id}")
                return {
                    "session_id": None,
                    "status": "invalid_format"
                }
        else:
            return {
                "session_id": None,
                "status": "pattern_not_found"
            }


# Global singleton instance
session_service = SessionService()
