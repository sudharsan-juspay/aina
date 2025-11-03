"""
API Module

HTTP API layer with FastAPI and MCP support.
"""

from .app import create_app

__all__ = ["create_app"]
