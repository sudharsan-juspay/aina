"""
Unit tests for authentication manager.

Tests thread-safe token management and expiration handling.
"""

import pytest
import time
from src.security.auth import AuthManager, TokenInfo


class TestTokenInfo:
    """Tests for TokenInfo dataclass."""

    def test_token_info_creation(self):
        """Test TokenInfo creation with default values."""
        token_info = TokenInfo(token="test-token-123")

        assert token_info.token == "test-token-123"
        assert token_info.context == "default"
        assert token_info.created_at > 0

    def test_token_info_with_expiry(self):
        """Test TokenInfo with expiration."""
        expires_at = time.time() + 3600
        token_info = TokenInfo(
            token="test-token",
            expires_at=expires_at,
            context="test"
        )

        assert not token_info.is_expired()
        assert token_info.time_until_expiry() > 0

    def test_token_info_expired(self):
        """Test expired token detection."""
        expires_at = time.time() - 1  # Expired 1 second ago
        token_info = TokenInfo(token="test-token", expires_at=expires_at)

        assert token_info.is_expired()
        assert token_info.time_until_expiry() == 0.0

    def test_token_info_never_expires(self):
        """Test token with no expiration."""
        token_info = TokenInfo(token="test-token", expires_at=0.0)

        assert not token_info.is_expired()
        assert token_info.time_until_expiry() == -1.0


class TestAuthManager:
    """Tests for AuthManager class."""

    def test_set_and_get_token(self):
        """Test basic token set and get operations."""
        auth = AuthManager()

        auth.set_token("test-context", "test-token-123")
        token = auth.get_token("test-context")

        assert token == "test-token-123"

    def test_get_nonexistent_token(self):
        """Test getting token that doesn't exist."""
        auth = AuthManager()
        token = auth.get_token("nonexistent")

        assert token is None

    def test_token_expiration(self):
        """Test token expiration and automatic removal."""
        auth = AuthManager()

        # Set token with 1 second TTL
        auth.set_token("test", "token123", ttl=1.0)

        # Should be available immediately
        assert auth.get_token("test") == "token123"

        # Wait for expiration
        time.sleep(1.1)

        # Should be None after expiration
        assert auth.get_token("test") is None

    def test_validate_token_success(self):
        """Test successful token validation."""
        auth = AuthManager()
        auth.set_token("test", "correct-token")

        assert auth.validate_token("test", "correct-token") is True

    def test_validate_token_failure(self):
        """Test failed token validation."""
        auth = AuthManager()
        auth.set_token("test", "correct-token")

        assert auth.validate_token("test", "wrong-token") is False

    def test_validate_nonexistent_token(self):
        """Test validating token for nonexistent context."""
        auth = AuthManager()

        assert auth.validate_token("nonexistent", "any-token") is False

    def test_rotate_token(self):
        """Test token rotation."""
        auth = AuthManager()

        auth.set_token("test", "old-token")
        assert auth.get_token("test") == "old-token"

        auth.rotate_token("test", "new-token")
        assert auth.get_token("test") == "new-token"

        # Old token should not work
        assert auth.validate_token("test", "old-token") is False

    def test_remove_token(self):
        """Test token removal."""
        auth = AuthManager()

        auth.set_token("test", "token123")
        assert auth.get_token("test") is not None

        removed = auth.remove_token("test")
        assert removed is True
        assert auth.get_token("test") is None

    def test_remove_nonexistent_token(self):
        """Test removing token that doesn't exist."""
        auth = AuthManager()

        removed = auth.remove_token("nonexistent")
        assert removed is False

    def test_has_token(self):
        """Test checking if token exists."""
        auth = AuthManager()

        assert auth.has_token("test") is False

        auth.set_token("test", "token123")
        assert auth.has_token("test") is True

        auth.remove_token("test")
        assert auth.has_token("test") is False

    def test_get_all_contexts(self):
        """Test getting all contexts with tokens."""
        auth = AuthManager()

        auth.set_token("context1", "token1")
        auth.set_token("context2", "token2")
        auth.set_token("context3", "token3")

        contexts = auth.get_all_contexts()

        assert len(contexts) == 3
        assert "context1" in contexts
        assert "context2" in contexts
        assert "context3" in contexts

    def test_cleanup_expired_tokens(self):
        """Test cleanup of expired tokens."""
        auth = AuthManager()

        # Set some tokens with different expiration times
        auth.set_token("persistent", "token1")  # Never expires
        auth.set_token("short", "token2", ttl=0.5)  # Expires in 0.5s
        auth.set_token("medium", "token3", ttl=10.0)  # Expires in 10s

        # Wait for short-lived token to expire
        time.sleep(0.6)

        # Clean up expired tokens
        removed = auth.cleanup_expired_tokens()

        assert removed == 1
        assert auth.has_token("persistent")
        assert not auth.has_token("short")
        assert auth.has_token("medium")

    def test_empty_token_raises_error(self):
        """Test that setting empty token raises ValueError."""
        auth = AuthManager()

        with pytest.raises(ValueError) as exc_info:
            auth.set_token("test", "")
        assert "Token cannot be empty" in str(exc_info.value)

    def test_empty_context_raises_error(self):
        """Test that setting token with empty context raises ValueError."""
        auth = AuthManager()

        with pytest.raises(ValueError) as exc_info:
            auth.set_token("", "token123")
        assert "Context cannot be empty" in str(exc_info.value)

    def test_thread_safety(self):
        """Test thread safety of AuthManager.

        This is a basic test - in production, more thorough
        concurrent testing would be needed.
        """
        import threading

        auth = AuthManager()
        errors = []

        def set_tokens(thread_id):
            try:
                for i in range(100):
                    auth.set_token(f"thread-{thread_id}-{i}", f"token-{i}")
            except Exception as e:
                errors.append(e)

        def get_tokens(thread_id):
            try:
                for i in range(100):
                    auth.get_token(f"thread-{thread_id}-{i}")
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = []
        for i in range(5):
            t1 = threading.Thread(target=set_tokens, args=(i,))
            t2 = threading.Thread(target=get_tokens, args=(i,))
            threads.extend([t1, t2])

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0
