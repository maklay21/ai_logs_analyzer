import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.log_analyzer.database import AnalysisBase, get_analysis_db
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "log_allowed_roots", str(tmp_path))
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    AnalysisBase.metadata.create_all(bind=engine)

    def override_analysis_db():
        with testing_session() as db:
            yield db

    application = create_app(
        database_engine=engine,
        analysis_database_engine=engine,
        monitor_resources=False,
    )
    application.dependency_overrides[get_analysis_db] = override_analysis_db
    with TestClient(application) as test_client:
        yield test_client, tmp_path

    application.dependency_overrides.clear()
    AnalysisBase.metadata.drop_all(bind=engine)
    engine.dispose()

