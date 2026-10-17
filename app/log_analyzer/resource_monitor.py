from datetime import UTC, datetime
from typing import Any

import psutil
from sqlalchemy.orm import Session

from app.core.config import settings
from app.log_analyzer.database import AnalysisSessionLocal
from app.models import ResourceSample


def collect_resources() -> dict[str, Any]:
    process = psutil.Process()
    snapshot: dict[str, Any] = {
        "sampled_at": datetime.now(UTC),
        "host_cpu_percent": psutil.cpu_percent(interval=None),
        "host_memory_percent": psutil.virtual_memory().percent,
        "host_disk_percent": psutil.disk_usage("/").percent,
        "process_cpu_percent": process.cpu_percent(interval=0.1),
        "process_memory_bytes": process.memory_info().rss,
        "docker_containers": [],
    }

    if settings.target_container:
        try:
            import docker

            client = docker.from_env(timeout=3)
            container = client.containers.get(settings.target_container)
            stats = container.stats(stream=False)
            cpu = stats.get("cpu_stats", {})
            precpu = stats.get("precpu_stats", {})
            cpu_delta = (
                cpu.get("cpu_usage", {}).get("total_usage", 0)
                - precpu.get("cpu_usage", {}).get("total_usage", 0)
            )
            system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
            cpu_count = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [])) or 1
            memory = stats.get("memory_stats", {})
            memory_usage = memory.get("usage", 0)
            memory_limit = memory.get("limit", 0)
            snapshot["docker_containers"].append({
                "name": settings.target_container,
                "cpu_percent": round((cpu_delta / system_delta) * cpu_count * 100, 2) if system_delta > 0 else 0,
                "memory_usage_bytes": memory_usage,
                "memory_limit_bytes": memory_limit,
                "memory_percent": round(memory_usage / memory_limit * 100, 2) if memory_limit else 0,
            })
            client.close()
        except Exception as error:  # Docker socket may be intentionally unavailable.
            snapshot["docker_error"] = str(error)[:300]
    return snapshot


def persist_resource_snapshot(db: Session, snapshot: dict[str, Any]) -> ResourceSample:
    sample = ResourceSample(**snapshot)
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


def collect_and_persist() -> None:
    snapshot = collect_resources()
    with AnalysisSessionLocal() as db:
        persist_resource_snapshot(db, snapshot)
