"""
Core Module

Provides foundational utilities including configuration management,
logging setup, custom exceptions, and application constants.
"""

from .exceptions import (
    KibanaMCPException,
    AuthenticationError,
    ValidationError,
    KibanaAPIError,
    PeriscopeAPIError,
    SQLInjectionAttempt,
    RateLimitExceeded,
    SessionNotFoundError,
    ConfigurationError,
)
from .config import Config, config
from .logging_config import setup_logging

__all__ = [
    "KibanaMCPException",
    "AuthenticationError",
    "ValidationError",
    "KibanaAPIError",
    "PeriscopeAPIError",
    "SQLInjectionAttempt",
    "RateLimitExceeded",
    "SessionNotFoundError",
    "ConfigurationError",
    "Config",
    "config",
    "setup_logging",
]
