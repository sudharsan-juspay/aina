"""
HTTP Routes

RESTful API endpoint definitions.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from loguru import logger

from src.models.requests import (
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
    CreateBoardRequest,
    AddFindingRequest,
)
from src.models.responses import (
    HealthResponse,
    BaseResponse,
    ErrorResponse,
)
from src.services.log_service import log_service
from src.services.session_service import session_service
from src.services.index_service import index_service
from src.services.memory_service import MemoryService
from src.security.auth import auth_manager, AUTH_CONTEXT_KIBANA, AUTH_CONTEXT_PERISCOPE
from src.security.rate_limiter import search_rate_limiter, auth_rate_limiter, config_rate_limiter
from src.core.config import config
from src.core.constants import APP_VERSION, ERROR_RATE_LIMIT_EXCEEDED
from src.core.exceptions import RateLimitExceeded


# Create router
router = APIRouter()


def get_client_id(request) -> str:
    """Get client identifier for rate limiting."""
    return f"ip:{request.client.host}" if request.client else "unknown"


@router.get("/health", response_model=HealthResponse)
async def health():
    """
    Health check endpoint.

    Returns server status and version.
    """
    return {
        "success": True,
        "version": APP_VERSION,
        "status": "ok",
        "message": "Server is healthy"
    }


# ===== Authentication Endpoints =====

@router.post("/set_auth_token", response_model=BaseResponse)
async def set_auth_token(request: SetAuthTokenRequest):
    """
    Set Kibana authentication token.

    **Security**: Rate limited to prevent brute force attacks.
    """
    # Rate limiting (handled by middleware in production)
    auth_manager.set_token(
        AUTH_CONTEXT_KIBANA,
        request.auth_token,
        ttl=float(request.ttl) if request.ttl else 0.0
    )

    return {
        "success": True,
        "message": "Kibana authentication token set successfully"
    }


@router.post("/set_periscope_auth_token", response_model=BaseResponse)
async def set_periscope_auth_token(request: SetAuthTokenRequest):
    """
    Set Periscope authentication token.

    **Security**: Rate limited to prevent brute force attacks.
    """
    auth_manager.set_token(
        AUTH_CONTEXT_PERISCOPE,
        request.auth_token,
        ttl=float(request.ttl) if request.ttl else 0.0
    )

    return {
        "success": True,
        "message": "Periscope authentication token set successfully"
    }


# ===== Configuration Endpoints =====

@router.post("/set_config", response_model=BaseResponse)
async def set_config(request: SetConfigRequest):
    """
    Set configuration value dynamically.

    Allows runtime configuration updates without restart.
    """
    # Get previous value
    try:
        previous_value = config.get(request.key_path)
    except:
        previous_value = None

    # Set new value
    config.set(request.key_path, request.value)

    return {
        "success": True,
        "message": f"Configuration updated: {request.key_path}",
        "details": {
            "key_path": request.key_path,
            "value": request.value,
            "previous_value": previous_value
        }
    }


# ===== Log Search Endpoints =====

@router.post("/search_logs")
async def search_logs(request: SearchLogsRequest):
    """
    Search logs using KQL query.

    **Required**: Authentication token must be set first.
    **Security**: Input validated, rate limited.
    """
    result = await log_service.search_logs(
        query_text=request.query_text,
        max_results=request.max_results,
        start_time=request.start_time,
        end_time=request.end_time,
        levels=request.levels,
        include_fields=request.include_fields,
        exclude_fields=request.exclude_fields,
        sort_by=request.sort_by,
        sort_order=request.sort_order
    )

    return result


@router.post("/get_recent_logs")
async def get_recent_logs(request: GetRecentLogsRequest):
    """
    Get recent logs.

    Returns the most recent logs, optionally filtered by level.
    """
    result = await log_service.get_recent_logs(
        count=request.count,
        level=request.level,
        index_pattern=request.index_pattern
    )

    return result


@router.post("/analyze_logs")
async def analyze_logs(request: AnalyzeLogsRequest):
    """
    Analyze logs for patterns and aggregations.

    Returns statistical analysis and aggregations.
    """
    result = await log_service.analyze_logs(
        time_range=request.time_range,
        group_by=request.group_by,
        index_pattern=request.index_pattern
    )

    return result


@router.post("/extract_errors")
async def extract_errors(request: ExtractErrorsRequest):
    """
    Extract error logs from specified time range.

    Returns ERROR level logs with optional stack traces.
    """
    result = await log_service.extract_errors(
        hours=request.hours,
        include_stack_traces=request.include_stack_traces,
        limit=request.limit,
        index_pattern=request.index_pattern
    )

    return result


# ===== Session Management Endpoints =====

@router.post("/extract_session_id")
async def extract_session_id(request: ExtractSessionIdRequest):
    """
    Extract session ID from order ID.

    Searches logs for the order ID and extracts the associated session ID.
    """
    result = await session_service.extract_session_id(
        order_id=request.order_id
    )

    return result


# ===== Index Management Endpoints =====

@router.get("/discover_indexes")
async def discover_indexes():
    """
    Discover available Elasticsearch indexes.

    Returns list of index patterns available for searching.
    """
    result = await index_service.discover_indexes()
    return result


@router.post("/set_current_index")
async def set_current_index(request: SetCurrentIndexRequest):
    """
    Set current index pattern for searches.

    All subsequent searches will use this index pattern unless overridden.
    """
    result = await index_service.set_current_index(request.index_pattern)
    return result


# ===== Periscope Endpoints =====

@router.post("/search_periscope_logs")
async def search_periscope_logs(request: PeriscopeSearchRequest):
    """
    Search Periscope logs using SQL query.

    **Security**: SQL injection prevention via sanitization.
    **Features**: Timezone support, flexible time formats.
    """
    from src.clients.periscope_client import periscope_client

    result = await periscope_client.search(
        sql_query=request.sql_query,
        start_time=request.start_time,
        end_time=request.end_time,
        timezone=request.timezone,
        max_results=request.max_results,
        org_identifier=request.org_identifier
    )

    return result


@router.post("/search_periscope_errors")
async def search_periscope_errors(request: PeriscopeErrorsRequest):
    """
    Search for error logs in Periscope.

    Convenience endpoint for finding 4xx/5xx errors.
    Supports timezone-aware relative time queries.
    """
    from src.clients.periscope_client import periscope_client

    result = await periscope_client.search_errors(
        hours=request.hours,
        stream=request.stream,
        error_codes=request.error_codes,
        org_identifier=request.org_identifier,
        timezone=request.timezone
    )

    return result


@router.get("/get_periscope_streams")
async def get_periscope_streams(org_identifier: str = "default"):
    """
    Get available Periscope streams.

    Returns list of log streams available for querying.
    """
    from src.clients.periscope_client import periscope_client

    streams = await periscope_client.get_streams(org_identifier)

    return {
        "success": True,
        "streams": streams,
        "org_identifier": org_identifier,
        "message": f"Found {len(streams)} streams"
    }


@router.post("/get_periscope_stream_schema")
async def get_periscope_stream_schema(stream_name: str, org_identifier: str = "default"):
    """
    Get schema for a Periscope stream.

    Returns field definitions and statistics for the stream.
    """
    from src.clients.periscope_client import periscope_client

    schema = await periscope_client.get_stream_schema(stream_name, org_identifier)

    return {
        "success": True,
        "stream_name": stream_name,
        "schema": schema,
        "message": f"Schema retrieved for stream: {stream_name}"
    }


@router.get("/get_all_periscope_schemas")
async def get_all_periscope_schemas(org_identifier: str = "default"):
    """
    Get schemas for all Periscope streams.

    Returns comprehensive schema information for all available streams.
    """
    from src.clients.periscope_client import periscope_client

    # Get all streams
    streams = await periscope_client.get_streams(org_identifier)

    # Get schema for each stream
    all_schemas = {}
    for stream in streams:
        stream_name = stream.get('name') if isinstance(stream, dict) else stream
        try:
            schema = await periscope_client.get_stream_schema(stream_name, org_identifier)
            all_schemas[stream_name] = schema
        except Exception as e:
            logger.warning(f"Failed to get schema for {stream_name}: {e}")
            all_schemas[stream_name] = {"error": str(e)}

    return {
        "success": True,
        "schemas": all_schemas,
        "count": len(all_schemas),
        "message": f"Retrieved schemas for {len(all_schemas)} streams"
    }


# ===== Memory Board Endpoints =====

memory_router = APIRouter(prefix="/api/memory", tags=["Memory Board"])
memory_service = MemoryService()

@memory_router.get("/all")
def get_all_board_summaries():
    """Gets a summary list (ID and name) of all active memory boards."""
    return memory_service.list_all_boards()

@memory_router.post("/create")
def create_new_memory_board(request: CreateBoardRequest):
    """Creates a new, uniquely named memory board."""
    return memory_service.create_board(name=request.name)

@memory_router.post("/{board_id}/add_finding")
def add_finding_to_board(board_id: str, finding: AddFindingRequest):
    """Adds a finding to the specified memory board."""
    return memory_service.add_finding(board_id, finding.dict())

@memory_router.get("/{board_id}")
def get_memory_board(board_id: str):
    """Gets the current board for a given ID."""
    board = memory_service.get_board(board_id)
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory board with ID '{board_id}' not found."
        )
    return {"board_id": board_id, **board}

@memory_router.post("/{board_id}/clear")
def clear_memory_board(board_id: str):
    """Clears and removes a memory board."""
    result = memory_service.clear_board(board_id)
    if result.get("status") == "not_found":
         raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory board with ID '{board_id}' not found."
        )
    return result
