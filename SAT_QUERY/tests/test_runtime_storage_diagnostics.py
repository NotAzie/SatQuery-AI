from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from satquery.api import create_app, set_engine
from satquery.config import Settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.config import PlatformConfig
from satquery.platform.runtime import PlatformRuntime


def test_runtime_health_reports_shared_monitoring_storage_as_durable():
    settings = Settings.from_env(dotenv_path=None)
    database = Path.cwd() / f".runtime-storage-{uuid4().hex}.sqlite"
    config = PlatformConfig.load(
        environ={},
        overrides={"storage": {"monitoring_path": str(database)}},
    )
    engine = SatQueryEngine(settings)
    engine.platform_runtime = PlatformRuntime(config=config)
    set_engine(engine)

    try:
        with TestClient(create_app(settings)) as client:
            response = client.get("/api/v1/platform/runtime")
        assert response.status_code == 200
        storage = response.json()["storage"]
        assert set(storage) == {
            "earth_memory",
            "lifecycle",
            "execution",
            "audit",
            "monitoring",
        }
        assert all(
            item == {"backend": "sqlite", "durable": True}
            for item in storage.values()
        )
    finally:
        set_engine(None)
        database.unlink(missing_ok=True)
        Path(f"{database}-wal").unlink(missing_ok=True)
        Path(f"{database}-shm").unlink(missing_ok=True)
