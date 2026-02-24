"""
FastAPI application for LLM Portfolio Journal.

Provides REST API endpoints for:
- Portfolio summary and positions
- Order history with notification status
- Stock profiles, ideas, and OHLCV data
- Symbol search and watchlist management
- SnapTrade webhook handling
- AI-powered stock chat analysis

Security:
- API key authentication on all endpoints except /health and webhooks
- CORS restricted to allowed frontend origins
- Bind to 127.0.0.1 (Nginx handles public traffic with SSL)
"""

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import require_api_key
from app.routes import (
    sentiment,
    portfolio,
    orders,
    stocks,
    search,
    watchlist,
    chat,
    webhook,
    activities,
    openbb as openbb_routes,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("Starting LLM Portfolio Journal API...")
    # Startup: verify database connection
    try:
        from src.db import healthcheck

        if healthcheck():
            logger.info("Database connection verified")
        else:
            logger.warning("Database health check failed")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

    # Check yfinance availability (non-blocking)
    try:
        from src.market_data_service import is_available as yf_available

        if yf_available():
            logger.info("yfinance market data service available")
        else:
            logger.warning("yfinance not available — supplementary market data disabled")
    except Exception:
        logger.warning("yfinance module not loaded")

    # Check OpenBB availability (non-blocking)
    try:
        from src.openbb_service import is_available as obb_available

        if obb_available():
            logger.info("OpenBB Platform SDK available (FMP + SEC providers)")
        else:
            logger.warning("OpenBB not available — fundamental data disabled")
    except Exception:
        logger.warning("OpenBB module not loaded")

    yield

    # Shutdown
    logger.info("Shutting down LLM Portfolio Journal API...")


# Create FastAPI app
app = FastAPI(
    title="LLM Portfolio Journal API",
    description="REST API for portfolio analytics, trading ideas, and market data",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration - allow frontend origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",  # Local Next.js dev
    "http://127.0.0.1:3000",
    "https://llm-portfolio-frontend.vercel.app",  # Production Vercel
    "https://llmportfolio.app",  # Custom domain (if configured)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# Include routers with API key authentication
# Protected routes - require API key
app.include_router(
    portfolio.router,
    prefix="/portfolio",
    tags=["Portfolio"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    orders.router,
    prefix="/orders",
    tags=["Orders"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    stocks.router,
    prefix="/stocks",
    tags=["Stocks"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    search.router,
    prefix="/search",
    tags=["Search"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    watchlist.router,
    prefix="/watchlist",
    tags=["Watchlist"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    chat.router,
    prefix="/stocks",
    tags=["Chat"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    activities.router,
    prefix="/activities",
    tags=["Activities"],
    dependencies=[Depends(require_api_key)],
)

app.include_router(
    sentiment.router,
    prefix="/sentiment",
    tags=["Sentiment"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    openbb_routes.router,
    prefix="/stocks",
    tags=["OpenBB Insights"],
    dependencies=[Depends(require_api_key)],
)

# Webhook routes - protected by signature verification, NOT API key
app.include_router(webhook.router, prefix="/webhook", tags=["Webhooks"])


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint - redirect to docs."""
    return {"message": "LLM Portfolio Journal API", "docs": "/docs"}


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        status: "healthy" or "degraded"
        timestamp: Current UTC timestamp
        database: Database connection status
        version: API version
    """
    db_healthy = False
    try:
        from src.db import healthcheck

        db_healthy = healthcheck()
    except Exception as e:
        logger.warning(f"Health check database error: {e}")

    status = "healthy" if db_healthy else "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "connected" if db_healthy else "disconnected",
        "version": "1.0.0",
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if app.debug else "An unexpected error occurred",
            "status": 500,
        },
    )


if __name__ == "__main__":
    import uvicorn

    # Bind to 127.0.0.1 - Nginx handles public traffic with SSL
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
