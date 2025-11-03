"""
Response Models

Pydantic models for API responses.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class BaseResponse(BaseModel):
    """Base response model for all API responses."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "message": "Operation completed successfully"
                }
            ]
        }
    )

    success: bool = Field(
        ...,
        description="Whether the operation was successful"
    )
    message: Optional[str] = Field(
        default=None,
        description="Human-readable message"
    )


class ErrorResponse(BaseModel):
    """Error response model."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": "ValidationError",
                    "message": "Invalid query format",
                    "details": {"field": "query_text"}
                }
            ]
        }
    )

    error: str = Field(
        ...,
        description="Error type"
    )
    message: str = Field(
        ...,
        description="Error message"
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )


class HealthResponse(BaseResponse):
    """Health check response."""

    version: str = Field(
        ...,
        description="Server version"
    )
    status: str = Field(
        default="ok",
        description="Server status"
    )


class LogEntry(BaseModel):
    """Single log entry model."""

    timestamp: Optional[str] = None
    level: Optional[str] = None
    message: Optional[str] = None
    source: Optional[Dict[str, Any]] = None


class SearchLogsResponse(BaseResponse):
    """Response model for search_logs endpoint."""

    total_hits: int = Field(
        ...,
        description="Total number of matching logs"
    )
    logs: List[Dict[str, Any]] = Field(
        ...,
        description="List of log entries"
    )
    took: Optional[int] = Field(
        default=None,
        description="Time taken for search in milliseconds"
    )
    timed_out: bool = Field(
        default=False,
        description="Whether the search timed out"
    )


class SessionInfo(BaseModel):
    """Session ID extraction information."""

    session_id: Optional[str] = Field(
        default=None,
        description="Extracted session ID"
    )
    status: str = Field(
        ...,
        description="Extraction status (extracted, not_found, error)"
    )
    message: Optional[str] = Field(
        default=None,
        description="Status message"
    )
    source_log: Optional[str] = Field(
        default=None,
        description="Log entry where session ID was found"
    )


class SessionExtractionResponse(BaseResponse):
    """Response model for extract_session_id endpoint."""

    order_id: str = Field(
        ...,
        description="Order ID that was searched"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Primary extracted session ID"
    )
    status: str = Field(
        ...,
        description="Overall extraction status"
    )
    extraction_attempts: List[SessionInfo] = Field(
        default_factory=list,
        description="Detailed extraction attempts"
    )
    logs_searched: int = Field(
        default=0,
        description="Number of logs searched"
    )


class IndexInfo(BaseModel):
    """Elasticsearch index information."""

    name: str = Field(
        ...,
        description="Index name or pattern"
    )
    doc_count: Optional[int] = Field(
        default=None,
        description="Number of documents in index"
    )
    storage_size: Optional[str] = Field(
        default=None,
        description="Storage size of index"
    )


class IndexDiscoveryResponse(BaseResponse):
    """Response model for discover_indexes endpoint."""

    indexes: List[str] = Field(
        ...,
        description="List of available index patterns"
    )
    current_index: Optional[str] = Field(
        default=None,
        description="Currently selected index"
    )


class ConfigUpdateResponse(BaseResponse):
    """Response model for set_config endpoint."""

    key_path: str = Field(
        ...,
        description="Configuration key that was updated"
    )
    value: Any = Field(
        ...,
        description="New value"
    )
    previous_value: Optional[Any] = Field(
        default=None,
        description="Previous value (if any)"
    )


class AnalysisResult(BaseModel):
    """Log analysis result."""

    metric: str = Field(
        ...,
        description="Metric name"
    )
    value: Any = Field(
        ...,
        description="Metric value"
    )
    count: Optional[int] = Field(
        default=None,
        description="Count for this metric"
    )


class AnalyzeLogsResponse(BaseResponse):
    """Response model for analyze_logs endpoint."""

    time_range: str = Field(
        ...,
        description="Time range analyzed"
    )
    total_logs: int = Field(
        ...,
        description="Total number of logs analyzed"
    )
    analysis: List[AnalysisResult] = Field(
        default_factory=list,
        description="Analysis results"
    )
    aggregations: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw aggregation data"
    )


class ErrorInfo(BaseModel):
    """Error log information."""

    timestamp: Optional[str] = None
    level: str = Field(default="ERROR")
    message: Optional[str] = None
    stack_trace: Optional[str] = None
    service: Optional[str] = None
    source: Optional[Dict[str, Any]] = None


class ExtractErrorsResponse(BaseResponse):
    """Response model for extract_errors endpoint."""

    time_range: str = Field(
        ...,
        description="Time range searched"
    )
    total_errors: int = Field(
        ...,
        description="Total number of errors found"
    )
    errors: List[ErrorInfo] = Field(
        ...,
        description="List of error entries"
    )


class PeriscopeStreamInfo(BaseModel):
    """Periscope stream information."""

    name: str = Field(
        ...,
        description="Stream name"
    )
    doc_count: Optional[int] = Field(
        default=None,
        description="Number of documents"
    )
    time_range: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Time range of data"
    )


class PeriscopeStreamsResponse(BaseResponse):
    """Response model for get_periscope_streams endpoint."""

    streams: List[PeriscopeStreamInfo] = Field(
        ...,
        description="List of available streams"
    )
    org_identifier: str = Field(
        ...,
        description="Organization identifier"
    )


class PeriscopeFieldInfo(BaseModel):
    """Periscope field information."""

    name: str = Field(
        ...,
        description="Field name"
    )
    type: str = Field(
        ...,
        description="Field data type"
    )


class PeriscopeSchemaResponse(BaseResponse):
    """Response model for get_periscope_stream_schema endpoint."""

    stream_name: str = Field(
        ...,
        description="Stream name"
    )
    fields: List[PeriscopeFieldInfo] = Field(
        ...,
        description="List of fields in stream"
    )
    stats: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Stream statistics"
    )


class PeriscopeSearchResponse(BaseResponse):
    """Response model for search_periscope_logs endpoint."""

    total_hits: int = Field(
        ...,
        description="Total number of matching logs"
    )
    logs: List[Dict[str, Any]] = Field(
        ...,
        description="List of log entries"
    )
    query: str = Field(
        ...,
        description="SQL query executed"
    )
    execution_time_ms: Optional[int] = Field(
        default=None,
        description="Query execution time in milliseconds"
    )
