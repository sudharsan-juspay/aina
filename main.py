#!/usr/bin/env python3
# Copyright (c) 2025 [Harivatsa G A]. All rights reserved.
# This work is licensed under CC BY-NC-ND 4.0.
# https://creativecommons.org/licenses/by-nc-nd/4.0/
# Attribution required. Commercial use and modifications prohibited.

"""
Kibana MCP Server - Main Entry Point
"""

import os
import sys
import argparse
import uvicorn
from loguru import logger

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.config import config
from src.core.logging_config import configure_logging_from_config
from src.core.constants import APP_NAME, APP_VERSION
from src.api.app import create_app


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{APP_VERSION} - Kibana MCP Server"
    )

    parser.add_argument(
        '--host',
        type=str,
        default=None,
        help='Host to bind to (default: from config)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Port to bind to (default: from config)'
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file'
    )

    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default=None,
        help='Logging level (default: from config)'
    )

    parser.add_argument(
        '--reload',
        action='store_true',
        help='Enable auto-reload for development'
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Configure logging
    configure_logging_from_config(config)

    # Override log level if specified
    if args.log_level:
        from src.core.logging_config import setup_logging
        setup_logging(level=args.log_level)

    # Get host and port from args or config
    host = args.host or config.get('mcp_server.host', default='0.0.0.0')
    port = args.port or config.get('mcp_server.port', default=8000, expected_type=int)

    # Log startup info
    logger.info("=" * 60)
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    logger.info("=" * 60)
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"Config: {args.config}")
    logger.info(f"Environment: {config.env}")
    logger.info("=" * 60)

    # Create FastAPI app
    app = create_app()

    # Run server
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=args.reload,
            log_level="info" if args.log_level is None else args.log_level.lower()
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
