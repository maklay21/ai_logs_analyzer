from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.log_analyzer.database import AnalysisBase


def utc_now() -> datetime:
    return datetime.now(UTC)


class LogSource(AnalysisBase):
    __tablename__ = "log_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(240))
    path: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events_count: Mapped[int] = mapped_column(Integer, default=0)

    events: Mapped[list["LogEvent"]] = relationship(back_populates="source", cascade="all, delete-orphan")
    reports: Mapped[list["AnalysisReport"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class LogEvent(AnalysisBase):
    __tablename__ = "log_events"
    __table_args__ = (UniqueConstraint("source_id", "file_path", "line_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("log_sources.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(2048))
    line_number: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16), default="UNKNOWN", index=True)
    logger_name: Mapped[str] = mapped_column(String(300), default="")
    trace_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    source: Mapped[LogSource] = relationship(back_populates="events")


class AnalysisReport(AnalysisBase):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("log_sources.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="local")
    summary: Mapped[str] = mapped_column(Text)
    severity_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    dependency_graph: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    source: Mapped[LogSource] = relationship(back_populates="reports")


class ResourceSample(AnalysisBase):
    __tablename__ = "resource_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    host_cpu_percent: Mapped[float] = mapped_column(Float)
    host_memory_percent: Mapped[float] = mapped_column(Float)
    host_disk_percent: Mapped[float] = mapped_column(Float)
    process_cpu_percent: Mapped[float] = mapped_column(Float)
    process_memory_bytes: Mapped[int] = mapped_column(Integer)
    docker_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    docker_containers: Mapped[list] = mapped_column(JSON, default=list)
