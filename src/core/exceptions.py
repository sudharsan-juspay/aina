"""
Custom Exceptions Module

Defines the exception hierarchy for the Kibana MCP Server.

All application-specific exceptions inherit from KibanaMCPException
for easier error handling and filtering.
"""

from typing import Optional, Dict, Any


class KibanaMCPException(Exception):
    """
    Base exception for all Kibana MCP Server errors.

    All custom exceptions should inherit from this class.

    Attributes:
        message: Human-readable error message
        details: Optional dictionary with additional error context
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize exception.

        Args:
            message: Error message
            details: Optional additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for API responses.

        Returns:
            Dictionary with error information
        """
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class AuthenticationError(KibanaMCPException):
    """
    Raised when authentication fails.

    Examples:
    - Missing authentication token
    - Invalid authentication token
    - Expired authentication token
    """

    def __init__(self, message: str = "Authentication failed", details: Optional[Dict] = None):
        super().__init__(message, details)


class ValidationError(KibanaMCPException):
    """
    Raised when input validation fails.

    Examples:
    - Invalid KQL query format
    - Invalid session ID format
    - Invalid request parameters
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(message, details)


class KibanaAPIError(KibanaMCPException):
    """
    Raised when Kibana API request fails.

    Attributes:
        status_code: HTTP status code from Kibana
        response_body: Response body from Kibana (if available)
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize Kibana API error.

        Args:
            message: Error message
            status_code: HTTP status code
            response_body: Response body from API
            details: Additional error details
        """
        error_details = details or {}
        if status_code:
            error_details['status_code'] = status_code
        if response_body:
            error_details['response_body'] = response_body

        super().__init__(message, error_details)
        self.status_code = status_code
        self.response_body = response_body


class PeriscopeAPIError(KibanaMCPException):
    """
    Raised when Periscope API request fails.

    Attributes:
        status_code: HTTP status code from Periscope
        response_body: Response body from Periscope (if available)
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize Periscope API error.

        Args:
            message: Error message
            status_code: HTTP status code
            response_body: Response body from API
            details: Additional error details
        """
        error_details = details or {}
        if status_code:
            error_details['status_code'] = status_code
        if response_body:
            error_details['response_body'] = response_body

        super().__init__(message, error_details)
        self.status_code = status_code
        self.response_body = response_body


class SQLInjectionAttempt(KibanaMCPException):
    """
    Raised when SQL injection attempt is detected.

    This is a CRITICAL security exception that should be logged
    and potentially trigger alerts.
    """

    def __init__(
        self,
        message: str = "SQL injection attempt detected",
        query: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize SQL injection exception.

        Args:
            message: Error message
            query: The malicious query (truncated for safety)
            details: Additional error details
        """
        error_details = details or {}
        if query:
            # Truncate query for safety (don't log full malicious input)
            error_details['query_preview'] = query[:100] + "..." if len(query) > 100 else query

        super().__init__(message, error_details)


class RateLimitExceeded(KibanaMCPException):
    """
    Raised when rate limit is exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize rate limit exception.

        Args:
            message: Error message
            retry_after: Seconds to wait before retrying
            details: Additional error details
        """
        error_details = details or {}
        if retry_after:
            error_details['retry_after'] = retry_after

        super().__init__(message, error_details)
        self.retry_after = retry_after


class SessionNotFoundError(KibanaMCPException):
    """
    Raised when session ID cannot be found or extracted.

    Examples:
    - Session ID not found in logs for given order ID
    - Invalid session ID format
    """

    def __init__(
        self,
        message: str,
        order_id: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize session not found exception.

        Args:
            message: Error message
            order_id: Order ID that was searched
            details: Additional error details
        """
        error_details = details or {}
        if order_id:
            error_details['order_id'] = order_id

        super().__init__(message, error_details)


class ConfigurationError(KibanaMCPException):
    """
    Raised when configuration is invalid or missing.

    Examples:
    - Missing required configuration value
    - Invalid configuration format
    - Configuration file not found
    """

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize configuration exception.

        Args:
            message: Error message
            config_key: Configuration key that caused the error
            details: Additional error details
        """
        error_details = details or {}
        if config_key:
            error_details['config_key'] = config_key

        super().__init__(message, error_details)


class IndexNotFoundError(KibanaMCPException):
    """
    Raised when Elasticsearch index is not found.

    Examples:
    - Requested index pattern doesn't match any indices
    - Index has been deleted
    """

    def __init__(
        self,
        message: str,
        index_pattern: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize index not found exception.

        Args:
            message: Error message
            index_pattern: Index pattern that wasn't found
            details: Additional error details
        """
        error_details = details or {}
        if index_pattern:
            error_details['index_pattern'] = index_pattern

        super().__init__(message, error_details)


class TimeoutError(KibanaMCPException):
    """
    Raised when operation times out.

    Examples:
    - Kibana query takes too long
    - Periscope query timeout
    - Network connection timeout
    """

    def __init__(
        self,
        message: str = "Operation timed out",
        timeout_seconds: Optional[float] = None,
        details: Optional[Dict] = None
    ):
        """
        Initialize timeout exception.

        Args:
            message: Error message
            timeout_seconds: Timeout value that was exceeded
            details: Additional error details
        """
        error_details = details or {}
        if timeout_seconds:
            error_details['timeout_seconds'] = timeout_seconds

        super().__init__(message, error_details)
