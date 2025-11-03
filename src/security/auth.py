"""
Authentication Manager Module

CRITICAL SECURITY: Thread-safe authentication token management.

This module replaces the global DYNAMIC_AUTH_TOKEN and PERISCOPE_AUTH_TOKEN
with a thread-safe, context-based authentication system.

Security improvements:
- Thread-safe token storage (no race conditions)
- Token expiration and rotation support
- Separate token contexts (Kibana, Periscope)
- Audit logging for token operations
"""

import time
from threading import Lock
from typing import Optional, Dict
from dataclasses import dataclass
from loguru import logger


@dataclass
class TokenInfo:
    """
    Metadata for an authentication token.

    Attributes:
        token: The actual authentication token
        expires_at: Unix timestamp when token expires (0 = never expires)
        context: Token context identifier (e.g., 'kibana', 'periscope', 'user123')
        created_at: Unix timestamp when token was created
    """
    token: str
    expires_at: float = 0.0  # 0 means never expires
    context: str = "default"
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def is_expired(self) -> bool:
        """Check if token has expired."""
        if self.expires_at == 0.0:
            return False  # Never expires
        return time.time() > self.expires_at

    def time_until_expiry(self) -> float:
        """Get seconds until token expires. Returns -1 if never expires."""
        if self.expires_at == 0.0:
            return -1.0
        return max(0.0, self.expires_at - time.time())


class AuthManager:
    """
    Thread-safe authentication token manager.

    Replaces global authentication variables with proper encapsulation
    and thread safety.

    Features:
    - Thread-safe token storage and retrieval
    - Token expiration management
    - Multiple token contexts (Kibana, Periscope, users)
    - Automatic cleanup of expired tokens
    - Audit logging for security

    Example:
        >>> auth = AuthManager()
        >>> auth.set_token('kibana', 'my-token-123', ttl=3600)
        >>> token = auth.get_token('kibana')
        >>> auth.validate_token('kibana', 'my-token-123')
        True
    """

    def __init__(self):
        """Initialize the authentication manager."""
        self._tokens: Dict[str, TokenInfo] = {}
        self._lock = Lock()

    def set_token(
        self,
        context: str,
        token: str,
        ttl: float = 0.0
    ) -> None:
        """
        Store authentication token for a context.

        Args:
            context: Token context (e.g., 'kibana', 'periscope', 'user123')
            token: Authentication token
            ttl: Time to live in seconds (0 = never expires)

        Example:
            >>> auth.set_token('kibana', 'token123', ttl=3600)
            >>> auth.set_token('periscope', 'token456')  # Never expires
        """
        if not token:
            raise ValueError("Token cannot be empty")

        if not context:
            raise ValueError("Context cannot be empty")

        expires_at = time.time() + ttl if ttl > 0 else 0.0

        with self._lock:
            self._tokens[context] = TokenInfo(
                token=token,
                expires_at=expires_at,
                context=context
            )

            # Log token update (don't log the actual token for security)
            expiry_msg = f"expires in {ttl}s" if ttl > 0 else "never expires"
            logger.info(
                f"Authentication token set for context '{context}' ({expiry_msg})"
            )

    def get_token(self, context: str) -> Optional[str]:
        """
        Get authentication token for a context.

        Automatically removes expired tokens.

        Args:
            context: Token context

        Returns:
            Token string if valid, None if not found or expired

        Example:
            >>> token = auth.get_token('kibana')
            >>> if token:
            ...     # Use token for authentication
        """
        with self._lock:
            token_info = self._tokens.get(context)

            if not token_info:
                return None

            # Check expiration
            if token_info.is_expired():
                logger.warning(f"Token for context '{context}' has expired, removing")
                del self._tokens[context]
                return None

            return token_info.token

    def validate_token(self, context: str, token: str) -> bool:
        """
        Validate that a token matches the stored token for a context.

        Args:
            context: Token context
            token: Token to validate

        Returns:
            True if token is valid and not expired, False otherwise

        Example:
            >>> if auth.validate_token('kibana', user_provided_token):
            ...     # Token is valid
        """
        stored_token = self.get_token(context)
        return stored_token == token if stored_token else False

    def rotate_token(self, context: str, new_token: str, ttl: float = 0.0) -> None:
        """
        Rotate token for a context (update with new token).

        This is a convenience method that logs the rotation for audit purposes.

        Args:
            context: Token context
            new_token: New authentication token
            ttl: Time to live in seconds

        Example:
            >>> auth.rotate_token('kibana', 'new-token-xyz', ttl=7200)
        """
        logger.info(f"Rotating authentication token for context '{context}'")
        self.set_token(context, new_token, ttl)

    def remove_token(self, context: str) -> bool:
        """
        Remove token for a context.

        Args:
            context: Token context to remove

        Returns:
            True if token was removed, False if not found

        Example:
            >>> auth.remove_token('kibana')
        """
        with self._lock:
            if context in self._tokens:
                del self._tokens[context]
                logger.info(f"Authentication token removed for context '{context}'")
                return True
            return False

    def cleanup_expired_tokens(self) -> int:
        """
        Remove all expired tokens from storage.

        Returns:
            Number of expired tokens removed

        Example:
            >>> count = auth.cleanup_expired_tokens()
            >>> print(f"Removed {count} expired tokens")
        """
        with self._lock:
            expired_contexts = [
                context
                for context, token_info in self._tokens.items()
                if token_info.is_expired()
            ]

            for context in expired_contexts:
                del self._tokens[context]

            if expired_contexts:
                logger.info(
                    f"Cleaned up {len(expired_contexts)} expired tokens: "
                    f"{', '.join(expired_contexts)}"
                )

            return len(expired_contexts)

    def get_all_contexts(self) -> list[str]:
        """
        Get list of all contexts with tokens.

        Returns:
            List of context identifiers

        Example:
            >>> contexts = auth.get_all_contexts()
            >>> print(f"Active tokens: {', '.join(contexts)}")
        """
        with self._lock:
            return list(self._tokens.keys())

    def has_token(self, context: str) -> bool:
        """
        Check if a valid token exists for a context.

        Args:
            context: Token context

        Returns:
            True if valid token exists, False otherwise

        Example:
            >>> if not auth.has_token('kibana'):
            ...     print("Please set Kibana authentication token")
        """
        return self.get_token(context) is not None


# Authentication context constants
AUTH_CONTEXT_KIBANA = 'kibana'
AUTH_CONTEXT_PERISCOPE = 'periscope'


# Global singleton instance
# This replaces the global DYNAMIC_AUTH_TOKEN and PERISCOPE_AUTH_TOKEN variables
auth_manager = AuthManager()


# Convenience functions for backward compatibility
def get_kibana_token() -> Optional[str]:
    """Get Kibana authentication token."""
    return auth_manager.get_token('kibana')


def set_kibana_token(token: str, ttl: float = 0.0) -> None:
    """Set Kibana authentication token."""
    auth_manager.set_token('kibana', token, ttl)


def get_periscope_token() -> Optional[str]:
    """Get Periscope authentication token."""
    return auth_manager.get_token('periscope')


def set_periscope_token(token: str, ttl: float = 0.0) -> None:
    """Set Periscope authentication token."""
    auth_manager.set_token('periscope', token, ttl)
