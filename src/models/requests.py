"""
Request Models

Pydantic models for API request validation.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime

from src.security.validators import QueryValidator


class SearchLogsRequest(BaseModel):
    """Request model for search_logs endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query_text: str = Field(
        ...,
        description="KQL query text (must include session_id)",
        min_length=1,
        max_length=5000,
        examples=['"{session_id} AND error"', '{session_id} AND payment']
    )
    max_results: int = Field(
        default=100,
        description="Maximum number of results to return",
        ge=1,
        le=10000
    )
    start_time: Optional[str] = Field(
        default=None,
        description="Start time in ISO format or relative (e.g., '24h')"
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End time in ISO format"
    )
    levels: Optional[List[str]] = Field(
        default=None,
        description="Log levels to filter (ERROR, WARN, INFO, DEBUG)"
    )
    include_fields: Optional[List[str]] = Field(
        default=None,
        description="Fields to include in results"
    )
    exclude_fields: Optional[List[str]] = Field(
        default=None,
        description="Fields to exclude from results"
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Field to sort by (timestamp, @timestamp, start_time)"
    )
    sort_order: str = Field(
        default="desc",
        description="Sort order: asc or desc"
    )

    @field_validator('query_text')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate KQL query for security threats."""
        return QueryValidator.validate_kql_query(v)

    @field_validator('sort_order')
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        """Validate sort order."""
        if v.lower() not in ['asc', 'desc']:
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return v.lower()

    @field_validator('levels')
    @classmethod
    def validate_levels(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate log levels."""
        if v:
            valid_levels = {'ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE'}
            for level in v:
                if level.upper() not in valid_levels:
                    raise ValueError(f"Invalid log level: {level}")
            return [level.upper() for level in v]
        return v

    @field_validator('include_fields', 'exclude_fields')
    @classmethod
    def validate_fields(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate field names."""
        if v:
            for field in v:
                QueryValidator.validate_field_name(field)
        return v


class GetRecentLogsRequest(BaseModel):
    """Request model for get_recent_logs endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    count: int = Field(
        default=100,
        description="Number of recent logs to retrieve",
        ge=1,
        le=1000
    )
    level: Optional[str] = Field(
        default=None,
        description="Filter by log level"
    )
    index_pattern: Optional[str] = Field(
        default=None,
        description="Elasticsearch index pattern"
    )

    @field_validator('level')
    @classmethod
    def validate_level(cls, v: Optional[str]) -> Optional[str]:
        """Validate log level."""
        if v:
            valid_levels = {'ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE'}
            if v.upper() not in valid_levels:
                raise ValueError(f"Invalid log level: {v}")
            return v.upper()
        return v

    @field_validator('index_pattern')
    @classmethod
    def validate_index(cls, v: Optional[str]) -> Optional[str]:
        """Validate index pattern."""
        if v:
            return QueryValidator.validate_index_pattern(v)
        return v


class AnalyzeLogsRequest(BaseModel):
    """Request model for analyze_logs endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    time_range: str = Field(
        default="24h",
        description="Time range for analysis (e.g., '1h', '24h', '7d')"
    )
    group_by: Optional[str] = Field(
        default=None,
        description="Field to group by (e.g., 'level', 'service')"
    )
    index_pattern: Optional[str] = Field(
        default=None,
        description="Elasticsearch index pattern"
    )

    @field_validator('time_range')
    @classmethod
    def validate_time_range(cls, v: str) -> str:
        """Validate time range format."""
        return QueryValidator.validate_time_range(v)


class ExtractErrorsRequest(BaseModel):
    """Request model for extract_errors endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    hours: int = Field(
        default=24,
        description="Number of hours to look back",
        ge=1,
        le=168  # Max 7 days
    )
    include_stack_traces: bool = Field(
        default=True,
        description="Include stack traces in results"
    )
    limit: int = Field(
        default=100,
        description="Maximum number of errors to return",
        ge=1,
        le=1000
    )
    index_pattern: Optional[str] = Field(
        default=None,
        description="Elasticsearch index pattern"
    )


class ExtractSessionIdRequest(BaseModel):
    """Request model for extract_session_id endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    order_id: str = Field(
        ...,
        description="Order ID to extract session ID from",
        min_length=1,
        max_length=100
    )

    @field_validator('order_id')
    @classmethod
    def validate_order_id(cls, v: str) -> str:
        """Validate order ID format."""
        return QueryValidator.validate_order_id(v)


class SetAuthTokenRequest(BaseModel):
    """Request model for set_auth_token endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    auth_token: str = Field(
        ...,
        description="Authentication token",
        min_length=1
    )
    ttl: Optional[int] = Field(
        default=None,
        description="Time to live in seconds (0 = never expires)",
        ge=0
    )


class SetCurrentIndexRequest(BaseModel):
    """Request model for set_current_index endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    index_pattern: str = Field(
        ...,
        description="Elasticsearch index pattern to use",
        min_length=1,
        max_length=100
    )

    @field_validator('index_pattern')
    @classmethod
    def validate_index(cls, v: str) -> str:
        """Validate index pattern."""
        return QueryValidator.validate_index_pattern(v)


class SetConfigRequest(BaseModel):
    """Request model for set_config endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    key_path: str = Field(
        ...,
        description="Dot-separated config key path (e.g., 'elasticsearch.host')",
        min_length=1,
        max_length=200
    )
    value: str | int | float | bool = Field(
        ...,
        description="Configuration value"
    )


class PeriscopeSearchRequest(BaseModel):
    """Request model for search_periscope_logs endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sql_query: str = Field(
        ...,
        description="SQL query for Periscope",
        min_length=1,
        max_length=5000
    )
    start_time: str | int = Field(
        default="24h",
        description="Start time (ISO, relative, or microseconds)"
    )
    end_time: Optional[str | int] = Field(
        default=None,
        description="End time (ISO or microseconds)"
    )
    timezone: Optional[str] = Field(
        default=None,
        description="Timezone for naive datetime (e.g., 'Asia/Kolkata')"
    )
    max_results: int = Field(
        default=50,
        description="Maximum number of results",
        ge=1,
        le=10000
    )
    org_identifier: str = Field(
        default="default",
        description="Organization identifier"
    )


class PeriscopeErrorsRequest(BaseModel):
    """Request model for search_periscope_errors endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    hours: int = Field(
        default=24,
        description="Number of hours to look back",
        ge=1,
        le=168
    )
    stream: str = Field(
        default="envoy_logs",
        description="Periscope stream name"
    )
    error_codes: Optional[str] = Field(
        default=None,
        description="Error code pattern (e.g., '5%' for 5xx errors)"
    )
    org_identifier: str = Field(
        default="default",
        description="Organization identifier"
    )
    timezone: Optional[str] = Field(
        default="Asia/Kolkata",
        description="Timezone for relative time calculation (e.g., 'Asia/Kolkata', 'UTC')"
    )

    @field_validator('stream')
    @classmethod
    def validate_stream(cls, v: str) -> str:
        """Validate stream name."""
        from src.security.sanitizers import sanitize_stream_name
        return sanitize_stream_name(v)

    @field_validator('error_codes')
    @classmethod
    def validate_error_codes(cls, v: Optional[str]) -> Optional[str]:
        """Validate error code pattern."""
        if v:
            from src.security.sanitizers import sanitize_error_code_pattern
            return sanitize_error_code_pattern(v)
        return v


# Memory Board Models

class CreateBoardRequest(BaseModel):
    """Request model for creating a new memory board."""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ...,
        description="A descriptive name for the memory board/investigation.",
        min_length=3,
        max_length=150
    )


class AddFindingRequest(BaseModel):
    """Request model for adding a finding to a memory board."""
    timestamp: datetime = Field(
        ...,
        description="The timestamp of the event related to the finding."
    )
    finding: str = Field(
        ...,
        description="A concise, human-readable summary of the discovery.",
        min_length=3,
        max_length=1000
    )
    source_log: Dict[str, Any] = Field(
        ...,
        description="The raw log entry that led to this finding."
    )
    attention_weight: int = Field(
        ...,
        description="The AI's assessment of how critical this finding is (1-10).",
        ge=1,
        le=10
    )
    implication: str = Field(
        ...,
        description="The AI's deduction based on the finding.",
        min_length=3,
        max_length=1000
    )
