"""
Logging Configuration Module

Provides structured logging setup with proper configuration
for different environments and use cases.
"""

import sys
from loguru import logger
from typing import Optional


def setup_logging(
    level: str = "INFO",
    format_string: Optional[str] = None,
    enable_file_logging: bool = False,
    log_file_path: str = "kibana_mcp_server.log",
    rotation: str = "10 MB",
    retention: str = "30 days"
) -> None:
    """
    Configure structured logging with loguru.

    Sets up console and optional file logging with appropriate formatting
    and rotation.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string (None for default)
        enable_file_logging: Whether to enable file logging
        log_file_path: Path to log file (if file logging enabled)
        rotation: File rotation policy (e.g., "10 MB", "1 day")
        retention: Log retention policy (e.g., "30 days", "1 week")

    Example:
        >>> setup_logging(level="DEBUG", enable_file_logging=True)
        >>> logger.info("Server started")
    """
    # Remove default logger
    logger.remove()

    # Default format with structured information
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

    # Add console logger
    logger.add(
        sys.stderr,
        format=format_string,
        level=level.upper(),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Add file logger if enabled
    if enable_file_logging:
        # File logger with JSON format for structured logging
        logger.add(
            log_file_path,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            level=level.upper(),
            rotation=rotation,
            retention=retention,
            compression="zip",  # Compress rotated logs
            backtrace=True,
            diagnose=True,
        )

        logger.info(f"File logging enabled: {log_file_path}")

    logger.info(f"Logging configured with level: {level.upper()}")


def configure_logging_from_config(config_obj) -> None:
    """
    Configure logging from configuration object.

    Args:
        config_obj: Configuration object with logging settings

    Example:
        >>> from src.core.config import config
        >>> configure_logging_from_config(config)
    """
    log_level = config_obj.get('mcp_server.log_level', default='INFO', expected_type=str)

    # Check if file logging is enabled in config
    enable_file = config_obj.get('logging.enable_file', default=False, expected_type=bool)
    log_file = config_obj.get('logging.file_path', default='kibana_mcp_server.log', expected_type=str)
    rotation = config_obj.get('logging.rotation', default='10 MB', expected_type=str)
    retention = config_obj.get('logging.retention', default='30 days', expected_type=str)

    setup_logging(
        level=log_level,
        enable_file_logging=enable_file,
        log_file_path=log_file,
        rotation=rotation,
        retention=retention
    )


def add_request_context(request_id: str) -> logger:
    """
    Add request context to logger.

    Creates a logger bound with request ID for tracing.

    Args:
        request_id: Unique request identifier

    Returns:
        Logger with request context

    Example:
        >>> request_logger = add_request_context("req-123")
        >>> request_logger.info("Processing request")
        # Logs: ... | request_id=req-123 | Processing request
    """
    return logger.bind(request_id=request_id)


def add_user_context(user_id: str) -> logger:
    """
    Add user context to logger.

    Creates a logger bound with user ID for audit trails.

    Args:
        user_id: User identifier

    Returns:
        Logger with user context

    Example:
        >>> user_logger = add_user_context("user-456")
        >>> user_logger.info("User action performed")
    """
    return logger.bind(user_id=user_id)
