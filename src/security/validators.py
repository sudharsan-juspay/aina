"""
Input Validation Module

Provides security validation for user inputs including KQL queries,
session IDs, and other user-provided data.

Works in conjunction with Pydantic models for comprehensive validation.
"""

import re
from typing import Optional


class ValidationError(Exception):
    """Raised when security validation fails."""
    pass


class QueryValidator:
    """
    Validate user queries for security threats.

    Provides validation methods for KQL queries, SQL queries, and other
    user inputs that could contain malicious content.
    """

    # Dangerous SQL keywords that should not appear in KQL queries
    DANGEROUS_SQL_KEYWORDS = [
        'drop', 'delete', 'insert', 'update', 'create',
        'alter', 'truncate', 'exec', 'execute', 'union',
        'script', 'javascript', '<script', 'eval'
    ]

    # Dangerous patterns in queries
    DANGEROUS_PATTERNS = [
        r'<script[^>]*>',  # Script tags
        r'javascript:',     # JavaScript protocol
        r'on\w+\s*=',      # Event handlers (onclick, onerror, etc.)
        r'\beval\s*\(',    # eval() function
        r'\.\./',          # Path traversal
    ]

    @staticmethod
    def validate_kql_query(query: str, max_length: int = 5000) -> str:
        """
        Validate KQL query for injection attempts.

        Checks for:
        - Dangerous SQL keywords
        - Script injection attempts
        - Excessive length
        - Dangerous patterns

        Args:
            query: KQL query string
            max_length: Maximum allowed query length

        Returns:
            Validated query (same as input if valid)

        Raises:
            ValidationError: If query contains dangerous content

        Example:
            >>> QueryValidator.validate_kql_query('level:ERROR AND service:payment')
            'level:ERROR AND service:payment'
            >>> QueryValidator.validate_kql_query('DROP TABLE users')
            ValidationError: Dangerous keyword 'drop' detected
        """
        if not query:
            raise ValidationError("Query cannot be empty")

        # Check length
        if len(query) > max_length:
            raise ValidationError(
                f"Query too long: {len(query)} characters. "
                f"Maximum allowed: {max_length} characters."
            )

        query_lower = query.lower()

        # Check for SQL injection attempts
        for keyword in QueryValidator.DANGEROUS_SQL_KEYWORDS:
            # Use word boundaries to avoid false positives
            # (e.g., "dropped" shouldn't match "drop")
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, query_lower):
                raise ValidationError(
                    f"Dangerous keyword '{keyword}' detected in query. "
                    "This may be an injection attempt."
                )

        # Check for dangerous patterns
        for pattern in QueryValidator.DANGEROUS_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                raise ValidationError(
                    f"Dangerous pattern detected in query. "
                    f"Pattern: {pattern}"
                )

        return query

    @staticmethod
    def validate_session_id(session_id: str, max_length: int = 200) -> str:
        """
        Validate session ID format.

        Session IDs should only contain alphanumeric characters,
        underscores, and hyphens.

        Args:
            session_id: Session ID to validate
            max_length: Maximum allowed length

        Returns:
            Validated session ID

        Raises:
            ValidationError: If session ID format is invalid

        Example:
            >>> QueryValidator.validate_session_id('abc-123_def')
            'abc-123_def'
            >>> QueryValidator.validate_session_id('abc; DROP TABLE')
            ValidationError: Invalid session ID format
        """
        if not session_id:
            raise ValidationError("Session ID cannot be empty")

        # Only allow alphanumeric, underscore, and hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', session_id):
            raise ValidationError(
                f"Invalid session ID format: '{session_id}'. "
                "Only alphanumeric characters, underscores, and hyphens are allowed."
            )

        if len(session_id) > max_length:
            raise ValidationError(
                f"Session ID too long: {len(session_id)} characters. "
                f"Maximum allowed: {max_length} characters."
            )

        return session_id

    @staticmethod
    def validate_order_id(order_id: str, max_length: int = 100) -> str:
        """
        Validate order ID format.

        Args:
            order_id: Order ID to validate
            max_length: Maximum allowed length

        Returns:
            Validated order ID

        Raises:
            ValidationError: If order ID format is invalid

        Example:
            >>> QueryValidator.validate_order_id('ORDER_12345')
            'ORDER_12345'
        """
        if not order_id:
            raise ValidationError("Order ID cannot be empty")

        # Allow alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', order_id):
            raise ValidationError(
                f"Invalid order ID format: '{order_id}'. "
                "Only alphanumeric characters, underscores, and hyphens are allowed."
            )

        if len(order_id) > max_length:
            raise ValidationError(
                f"Order ID too long: {len(order_id)} characters. "
                f"Maximum allowed: {max_length} characters."
            )

        return order_id

    @staticmethod
    def validate_index_pattern(pattern: str, max_length: int = 100) -> str:
        """
        Validate Elasticsearch index pattern.

        Index patterns can contain alphanumeric characters, hyphens,
        underscores, wildcards (*), and dots.

        Args:
            pattern: Index pattern to validate
            max_length: Maximum allowed length

        Returns:
            Validated index pattern

        Raises:
            ValidationError: If pattern format is invalid

        Example:
            >>> QueryValidator.validate_index_pattern('breeze-v2*')
            'breeze-v2*'
            >>> QueryValidator.validate_index_pattern('logs-2023.*')
            'logs-2023.*'
        """
        if not pattern:
            raise ValidationError("Index pattern cannot be empty")

        # Allow alphanumeric, hyphen, underscore, asterisk, dot, comma
        if not re.match(r'^[a-zA-Z0-9_.*,-]+$', pattern):
            raise ValidationError(
                f"Invalid index pattern: '{pattern}'. "
                "Only alphanumeric characters, hyphens, underscores, "
                "asterisks, dots, and commas are allowed."
            )

        if len(pattern) > max_length:
            raise ValidationError(
                f"Index pattern too long: {len(pattern)} characters. "
                f"Maximum allowed: {max_length} characters."
            )

        return pattern

    @staticmethod
    def validate_field_name(field_name: str, max_length: int = 100) -> str:
        """
        Validate Elasticsearch field name.

        Args:
            field_name: Field name to validate
            max_length: Maximum allowed length

        Returns:
            Validated field name

        Raises:
            ValidationError: If field name format is invalid

        Example:
            >>> QueryValidator.validate_field_name('@timestamp')
            '@timestamp'
            >>> QueryValidator.validate_field_name('message.keyword')
            'message.keyword'
        """
        if not field_name:
            raise ValidationError("Field name cannot be empty")

        # Allow alphanumeric, underscore, hyphen, dot, @
        if not re.match(r'^[@a-zA-Z0-9_.-]+$', field_name):
            raise ValidationError(
                f"Invalid field name: '{field_name}'. "
                "Only alphanumeric characters, underscores, hyphens, "
                "dots, and @ are allowed."
            )

        if len(field_name) > max_length:
            raise ValidationError(
                f"Field name too long: {len(field_name)} characters. "
                f"Maximum allowed: {max_length} characters."
            )

        return field_name

    @staticmethod
    def validate_time_range(time_range: str) -> str:
        """
        Validate time range format.

        Accepts formats like: 1h, 24h, 7d, 30d, 1w, 1m

        Args:
            time_range: Time range string

        Returns:
            Validated time range

        Raises:
            ValidationError: If time range format is invalid

        Example:
            >>> QueryValidator.validate_time_range('24h')
            '24h'
            >>> QueryValidator.validate_time_range('7d')
            '7d'
        """
        if not time_range:
            raise ValidationError("Time range cannot be empty")

        # Match patterns like: 1h, 24h, 7d, 30d, 1w, 1m
        if not re.match(r'^\d+[hdwm]$', time_range):
            raise ValidationError(
                f"Invalid time range format: '{time_range}'. "
                "Expected format: number + unit (h=hours, d=days, w=weeks, m=months). "
                "Examples: '1h', '24h', '7d', '30d'"
            )

        return time_range

    @staticmethod
    def sanitize_for_display(text: str, max_length: int = 1000) -> str:
        """
        Sanitize text for safe display in logs or UI.

        Removes or escapes potentially dangerous characters.

        Args:
            text: Text to sanitize
            max_length: Maximum length to display

        Returns:
            Sanitized text safe for display
        """
        if not text:
            return ""

        # Truncate long text
        if len(text) > max_length:
            text = text[:max_length] + "... (truncated)"

        # Remove null bytes
        text = text.replace('\x00', '')

        # Escape HTML entities for safe display
        text = (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#x27;'))

        return text
