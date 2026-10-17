import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.api.routes import router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.log_analyzer.agent.orchestrator import run_agent_loop
from app.log_analyzer.database import AnalysisBase, analysis_engine
from app.log_analyzer.resource_monitor import collect_and_persist


async def _resource_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(collect_and_persist)
        except Exception:
            logging.exception("Resource sampling failed")
        await asyncio.sleep(max(settings.resource_poll_seconds, 5))


def create_app(
    database_engine: Engine = engine,
    monitor_resources: bool = True,
    run_agent: bool | None = None,
    analysis_database_engine: Engine = analysis_engine,
) -> FastAPI:
    if run_agent is None:
        run_agent = monitor_resources

    @asynccontextmanager
    async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(bind=database_engine)
        AnalysisBase.metadata.create_all(bind=analysis_database_engine)
        background_tasks = []
        if monitor_resources:
            background_tasks.append(asyncio.create_task(_resource_loop()))
        if run_agent:
            background_tasks.append(asyncio.create_task(run_agent_loop()))
        try:
            yield
        finally:
            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)

    application = FastAPI(
        title="AI Logs Analyzer",
        description="Autonomous log investigation, dependency evidence, and resource telemetry.",
        version="0.2.0",
        lifespan=app_lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    application.include_router(router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
