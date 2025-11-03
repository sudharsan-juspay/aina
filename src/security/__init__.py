"""
Security Module

Provides authentication, input sanitization, validation, and rate limiting.
"""

from .sanitizers import (
    sanitize_stream_name,
    sanitize_error_code_pattern,
    sanitize_sql_identifier,
)
from .auth import AuthManager, auth_manager, AUTH_CONTEXT_KIBANA, AUTH_CONTEXT_PERISCOPE
from .validators import QueryValidator
from .rate_limiter import RateLimiter, search_rate_limiter, auth_rate_limiter

__all__ = [
    "sanitize_stream_name",
    "sanitize_error_code_pattern",
    "sanitize_sql_identifier",
    "AuthManager",
    "auth_manager",
    "AUTH_CONTEXT_KIBANA",
    "AUTH_CONTEXT_PERISCOPE",
    "QueryValidator",
    "RateLimiter",
    "search_rate_limiter",
    "auth_rate_limiter",
]
