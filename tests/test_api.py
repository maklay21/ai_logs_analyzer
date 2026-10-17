def test_source_scan_analysis_and_event_query(client):
    http, root = client
    log_dir = root / "payments"
    log_dir.mkdir()
    (log_dir / "api.log").write_text(
        "2026-10-17 12:20:00 - checkout.api - [INFO] request accepted trace_id=z-1\n"
        "2026-10-17 12:20:01 - gateway - [ERROR] provider timeout trace_id=z-1\n",
        encoding="utf-8",
    )

    created = http.post("/api/sources", json={"path": str(log_dir), "name": "Checkout"})
    assert created.status_code == 201
    source_id = created.json()["id"]

    scan = http.post(f"/api/sources/{source_id}/scan")
    assert scan.status_code == 200
    assert scan.json()["events_scanned"] == 2

    report = http.post(
        f"/api/sources/{source_id}/analyze",
        json={"provider": "local"},
    )
    assert report.status_code == 200
    assert report.json()["severity_counts"]["ERROR"] == 1
    assert report.json()["dependency_graph"]["edges"][0]["from"] == "checkout.api"

    events = http.get(f"/api/sources/{source_id}/events?level=ERROR")
    assert events.status_code == 200
    assert len(events.json()["events"]) == 1


def test_source_must_be_inside_allowed_root(client):
    http, _ = client
    response = http.post("/api/sources", json={"path": "/tmp"})
    assert response.status_code == 422
