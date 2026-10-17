from app.log_analyzer.log_analysis import build_report, parse_log_line, read_log_directory, validate_log_path
from app.models import LogEvent


def test_parse_plain_log_extracts_timestamp_level_logger_and_trace():
    event = parse_log_line(
        "2026-10-17 12:21:35 - billing.api - [ERROR] Payment failed trace_id=req-123",
        "api.log",
        8,
    )

    assert event.level == "ERROR"
    assert event.logger_name == "billing.api"
    assert event.trace_id == "req-123"
    assert event.timestamp is not None
    assert event.message.endswith("Payment failed trace_id=req-123")


def test_parse_json_log():
    event = parse_log_line(
        '{"timestamp":"2026-10-17T09:21:35Z","level":"warning",'
        '"logger":"gateway","message":"slow response","request_id":"r-1"}'
    )

    assert event.level == "WARNING"
    assert event.logger_name == "gateway"
    assert event.trace_id == "r-1"
    assert event.timestamp is not None


def test_read_directory_and_build_trace_dependency_report(tmp_path):
    (tmp_path / "api.log").write_text(
        "2026-10-17 12:00:00 - web.api - [INFO] accepted trace_id=x-1\n"
        "2026-10-17 12:00:01 - billing.worker - [ERROR] provider timeout trace_id=x-1\n",
        encoding="utf-8",
    )
    parsed = read_log_directory(tmp_path)
    events = [
        LogEvent(
            source_id="source",
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

    report = build_report(events)
    assert report["events_scanned"] == 2
    assert report["severity_counts"]["ERROR"] == 1
    assert report["dependency_graph"]["edges"] == [
        {"from": "web.api", "to": "billing.worker", "weight": 1}
    ]


def test_rejects_log_path_outside_configured_root(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setattr("app.log_analyzer.log_analysis.settings.log_allowed_roots", str(allowed))

    try:
        validate_log_path(str(outside))
    except ValueError as error:
        assert "outside LOG_ALLOWED_ROOTS" in str(error)
    else:
        raise AssertionError("outside path should be rejected")

