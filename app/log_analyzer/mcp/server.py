import hashlib
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.core.config import settings
from app.log_analyzer.database import AnalysisSessionLocal
from app.log_analyzer.log_analysis import build_report, latest_events, scan_source, validate_log_path
from app.models import AnalysisReport, LogSource, ResourceSample

mcp = FastMCP("AI Logs Analyzer")


@mcp.tool()
def register_configured_sources() -> list[dict]:
    """Ensure each configured, existing allowed log root is registered as a source."""
    registered = []
    for root_value in settings.auto_source_paths:
        try:
            path = validate_log_path(root_value)
        except ValueError:
            continue
        with AnalysisSessionLocal() as db:
            source = db.scalar(select(LogSource).where(LogSource.path == str(path)))
            if source is None:
                existing_sources = db.scalars(select(LogSource)).all()
                overlaps = any(
                    path.is_relative_to(Path(existing.path))
                    or Path(existing.path).is_relative_to(path)
                    for existing in existing_sources
                )
                if overlaps:
                    continue
                source = LogSource(name=path.name or str(path), path=str(path))
                db.add(source)
                db.commit()
                db.refresh(source)
            registered.append({"id": source.id, "name": source.name, "path": source.path})
    return registered


@mcp.tool()
def list_log_sources() -> list[dict]:
    """List configured log folders and their latest scan status."""
    with AnalysisSessionLocal() as db:
        sources = db.scalars(select(LogSource).order_by(LogSource.name)).all()
        return [
            {
                "id": source.id,
                "name": source.name,
                "path": source.path,
                "events_count": source.events_count,
                "last_scan_at": source.last_scan_at.isoformat() if source.last_scan_at else None,
            }
            for source in sources
        ]


@mcp.tool()
def scan_log_source(source_id: str) -> dict:
    """Scan a registered source and return its baseline findings and a change signature."""
    with AnalysisSessionLocal() as db:
        source = db.get(LogSource, source_id)
        if source is None:
            raise ValueError("Log source not found")
        events = scan_source(db, source)
        report = build_report(events)
        stable_events = [
            [
                event.file_path,
                event.line_number,
                event.timestamp.isoformat() if event.timestamp else None,
                event.level,
                event.logger_name,
                event.trace_id,
                event.message,
            ]
            for event in events
        ]
        signature = hashlib.sha256(
            json.dumps(stable_events, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "source_id": source.id,
            "source_name": source.name,
            "content_signature": signature,
            **report,
            "sample_events": [
                {
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "level": event.level,
                    "logger": event.logger_name,
                    "trace_id": event.trace_id,
                    "file": event.file_path,
                    "line": event.line_number,
                    "message": event.message[:1000],
                }
                for event in events[-40:]
            ],
        }


@mcp.tool()
def search_log_events(source_id: str, level: str = "", limit: int = 50) -> list[dict]:
    """Return recent stored events. This tool never reads arbitrary filesystem paths."""
    safe_limit = max(1, min(limit, 100))
    with AnalysisSessionLocal() as db:
        events = latest_events(db, source_id, level or None, safe_limit)
        return [
            {
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "level": event.level,
                "logger": event.logger_name,
                "trace_id": event.trace_id,
                "file": event.file_path,
                "line": event.line_number,
                "message": event.message[:2000],
            }
            for event in events
        ]


@mcp.tool()
def get_latest_analysis(source_id: str) -> dict | None:
    """Return the latest saved report and observed dependency graph for a source."""
    with AnalysisSessionLocal() as db:
        report = db.scalar(
            select(AnalysisReport)
            .where(AnalysisReport.source_id == source_id)
            .order_by(AnalysisReport.created_at.desc())
        )
        if report is None:
            return None
        return {
            "provider": report.provider,
            "summary": report.summary,
            "severity_counts": report.severity_counts,
            "findings": report.findings,
            "dependency_graph": report.dependency_graph,
            "created_at": report.created_at.isoformat(),
        }


@mcp.tool()
def get_resource_history(limit: int = 30) -> list[dict]:
    """Return recent host and monitored Docker container resource samples."""
    safe_limit = max(1, min(limit, 100))
    with AnalysisSessionLocal() as db:
        samples = db.scalars(
            select(ResourceSample).order_by(ResourceSample.sampled_at.desc()).limit(safe_limit)
        ).all()
        return [
            {
                "sampled_at": sample.sampled_at.isoformat(),
                "host_cpu_percent": sample.host_cpu_percent,
                "host_memory_percent": sample.host_memory_percent,
                "host_disk_percent": sample.host_disk_percent,
                "process_cpu_percent": sample.process_cpu_percent,
                "process_memory_bytes": sample.process_memory_bytes,
                "docker_error": sample.docker_error,
                "docker_containers": sample.docker_containers,
            }
            for sample in samples
        ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
