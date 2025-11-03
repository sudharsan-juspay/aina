"""
Input Sanitization Module

CRITICAL SECURITY: Prevents SQL injection and other input-based attacks.

This module provides sanitization functions for user inputs, particularly
for Periscope SQL queries where direct SQL injection is possible.
"""

import re


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def sanitize_stream_name(stream: str) -> str:
    """
    Validate and sanitize Periscope stream name.

    Prevents SQL injection via stream name parameter using pattern validation.
    This is GENERIC and works with any customer's stream names.

    Args:
        stream: Stream name from user input

    Returns:
        Validated stream name (same as input if valid)

    Raises:
        ValidationError: If stream name contains invalid characters

    Security:
        - Only allows alphanumeric characters, underscores, and hyphens
        - Prevents SQL injection attempts
        - No hardcoded whitelist (works for all customers)

    Example:
        >>> sanitize_stream_name("envoy_logs")
        'envoy_logs'
        >>> sanitize_stream_name("customer_app_logs")
        'customer_app_logs'
        >>> sanitize_stream_name("malicious'; DROP TABLE logs; --")
        ValidationError: Invalid stream name format
    """
    if not stream:
        raise ValidationError("Stream name cannot be empty")

    # Generic validation: only allow safe SQL identifier characters
    # This works for ANY customer's stream names while preventing injection
    if not re.match(r'^[a-zA-Z0-9_-]+$', stream):
        raise ValidationError(
            f"Invalid stream name format: '{stream}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )

    # Limit length to prevent DoS
    if len(stream) > 100:
        raise ValidationError(
            f"Stream name too long: {len(stream)} characters. "
            "Maximum allowed: 100 characters."
        )

    return stream


def sanitize_error_code_pattern(pattern: str) -> str:
    """
    Validate error code pattern for SQL LIKE clause.

    Prevents SQL injection via error_codes parameter in Periscope queries.
    Only allows digits and the wildcard character '%'.

    Args:
        pattern: Error code pattern (e.g., "5%", "404", "4%")

    Returns:
        Sanitized pattern safe for SQL LIKE clause

    Raises:
        ValidationError: If pattern contains invalid characters

    Example:
        >>> sanitize_error_code_pattern("5%")
        '5%'
        >>> sanitize_error_code_pattern("404")
        '404'
        >>> sanitize_error_code_pattern("5%' OR '1'='1")
        ValidationError: Invalid error code pattern
    """
    if not pattern:
        raise ValidationError("Error code pattern cannot be empty")

    # Only allow digits and % wildcard
    if not re.match(r'^[0-9%]+$', pattern):
        raise ValidationError(
            f"Invalid error code pattern: '{pattern}'. "
            "Only digits and '%' wildcard are allowed."
        )

    # Limit length to prevent DoS attacks
    if len(pattern) > 10:
        raise ValidationError(
            f"Error code pattern too long: {len(pattern)} characters. "
            "Maximum allowed: 10 characters."
        )

    # Escape single quotes for SQL safety (defense in depth)
    # Even though we already validated the pattern, this adds extra protection
    sanitized = pattern.replace("'", "''")

    return sanitized


def sanitize_sql_identifier(identifier: str, max_length: int = 64) -> str:
    """
    Sanitize SQL identifiers (table names, column names, etc.).

    Prevents SQL injection via identifiers used in queries.
    Only allows alphanumeric characters, underscores, and hyphens.

    Args:
        identifier: SQL identifier to sanitize
        max_length: Maximum allowed length (default: 64)

    Returns:
        Sanitized identifier

    Raises:
        ValidationError: If identifier contains invalid characters or is too long

    Example:
        >>> sanitize_sql_identifier("column_name")
        'column_name'
        >>> sanitize_sql_identifier("table-name-123")
        'table-name-123'
        >>> sanitize_sql_identifier("evil'; DROP TABLE users; --")
        ValidationError: Invalid SQL identifier
    """
    if not identifier:
        raise ValidationError("SQL identifier cannot be empty")

    # Only allow alphanumeric, underscore, and hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', identifier):
        raise ValidationError(
            f"Invalid SQL identifier: '{identifier}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )

    if len(identifier) > max_length:
        raise ValidationError(
            f"SQL identifier too long: {len(identifier)} characters. "
            f"Maximum allowed: {max_length} characters."
        )

    return identifier


def sanitize_sql_query_for_logging(query: str, max_length: int = 200) -> str:
    """
    Sanitize SQL query for safe logging.

    Truncates and removes sensitive data before logging queries.
    This is a security measure to prevent sensitive data leaks in logs.

    Args:
        query: SQL query to sanitize
        max_length: Maximum length for logged query

    Returns:
        Sanitized query safe for logging
    """
    if not query:
        return ""

    # Truncate long queries
    if len(query) > max_length:
        query = query[:max_length] + "... (truncated)"

    # Remove potential sensitive patterns (basic example)
    # In production, you might want more sophisticated filtering
    query = re.sub(r"password\s*=\s*'[^']*'", "password='***'", query, flags=re.IGNORECASE)
    query = re.sub(r"token\s*=\s*'[^']*'", "token='***'", query, flags=re.IGNORECASE)

    return query
