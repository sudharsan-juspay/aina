"""
Unit tests for security sanitizers.

Tests SQL injection prevention and input sanitization.
"""

import pytest
from src.security.sanitizers import (
    sanitize_stream_name,
    sanitize_error_code_pattern,
    sanitize_sql_identifier,
    ValidationError,
    VALID_STREAM_NAMES,
)


class TestSanitizeStreamName:
    """Tests for sanitize_stream_name function."""

    def test_valid_stream_names(self):
        """Test that all valid stream names pass validation."""
        for stream in VALID_STREAM_NAMES:
            result = sanitize_stream_name(stream)
            assert result == stream

    def test_invalid_stream_name(self):
        """Test that invalid stream names raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_stream_name("invalid_stream")
        assert "Invalid stream name" in str(exc_info.value)

    def test_sql_injection_attempt(self):
        """Test that SQL injection attempts are blocked."""
        malicious_inputs = [
            "envoy_logs'; DROP TABLE logs; --",
            "envoy_logs' OR '1'='1",
            "'; DELETE FROM logs; --",
            "../../../etc/passwd",
        ]

        for malicious in malicious_inputs:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_stream_name(malicious)
            assert "Invalid stream name" in str(exc_info.value)

    def test_empty_stream_name(self):
        """Test that empty stream name raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_stream_name("")
        assert "cannot be empty" in str(exc_info.value)


class TestSanitizeErrorCodePattern:
    """Tests for sanitize_error_code_pattern function."""

    def test_valid_patterns(self):
        """Test valid error code patterns."""
        valid_patterns = ["5%", "4%", "404", "500", "5%%"]

        for pattern in valid_patterns:
            result = sanitize_error_code_pattern(pattern)
            assert result == pattern

    def test_sql_injection_attempts(self):
        """Test that SQL injection attempts are blocked."""
        malicious_patterns = [
            "5%' OR '1'='1",
            "404'; DROP TABLE logs; --",
            "5% UNION SELECT * FROM users",
            "500' AND 1=1--",
        ]

        for malicious in malicious_patterns:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_error_code_pattern(malicious)
            assert "Invalid error code pattern" in str(exc_info.value)

    def test_invalid_characters(self):
        """Test that patterns with invalid characters are rejected."""
        invalid_patterns = [
            "abc",  # Letters not allowed
            "5%-",  # Hyphen not allowed
            "4 %",  # Space not allowed
            "500;", # Semicolon not allowed
        ]

        for invalid in invalid_patterns:
            with pytest.raises(ValidationError):
                sanitize_error_code_pattern(invalid)

    def test_pattern_too_long(self):
        """Test that excessively long patterns are rejected."""
        long_pattern = "5" * 100
        with pytest.raises(ValidationError) as exc_info:
            sanitize_error_code_pattern(long_pattern)
        assert "too long" in str(exc_info.value)

    def test_empty_pattern(self):
        """Test that empty pattern raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_error_code_pattern("")
        assert "cannot be empty" in str(exc_info.value)


class TestSanitizeSQLIdentifier:
    """Tests for sanitize_sql_identifier function."""

    def test_valid_identifiers(self):
        """Test valid SQL identifiers."""
        valid_identifiers = [
            "column_name",
            "table-name",
            "field123",
            "my_table_name_123",
        ]

        for identifier in valid_identifiers:
            result = sanitize_sql_identifier(identifier)
            assert result == identifier

    def test_sql_injection_attempts(self):
        """Test that SQL injection attempts are blocked."""
        malicious_identifiers = [
            "column'; DROP TABLE users; --",
            "table OR 1=1",
            "field; DELETE FROM logs",
            "name' UNION SELECT",
        ]

        for malicious in malicious_identifiers:
            with pytest.raises(ValidationError) as exc_info:
                sanitize_sql_identifier(malicious)
            assert "Invalid SQL identifier" in str(exc_info.value)

    def test_invalid_characters(self):
        """Test that identifiers with invalid characters are rejected."""
        invalid_identifiers = [
            "column name",  # Space not allowed
            "table.name",   # Dot not allowed
            "field@host",   # @ not allowed
            "name$value",   # $ not allowed
        ]

        for invalid in invalid_identifiers:
            with pytest.raises(ValidationError):
                sanitize_sql_identifier(invalid)

    def test_identifier_too_long(self):
        """Test that excessively long identifiers are rejected."""
        long_identifier = "a" * 1000
        with pytest.raises(ValidationError) as exc_info:
            sanitize_sql_identifier(long_identifier)
        assert "too long" in str(exc_info.value)

    def test_custom_max_length(self):
        """Test custom max_length parameter."""
        identifier = "a" * 50

        # Should pass with max_length=100
        result = sanitize_sql_identifier(identifier, max_length=100)
        assert result == identifier

        # Should fail with max_length=10
        with pytest.raises(ValidationError):
            sanitize_sql_identifier(identifier, max_length=10)

    def test_empty_identifier(self):
        """Test that empty identifier raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_sql_identifier("")
        assert "cannot be empty" in str(exc_info.value)
