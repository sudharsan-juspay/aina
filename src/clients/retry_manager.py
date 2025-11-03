"""
Retry Manager Module

Implements exponential backoff retry logic for HTTP requests.
"""

import asyncio
import random
from typing import Callable, TypeVar, Optional, Set
from dataclasses import dataclass
from loguru import logger

from src.core.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_INITIAL_BACKOFF,
    DEFAULT_MAX_BACKOFF,
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_JITTER_FACTOR,
)
from src.core.exceptions import TimeoutError as MCPTimeoutError


T = TypeVar('T')


@dataclass
class RetryConfig:
    """
    Configuration for retry logic.

    Attributes:
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff delay in seconds
        max_backoff: Maximum backoff delay in seconds
        backoff_multiplier: Multiplier for exponential backoff
        jitter_factor: Jitter factor (0.0-1.0) to add randomness
        retryable_status_codes: HTTP status codes that should trigger retry
        non_retryable_status_codes: HTTP status codes that should never retry
    """
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF
    max_backoff: float = DEFAULT_MAX_BACKOFF
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER
    jitter_factor: float = DEFAULT_JITTER_FACTOR
    retryable_status_codes: Set[int] = None
    non_retryable_status_codes: Set[int] = None

    def __post_init__(self):
        """Set default status codes if not provided."""
        if self.retryable_status_codes is None:
            # Retry on server errors and rate limiting
            self.retryable_status_codes = {408, 429, 500, 502, 503, 504}

        if self.non_retryable_status_codes is None:
            # Don't retry on client errors and auth failures
            self.non_retryable_status_codes = {400, 401, 403, 404}


class RetryManager:
    """
    Manages retry logic with exponential backoff.

    Features:
    - Exponential backoff with configurable multiplier
    - Jitter to prevent thundering herd
    - Configurable retryable status codes
    - Timeout handling
    - Async/await support

    Example:
        >>> retry_manager = RetryManager()
        >>> result = await retry_manager.retry_async(
        ...     some_async_function,
        ...     arg1, arg2,
        ...     kwarg1=value1
        ... )
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        """
        Initialize retry manager.

        Args:
            config: Retry configuration (uses defaults if not provided)
        """
        self.config = config or RetryConfig()

    def calculate_backoff(self, attempt: int) -> float:
        """
        Calculate backoff delay for a retry attempt.

        Uses exponential backoff with jitter:
        delay = min(initial * multiplier^attempt, max) * (1 + jitter * random())

        Args:
            attempt: Retry attempt number (0-indexed)

        Returns:
            Backoff delay in seconds

        Example:
            >>> delay = retry_manager.calculate_backoff(2)
            >>> # Returns ~4 seconds with jitter
        """
        # Exponential backoff
        delay = self.config.initial_backoff * (self.config.backoff_multiplier ** attempt)

        # Cap at max backoff
        delay = min(delay, self.config.max_backoff)

        # Add jitter to prevent thundering herd
        jitter = delay * self.config.jitter_factor * random.random()
        delay += jitter

        return delay

    def should_retry(self, attempt: int, error: Exception, status_code: Optional[int] = None) -> bool:
        """
        Determine if operation should be retried.

        Args:
            attempt: Current attempt number (0-indexed)
            error: Exception that was raised
            status_code: HTTP status code (if applicable)

        Returns:
            True if should retry, False otherwise
        """
        # Check if we've exceeded max retries
        if attempt >= self.config.max_retries:
            return False

        # Check status code
        if status_code is not None:
            # Never retry these status codes
            if status_code in self.config.non_retryable_status_codes:
                return False

            # Always retry these status codes
            if status_code in self.config.retryable_status_codes:
                return True

        # Retry on connection errors, timeouts, etc.
        retryable_exceptions = (
            ConnectionError,
            TimeoutError,
            MCPTimeoutError,
        )

        return isinstance(error, retryable_exceptions)

    async def retry_async(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        Retry an async function with exponential backoff.

        Args:
            func: Async function to retry
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from successful function call

        Raises:
            Exception: Last exception if all retries fail

        Example:
            >>> async def fetch_data():
            ...     # Some API call that might fail
            ...     return data
            >>> result = await retry_manager.retry_async(fetch_data)
        """
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                # Try to execute the function
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                last_exception = e

                # Extract status code if it's an HTTP error
                status_code = getattr(e, 'status_code', None)

                # Check if we should retry
                if not self.should_retry(attempt, e, status_code):
                    logger.warning(
                        f"Not retrying after attempt {attempt + 1}: {type(e).__name__}: {e}"
                    )
                    raise

                # We've exhausted retries
                if attempt >= self.config.max_retries:
                    logger.error(
                        f"All {self.config.max_retries} retry attempts failed: {type(e).__name__}: {e}"
                    )
                    raise

                # Calculate backoff delay
                delay = self.calculate_backoff(attempt)

                logger.warning(
                    f"Retry attempt {attempt + 1}/{self.config.max_retries} "
                    f"after {delay:.2f}s delay: {type(e).__name__}: {e}"
                )

                # Wait before retrying
                await asyncio.sleep(delay)

        # This should never be reached, but just in case
        if last_exception:
            raise last_exception

    async def retry_with_timeout(
        self,
        func: Callable[..., T],
        timeout: float,
        *args,
        **kwargs
    ) -> T:
        """
        Retry an async function with timeout and exponential backoff.

        Args:
            func: Async function to retry
            timeout: Total timeout for all attempts in seconds
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from successful function call

        Raises:
            MCPTimeoutError: If total timeout is exceeded
            Exception: Last exception if all retries fail

        Example:
            >>> result = await retry_manager.retry_with_timeout(
            ...     fetch_data, timeout=30.0
            ... )
        """
        try:
            return await asyncio.wait_for(
                self.retry_async(func, *args, **kwargs),
                timeout=timeout
            )
        except asyncio.TimeoutError as e:
            raise MCPTimeoutError(
                f"Operation timed out after {timeout} seconds",
                timeout_seconds=timeout
            ) from e


# Create default retry manager instance
default_retry_manager = RetryManager()
