"""
FastAPI Application Factory

Creates and configures the FastAPI application.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from src.core.constants import APP_NAME, APP_VERSION, APP_DESCRIPTION
from src.core.exceptions import KibanaMCPException
from src.api.http.routes import router as http_router, memory_router
from src.observability.tracing import setup_tracing


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI application

    Example:
        >>> app = create_app()
        >>> uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    # Create FastAPI app
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure this properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add exception handlers
    @app.exception_handler(KibanaMCPException)
    async def kibana_mcp_exception_handler(request: Request, exc: KibanaMCPException):
        """Handle custom exceptions."""
        logger.error(f"KibanaMCPException: {exc.message}")
        return JSONResponse(
            status_code=400,  # Most custom exceptions are client errors
            content=exc.to_dict()
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions."""
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred",
                "details": {"type": type(exc).__name__}
            }
        )

    # Include routers
    app.include_router(http_router, prefix="/api")
    app.include_router(memory_router)

    # Instrument FastAPI app for OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)

    # Startup event
    @app.on_event("startup")
    async def startup_event():
        """Run on application startup."""
        setup_tracing()
        logger.info(f"{APP_NAME} v{APP_VERSION} started")
        logger.info("API documentation available at /docs")

    # Shutdown event
    @app.on_event("shutdown")
    async def shutdown_event():
        """Run on application shutdown."""
        logger.info("Shutting down gracefully...")
        # Cleanup resources here if needed

    return app
