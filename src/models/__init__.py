"""
Models Module

Pydantic models for request/response validation and serialization.
"""

from .requests import (
    SearchLogsRequest,
    GetRecentLogsRequest,
    AnalyzeLogsRequest,
    ExtractErrorsRequest,
    ExtractSessionIdRequest,
    SetAuthTokenRequest,
    SetCurrentIndexRequest,
    SetConfigRequest,
    PeriscopeSearchRequest,
    PeriscopeErrorsRequest,
)

from .responses import (
    BaseResponse,
    HealthResponse,
    SearchLogsResponse,
    ErrorResponse,
    SessionExtractionResponse,
    IndexDiscoveryResponse,
    ConfigUpdateResponse,
)

__all__ = [
    # Requests
    "SearchLogsRequest",
    "GetRecentLogsRequest",
    "AnalyzeLogsRequest",
    "ExtractErrorsRequest",
    "ExtractSessionIdRequest",
    "SetAuthTokenRequest",
    "SetCurrentIndexRequest",
    "SetConfigRequest",
    "PeriscopeSearchRequest",
    "PeriscopeErrorsRequest",
    # Responses
    "BaseResponse",
    "HealthResponse",
    "SearchLogsResponse",
    "ErrorResponse",
    "SessionExtractionResponse",
    "IndexDiscoveryResponse",
    "ConfigUpdateResponse",
]
