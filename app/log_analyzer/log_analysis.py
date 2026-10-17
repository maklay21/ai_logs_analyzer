import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import LogEvent, LogSource, utc_now

LOG_SUFFIXES = {".log", ".txt", ".out", ".jsonl"}
LEVEL_RE = re.compile(r"\b(CRITICAL|FATAL|ERROR|ERR|WARNING|WARN|INFO|DEBUG|TRACE)\b", re.I)
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)"
)
TRACE_RE = re.compile(r"\b(?:trace[_-]?id|request[_-]?id|correlation[_-]?id)[=: ]+['\"]?([\w.-]+)", re.I)


@dataclass(frozen=True)
class ParsedEvent:
    file_path: str
    line_number: int
    timestamp: datetime | None
    level: str
    logger_name: str
    trace_id: str | None
    message: str
    fingerprint: str


def validate_log_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Log path must be an existing directory")

    allowed = False
    for root_value in settings.allowed_roots:
        root = Path(root_value).expanduser().resolve()
        try:
            path.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue

    if not allowed:
        raise ValueError("Log directory is outside LOG_ALLOWED_ROOTS")
    return path


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace(",", ".")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _fingerprint(message: str, logger_name: str) -> str:
    normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", message.lower())
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(f"{logger_name}:{normalized}".encode()).hexdigest()[:32]


def parse_log_line(line: str, file_path: str = "", line_number: int = 0) -> ParsedEvent:
    """Parse common plain-text and JSON log formats into a normalized event."""

    original = line.rstrip("\r\n")
    timestamp = None
    level = "UNKNOWN"
    logger_name = ""
    trace_id = None
    message = original

    try:
        payload = json.loads(original)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
        timestamp = _parse_timestamp(
            payload.get("timestamp") or payload.get("time") or payload.get("@timestamp")
        )
        level = str(payload.get("level") or payload.get("severity") or "UNKNOWN").upper()
        if level == "WARN":
            level = "WARNING"
        elif level == "FATAL":
            level = "CRITICAL"
        elif level == "ERR":
            level = "ERROR"
        logger_name = str(payload.get("logger") or payload.get("name") or "")
        trace_id = str(payload.get("trace_id") or payload.get("request_id") or "") or None
        message = str(payload.get("message") or payload.get("msg") or original)
    else:
        timestamp_match = TIMESTAMP_RE.match(original)
        if timestamp_match:
            timestamp = _parse_timestamp(timestamp_match.group(1))
        level_match = LEVEL_RE.search(original)
        if level_match:
            level = level_match.group(1).upper()
            if level == "WARN":
                level = "WARNING"
            elif level in {"FATAL", "ERR"}:
                level = "ERROR" if level == "ERR" else "CRITICAL"
        logger_match = re.search(r"\s-\s([\w.$:/-]+)\s-\s", original)
        if logger_match:
            logger_name = logger_match.group(1)
        trace_match = TRACE_RE.search(original)
        if trace_match:
            trace_id = trace_match.group(1)
        if timestamp_match:
            message = original[timestamp_match.end():].strip(" -")

    normalized_logger = logger_name or Path(file_path).stem
    return ParsedEvent(
        file_path=file_path,
        line_number=line_number,
        timestamp=timestamp,
        level=level,
        logger_name=normalized_logger,
        trace_id=trace_id,
        message=message[:20_000],
        fingerprint=_fingerprint(message, normalized_logger),
    )


def read_log_directory(directory: Path) -> list[ParsedEvent]:
    events: list[ParsedEvent] = []
    files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in LOG_SUFFIXES
    )[: settings.max_log_files]

    for file_path in files:
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if len(events) >= settings.max_log_lines:
                        return events
                    if line.strip():
                        events.append(
                            parse_log_line(
                                line,
                                str(file_path.relative_to(directory)),
                                line_number,
                            )
                        )
        except OSError:
            continue
    return events


def scan_source(db: Session, source: LogSource) -> list[LogEvent]:
    directory = validate_log_path(source.path)
    parsed = read_log_directory(directory)
    db.execute(delete(LogEvent).where(LogEvent.source_id == source.id))
    events = [
        LogEvent(
            source_id=source.id,
            file_path=item.file_path,
            line_number=item.line_number,
            timestamp=item.timestamp,
            level=item.level,
            logger_name=item.logger_name,
            trace_id=item.trace_id,
            message=item.message,
            fingerprint=item.fingerprint,
        )
        for item in parsed
    ]
    db.add_all(events)
    source.last_scan_at = utc_now()
    source.events_count = len(events)
    db.commit()
    return events


def build_report(events: list[LogEvent]) -> dict[str, Any]:
    levels = Counter(event.level for event in events)
    error_groups: dict[str, list[LogEvent]] = defaultdict(list)
    for event in events:
        if event.level in {"ERROR", "CRITICAL"}:
            error_groups[event.fingerprint].append(event)

    findings = []
    for fingerprint, occurrences in sorted(
        error_groups.items(), key=lambda item: len(item[1]), reverse=True
    )[:10]:
        sample = occurrences[0]
        findings.append({
            "fingerprint": fingerprint,
            "count": len(occurrences),
            "logger": sample.logger_name,
            "message": sample.message[:500],
            "first_seen": min((item.timestamp for item in occurrences if item.timestamp), default=None).isoformat()
            if any(item.timestamp for item in occurrences) else None,
            "last_seen": max((item.timestamp for item in occurrences if item.timestamp), default=None).isoformat()
            if any(item.timestamp for item in occurrences) else None,
        })

    trace_groups: dict[str, list[LogEvent]] = defaultdict(list)
    for event in events:
        if event.trace_id:
            trace_groups[event.trace_id].append(event)

    edge_counts: Counter[tuple[str, str]] = Counter()
    for trace_events in trace_groups.values():
        ordered = sorted(trace_events, key=lambda item: item.timestamp or datetime.min.replace(tzinfo=UTC))
        loggers = list(dict.fromkeys(item.logger_name for item in ordered if item.logger_name))
        edge_counts.update(zip(loggers, loggers[1:], strict=False))

    nodes = sorted({name for edge in edge_counts for name in edge})
    graph = {
        "nodes": [{"id": name, "label": name} for name in nodes],
        "edges": [{"from": start, "to": end, "weight": count} for (start, end), count in edge_counts.most_common(50)],
        "method": "Observed logger order within shared trace/request IDs",
    }
    error_count = levels.get("ERROR", 0) + levels.get("CRITICAL", 0)
    warning_count = levels.get("WARNING", 0)
    summary = (
        f"Scanned {len(events)} log events: {error_count} errors/critical events, "
        f"{warning_count} warnings, and {len(findings)} recurring error signatures."
    )
    return {
        "summary": summary,
        "severity_counts": dict(levels),
        "findings": findings,
        "dependency_graph": graph,
        "events_scanned": len(events),
    }


def latest_events(db: Session, source_id: str, level: str | None = None, limit: int = 100) -> list[LogEvent]:
    query = select(LogEvent).where(LogEvent.source_id == source_id)
    if level:
        query = query.where(LogEvent.level == level.upper())
    return list(db.scalars(query.order_by(LogEvent.timestamp.desc().nullslast()).limit(limit)).all())
