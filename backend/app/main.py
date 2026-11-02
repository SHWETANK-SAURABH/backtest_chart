"""FastAPI application entry point."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    ai_datasets,
    analytics,
    backtests,
    instruments,
    market_data,
    reports,
    strategies,
    system,
)
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(title="NIFTY 50 Backtester API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api/v1")
    api.include_router(system.router)
    api.include_router(instruments.router)
    api.include_router(market_data.router)
    api.include_router(strategies.router)
    api.include_router(backtests.router)
    api.include_router(analytics.router)
    api.include_router(reports.router)
    api.include_router(ai_datasets.router)
    app.include_router(api)
    return app


app = create_app()
