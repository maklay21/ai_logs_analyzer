from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import AnalysisRequest, LogSourceCreate
from app.log_analyzer.agent.orchestrator import get_agent_status
from app.log_analyzer.database import get_analysis_db
from app.log_analyzer.log_analysis import build_report, latest_events, scan_source, validate_log_path
from app.models import AnalysisReport, LogSource, ResourceSample

router = APIRouter(prefix="/api")


def _source_payload(source: LogSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "path": source.path,
        "created_at": source.created_at.isoformat(),
        "last_scan_at": source.last_scan_at.isoformat() if source.last_scan_at else None,
        "events_count": source.events_count,
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/overview")
def overview(db: Session = Depends(get_analysis_db)) -> dict:
    sources = db.scalars(select(LogSource).order_by(LogSource.created_at.desc())).all()
    latest_resource = db.scalar(
        select(ResourceSample).order_by(ResourceSample.sampled_at.desc()).limit(1)
    )
    return {
        "sources": [_source_payload(source) for source in sources],
        "latest_resource": _resource_payload(latest_resource) if latest_resource else None,
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/sources", status_code=201)
def create_source(payload: LogSourceCreate, db: Session = Depends(get_analysis_db)) -> dict:
    try:
        path = validate_log_path(payload.path)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    source = db.scalar(select(LogSource).where(LogSource.path == str(path)))
    if source is not None:
        return _source_payload(source)
    existing_sources = db.scalars(select(LogSource)).all()
    for existing in existing_sources:
        existing_path = Path(existing.path)
        if path.is_relative_to(existing_path) or existing_path.is_relative_to(path):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Путь пересекается с источником {existing.path}. "
                    "Настройте непересекающиеся пути в AUTO_LOG_SOURCE_PATHS."
                ),
            )

    source = LogSource(name=payload.name or path.name or str(path), path=str(path))
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_payload(source)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, db: Session = Depends(get_analysis_db)) -> None:
    source = db.get(LogSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Log source not found")
    db.delete(source)
    db.commit()


@router.post("/sources/{source_id}/scan")
def scan_log_source(source_id: str, db: Session = Depends(get_analysis_db)) -> dict:
    source = db.get(LogSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Log source not found")
    try:
        events = scan_source(db, source)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"source": _source_payload(source), "events_scanned": len(events)}


@router.get("/sources/{source_id}/events")
def source_events(
    source_id: str,
    level: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_analysis_db),
) -> dict:
    if db.get(LogSource, source_id) is None:
        raise HTTPException(status_code=404, detail="Log source not found")
    events = latest_events(db, source_id, level, limit)
    return {
        "events": [
            {
                "id": event.id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "level": event.level,
                "logger": event.logger_name,
                "trace_id": event.trace_id,
                "file": event.file_path,
                "line": event.line_number,
                "message": event.message,
            }
            for event in events
        ]
    }


@router.post("/sources/{source_id}/analyze")
def analyze_source(source_id: str, payload: AnalysisRequest, db: Session = Depends(get_analysis_db)) -> dict:
    """Compatibility endpoint for local baseline reports; model runs belong to the agent loop."""
    source = db.get(LogSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Log source not found")
    if payload.provider not in (None, "local"):
        raise HTTPException(
            status_code=409,
            detail="Модель запускается фоновым агентом; настройте AI_PROVIDER в .env.",
        )
    try:
        events = scan_source(db, source)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result = build_report(events)
    report = AnalysisReport(
        source_id=source.id,
        provider="local",
        summary=result["summary"],
        severity_counts=result["severity_counts"],
        findings=result["findings"],
        dependency_graph=result["dependency_graph"],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_payload(report)


@router.get("/agent/status")
def agent_status() -> dict:
    return get_agent_status()


@router.get("/sources/{source_id}/reports/latest")
def latest_report(source_id: str, db: Session = Depends(get_analysis_db)) -> dict:
    if db.get(LogSource, source_id) is None:
        raise HTTPException(status_code=404, detail="Log source not found")
    report = db.scalar(
        select(AnalysisReport)
        .where(AnalysisReport.source_id == source_id)
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )
    if report is None:
        raise HTTPException(status_code=404, detail="No analysis report yet")
    return _report_payload(report)


@router.get("/resources")
def resources(
    limit: int = Query(default=60, ge=1, le=1000),
    db: Session = Depends(get_analysis_db),
) -> dict:
    samples = db.scalars(
        select(ResourceSample).order_by(ResourceSample.sampled_at.desc()).limit(limit)
    ).all()
    return {"samples": [_resource_payload(sample) for sample in reversed(samples)]}


def _report_payload(report: AnalysisReport) -> dict:
    return {
        "id": report.id,
        "source_id": report.source_id,
        "provider": report.provider,
        "summary": report.summary,
        "severity_counts": report.severity_counts,
        "findings": report.findings,
        "dependency_graph": report.dependency_graph,
        "created_at": report.created_at.isoformat(),
    }


def _resource_payload(sample: ResourceSample) -> dict:
    return {
        "sampled_at": sample.sampled_at.isoformat(),
        "host_cpu_percent": sample.host_cpu_percent,
        "host_memory_percent": sample.host_memory_percent,
        "host_disk_percent": sample.host_disk_percent,
        "process_cpu_percent": sample.process_cpu_percent,
        "process_memory_bytes": sample.process_memory_bytes,
        "docker_error": sample.docker_error,
        "docker_containers": sample.docker_containers,
    }
