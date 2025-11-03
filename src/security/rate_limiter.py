"""
Rate Limiting Module

Provides token bucket rate limiting to prevent API abuse and DoS attacks.

This module implements a thread-safe token bucket algorithm that allows
configurable rate limiting for different endpoints.
"""

import time
from threading import Lock
from collections import defaultdict
from typing import Dict, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class BucketState:
    """
    State of a token bucket for rate limiting.

    Attributes:
        tokens: Current number of available tokens
        last_update: Timestamp of last token refill
    """
    tokens: float
    last_update: float


class RateLimiter:
    """
    Token bucket rate limiter.

    Implements the token bucket algorithm for rate limiting:
    - Tokens are added to the bucket at a constant rate
    - Each request consumes one token
    - If no tokens available, request is rejected
    - Thread-safe for concurrent use

    Example:
        >>> limiter = RateLimiter(rate=100, per=60)  # 100 requests per minute
        >>> if limiter.is_allowed('user123'):
        ...     # Process request
        ... else:
        ...     # Reject with 429 Too Many Requests
    """

    def __init__(self, rate: int, per: int = 60):
        """
        Initialize rate limiter.

        Args:
            rate: Number of requests allowed
            per: Time window in seconds

        Example:
            >>> limiter = RateLimiter(rate=100, per=60)  # 100 req/min
            >>> limiter = RateLimiter(rate=10, per=1)    # 10 req/sec
        """
        if rate <= 0:
            raise ValueError("Rate must be positive")
        if per <= 0:
            raise ValueError("Time window must be positive")

        self.rate = rate
        self.per = per
        self._buckets: Dict[str, BucketState] = defaultdict(
            lambda: BucketState(tokens=float(rate), last_update=time.time())
        )
        self._lock = Lock()

        logger.info(f"Rate limiter initialized: {rate} requests per {per} seconds")

    def is_allowed(self, key: str, cost: float = 1.0) -> bool:
        """
        Check if request is allowed under rate limit.

        Uses token bucket algorithm:
        1. Calculate tokens to add since last check
        2. Add tokens (up to bucket capacity)
        3. Check if enough tokens for this request
        4. If yes, deduct tokens and allow
        5. If no, reject

        Args:
            key: Identifier for rate limiting (e.g., user ID, IP address)
            cost: Token cost for this request (default: 1.0)

        Returns:
            True if request allowed, False if rate limit exceeded

        Example:
            >>> if limiter.is_allowed('user123'):
            ...     # Process request
            >>> if limiter.is_allowed('user456', cost=5.0):
            ...     # Expensive operation costs more tokens
        """
        with self._lock:
            bucket = self._buckets[key]
            now = time.time()

            # Calculate tokens to add based on elapsed time
            elapsed = now - bucket.last_update
            tokens_to_add = elapsed * (self.rate / self.per)

            # Refill bucket (up to max capacity)
            bucket.tokens = min(self.rate, bucket.tokens + tokens_to_add)
            bucket.last_update = now

            # Check if enough tokens available
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True

            # Rate limit exceeded
            logger.debug(
                f"Rate limit exceeded for key '{key}': "
                f"{bucket.tokens:.2f} tokens available, {cost} required"
            )
            return False

    def get_wait_time(self, key: str, cost: float = 1.0) -> float:
        """
        Get time (in seconds) until request would be allowed.

        Useful for implementing retry-after headers.

        Args:
            key: Identifier for rate limiting
            cost: Token cost for the request

        Returns:
            Seconds to wait (0 if request would be allowed now)

        Example:
            >>> wait = limiter.get_wait_time('user123')
            >>> if wait > 0:
            ...     # Return Retry-After: {wait} header
        """
        with self._lock:
            bucket = self._buckets[key]
            now = time.time()

            # Calculate current tokens
            elapsed = now - bucket.last_update
            tokens_to_add = elapsed * (self.rate / self.per)
            current_tokens = min(self.rate, bucket.tokens + tokens_to_add)

            # If enough tokens, no wait needed
            if current_tokens >= cost:
                return 0.0

            # Calculate wait time for required tokens
            tokens_needed = cost - current_tokens
            wait_seconds = tokens_needed * (self.per / self.rate)

            return wait_seconds

    def reset(self, key: str) -> None:
        """
        Reset rate limit for a specific key.

        Useful for testing or manual override.

        Args:
            key: Identifier to reset

        Example:
            >>> limiter.reset('user123')  # Clear rate limit for user
        """
        with self._lock:
            if key in self._buckets:
                del self._buckets[key]
                logger.info(f"Rate limit reset for key '{key}'")

    def get_stats(self, key: str) -> Tuple[float, float]:
        """
        Get current rate limit statistics for a key.

        Args:
            key: Identifier to check

        Returns:
            Tuple of (available_tokens, tokens_per_second)

        Example:
            >>> available, rate = limiter.get_stats('user123')
            >>> print(f"Available: {available:.1f}, Rate: {rate:.1f}/s")
        """
        with self._lock:
            bucket = self._buckets[key]
            now = time.time()

            # Calculate current tokens
            elapsed = now - bucket.last_update
            tokens_to_add = elapsed * (self.rate / self.per)
            current_tokens = min(self.rate, bucket.tokens + tokens_to_add)

            tokens_per_second = self.rate / self.per

            return (current_tokens, tokens_per_second)

    def cleanup_old_buckets(self, max_age: int = 3600) -> int:
        """
        Remove buckets for keys that haven't been accessed recently.

        Prevents memory growth from tracking too many unique keys.

        Args:
            max_age: Maximum age in seconds for inactive buckets

        Returns:
            Number of buckets removed

        Example:
            >>> removed = limiter.cleanup_old_buckets(max_age=3600)
            >>> print(f"Cleaned up {removed} old buckets")
        """
        with self._lock:
            now = time.time()
            old_keys = [
                key for key, bucket in self._buckets.items()
                if now - bucket.last_update > max_age
            ]

            for key in old_keys:
                del self._buckets[key]

            if old_keys:
                logger.info(f"Cleaned up {len(old_keys)} inactive rate limit buckets")

            return len(old_keys)


# Global rate limiter instances
# These replace the need for manual rate limiting in endpoint code

# Search endpoint rate limiter: 100 requests per minute per user
search_rate_limiter = RateLimiter(rate=100, per=60)

# Authentication endpoint rate limiter: 10 requests per minute per user
# More restrictive to prevent brute force attacks
auth_rate_limiter = RateLimiter(rate=10, per=60)

# API configuration endpoint rate limiter: 20 requests per minute per user
config_rate_limiter = RateLimiter(rate=20, per=60)


def get_client_identifier(request) -> str:
    """
    Extract client identifier from request for rate limiting.

    Priority:
    1. User ID from authentication (if available)
    2. IP address from request

    Args:
        request: FastAPI request object

    Returns:
        Client identifier string

    Example:
        >>> client_id = get_client_identifier(request)
        >>> if not search_rate_limiter.is_allowed(client_id):
        ...     raise HTTPException(status_code=429)
    """
    # Try to get user ID from request state (set by auth middleware)
    if hasattr(request.state, 'user_id'):
        return f"user:{request.state.user_id}"

    # Fall back to IP address
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"
