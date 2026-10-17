from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class AnalysisBase(DeclarativeBase):
    """Tables stored in the dedicated SQLite database shared by API and MCP."""


engine_options: dict = {"pool_pre_ping": True}
if settings.mcp_database_url.endswith(":memory:"):
    engine_options.update(
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
elif settings.mcp_database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}

analysis_engine = create_engine(settings.mcp_database_url, **engine_options)
AnalysisSessionLocal = sessionmaker(
    bind=analysis_engine, autoflush=False, expire_on_commit=False
)


def get_analysis_db() -> Generator[Session, None, None]:
    with AnalysisSessionLocal() as session:
        yield session
