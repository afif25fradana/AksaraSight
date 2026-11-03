"""Tests for Web settings endpoints, lifecycle persistence, and diagnostics."""

import asyncio
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch
import urllib3

import pytest

from config.settings import Settings
from core.engine import OCREngine
from core.server_manager import ServerStatus
from web.app import create_app, enforce_loopback_host
from web.orchestrator import JobStatus, WebOrchestrator
from tests.web_fixtures import (
    AsgiClient,
    MockEngine,
    MockServerManager,
    _create_sample_png_bytes,
)


def test_patch_settings_enforces_loopback_unless_allow_remote_true() -> None:
    """Verify PATCH /api/settings rejects non-loopback local_endpoint when allow_remote is False."""
    app = create_app()
    client = AsgiClient(app)
    status, _, resp = client.request(
        "PATCH",
        "/api/settings",
        body=json.dumps({"local_endpoint": "http://192.168.1.50:8080/v1", "allow_remote": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert "Non-loopback endpoint" in data["detail"]

    # Enforce loopback check helper
    enforce_loopback_host("127.0.0.1")
    enforce_loopback_host("localhost")

    with pytest.raises(ValueError, match="strictly requires loopback"):
        enforce_loopback_host("0.0.0.0")

    with pytest.raises(ValueError, match="strictly requires loopback"):
        enforce_loopback_host("192.168.1.100")


def test_doctor_endpoint_execution_and_schema(tmp_path: Path) -> None:
    """Verify POST /api/doctor runs diagnostics and GET /api/doctor returns the cached report."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Before POST, GET /api/doctor returns 404 with report: None
    status, _, resp = client.get("/api/doctor")
    assert status == 404
    data = json.loads(resp.decode("utf-8"))
    assert data["report"] is None

    # POST /api/doctor executes diagnostics
    status, _, resp = client.post("/api/doctor")
    assert status == 200
    post_data = json.loads(resp.decode("utf-8"))
    assert "status" in post_data
    assert "exit_code" in post_data
    assert "total_checks" in post_data
    assert "failed_checks" in post_data
    assert "checks" in post_data
    assert isinstance(post_data["checks"], list)
    if post_data["checks"]:
        first_check = post_data["checks"][0]
        assert "category" in first_check
        assert "title" in first_check
        assert "status" in first_check
        assert "details" in first_check
        assert "remediation" in first_check
    assert "text" in post_data
    assert isinstance(post_data["text"], str)

    # GET /api/doctor returns cached report
    status, _, resp = client.get("/api/doctor")
    assert status == 200
    get_data = json.loads(resp.decode("utf-8"))
    assert get_data == post_data


def test_settings_endpoint_lifecycle_and_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify settings querying, valid patch persistence, and strict security rejecting malformed keys."""
    pre_env = dict(os.environ)
    try:
        env_file = tmp_path / ".env"
        monkeypatch.chdir(tmp_path)

        app = create_app(upload_dir=tmp_path, env_path=env_file)
        client = AsgiClient(app)

        # 1. GET /api/settings
        status, _, resp = client.get("/api/settings")
        assert status == 200
        settings_data = json.loads(resp.decode("utf-8"))
        assert "dpi" in settings_data
        assert "timeout" in settings_data
        assert "backend" in settings_data
        assert "auto_start_server" in settings_data
        assert "llama_server_path" in settings_data
        assert "allow_remote" in settings_data

        # 2. PATCH /api/settings valid updates (numeric/basic settings)
        patch_body = json.dumps({"dpi": 150, "timeout": 45.0}).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_body,
        )
        assert status == 200
        res = json.loads(resp.decode("utf-8"))
        assert res["updated"] is True
        assert res["settings"]["dpi"] == 150
        assert res["settings"]["timeout"] == 45.0
        assert app.state.settings.dpi == 150
        assert app.state.settings.timeout == 45.0
        assert env_file.exists()
        saved_env = env_file.read_text(encoding="utf-8")
        assert "150" in saved_env

        # 3. PATCH newly mutable backend/runtime keys
        patch_backend_body = json.dumps({
            "backend": "ollama",
            "runtime_mode": "custom",
            "managed_backend_override": "cuda",
            "llama_server_path": "C:\\tools\\llama-server.exe",
            "model_repo": "test/repo",
            "allow_remote": True,
            "local_endpoint": "http://remote.lan:8080/v1",
        }).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_backend_body,
        )
        assert status == 200
        res = json.loads(resp.decode("utf-8"))
        assert res["updated"] is True
        assert res["settings"]["backend"] == "ollama"
        assert res["settings"]["runtime_mode"] == "custom"
        assert res["settings"]["managed_backend_override"] == "cuda"
        assert res["settings"]["llama_server_path"] == "C:\\tools\\llama-server.exe"
        assert res["settings"]["model_repo"] == "test/repo"
        assert res["settings"]["allow_remote"] is True
        assert res["settings"]["local_endpoint"] == "http://remote.lan:8080/v1"
        assert app.state.settings.backend == "ollama"
        assert app.state.settings.local_endpoint == "http://remote.lan:8080/v1"
        assert app.state.engine.client.endpoint == "http://remote.lan:8080/v1/chat/completions"

        # Also test empty string llama_server_path normalizes to None
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"llama_server_path": "   "}).encode("utf-8"),
        )
        assert status == 200
        res = json.loads(resp.decode("utf-8"))
        assert res["settings"]["llama_server_path"] is None
        assert app.state.settings.llama_server_path is None

        # 4. Non-loopback local_endpoint rejected when allow_remote=False
        # Reset to loopback first with allow_remote=False
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"allow_remote": False, "local_endpoint": "http://127.0.0.1:8080/v1"}).encode("utf-8"),
        )
        assert status == 200
        # Attempting to change local_endpoint to non-loopback while allow_remote=False must return 400
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"local_endpoint": "http://remote.lan:8080/v1"}).encode("utf-8"),
        )
        assert status == 400

        # 5. PATCH unknown keys (must return 400 Bad Request)
        body_bytes = json.dumps({"unknown_key": "val"}).encode("utf-8")
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=body_bytes,
        )
        assert status == 400

        # 6. PATCH invalid enum values (must return 400 Bad Request)
        for invalid_enum in [
            {"backend": "invalid_engine"},
            {"runtime_mode": "invalid_mode"},
            {"managed_backend_override": "invalid_accel"},
        ]:
            status, _, _ = client.patch(
                "/api/settings",
                headers={"content-type": "application/json"},
                body=json.dumps(invalid_enum).encode("utf-8"),
            )
            assert status == 400

        # 7. PATCH invalid types and ranges (must return 400 Bad Request)
        for invalid_payload in [
            {"dpi": "not_an_int"},
            {"dpi": -5},
            {"dpi": 1000},
            {"timeout": "slow"},
            {"timeout": 0.5},
            {"max_retries": -1},
            {"max_retries": 15},
            {"auto_start_server": "yes"},
            {"allow_remote": "yes"},
            {"llama_server_path": 123},
            {"model_repo": ""},
            {"backend": ""},
            {"local_endpoint": ""},
            {"runtime_mode": ""},
            {"managed_backend_override": ""},
        ]:
            body_bytes = json.dumps(invalid_payload).encode("utf-8")
            status, _, _ = client.patch(
                "/api/settings",
                headers={"content-type": "application/json"},
                body=body_bytes,
            )
            assert status == 400
    finally:
        os.environ.clear()
        os.environ.update(pre_env)


test_settings_api_patch_and_persistence = test_settings_endpoint_lifecycle_and_security


def test_dialog_pick_file_endpoint(tmp_path: Path) -> None:
    """Verify POST /api/dialog/file returns picked file path or None."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Success mock
    with patch("web.app._pick_executable_file", return_value="C:\\custom\\llama-server.exe"):
        status, _, body = client.post("/api/dialog/file")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data == {"path": "C:\\custom\\llama-server.exe"}

    # 2. Cancellation / None mock
    with patch("web.app._pick_executable_file", return_value=None):
        status, _, body = client.post("/api/dialog/file")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data == {"path": None}


def test_pick_executable_file_helper() -> None:
    """Verify _pick_executable_file handles subprocess exit codes and exceptions."""
    import subprocess
    from web.app import _pick_executable_file

    class DummyProc:
        def __init__(self, code: int, stdout: str):
            self.returncode = code
            self.stdout = stdout

    # Returncode 0 with path
    with patch("subprocess.run", return_value=DummyProc(0, "C:\\llama\\llama-server.exe\n")):
        assert _pick_executable_file() == "C:\\llama\\llama-server.exe"

    # Returncode 0 with empty stdout (cancelled)
    with patch("subprocess.run", return_value=DummyProc(0, "   \n")):
        assert _pick_executable_file() is None

    # Non-zero returncode
    with patch("subprocess.run", return_value=DummyProc(1, "error")):
        assert _pick_executable_file() is None

    # Exception / timeout
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=120)):
        assert _pick_executable_file() is None


def test_patch_settings_updates_server_manager_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify PATCH /api/settings updates server_manager.settings instance."""
    monkeypatch.chdir(tmp_path)
    mock_mgr = MockServerManager()
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path, env_path=tmp_path / ".env")
    client = AsgiClient(app)

    patch_body = json.dumps({"dpi": 240, "max_tokens": 4096}).encode("utf-8")
    status_code, _, body = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status_code == 200
    assert mock_mgr.settings.dpi == 240
    assert mock_mgr.settings.max_tokens == 4096


def test_settings_patch_mid_document_does_not_mutate_inflight_document_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that patching settings while a document is extracting does not mutate the in-flight job's JobConfig."""
    monkeypatch.chdir(tmp_path)
    started = threading.Event()
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    mock_eng.settings = Settings(dpi=150, max_image_dimension=1024)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path, env_path=tmp_path / ".env")
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("snapshot_test.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Start extraction
    status, _, _ = client.post(f"/api/documents/{doc_id}/extract")
    assert status == 202
    assert started.wait(timeout=5.0), "Processing did not start within timeout"

    # Document is now in-flight with initial snapshot settings (dpi=150, max_image_dimension=1024)
    # Patch settings mid-flight to new values
    patch_body = json.dumps({"dpi": 300, "max_image_dimension": 4096}).encode("utf-8")
    status, _, resp = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status == 200

    # Release gate so extraction completes
    gate.set()

    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS

    # The in-flight job must have executed with the pre-patch snapshot config
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.dpi == 150
    assert mock_eng.last_config.max_image_dimension == 1024

    orchestrator.stop()


def test_in_flight_patch_settings_isolation(tmp_path: Path) -> None:
    """Verify in-flight extraction retains initial settings snapshot while next job uses patched settings."""
    env_file = tmp_path / ".env"
    repo_env = Path(__file__).resolve().parent.parent / ".env"
    repo_pre = repo_env.read_bytes() if repo_env.exists() else None

    started = threading.Event()
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    mock_eng.settings = Settings(dpi=100, max_tokens=1024)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path, env_path=env_file)
    client = AsgiClient(app)

    png1 = _create_sample_png_bytes(50, 50)
    body1, ct1 = urllib3.encode_multipart_formdata({"file": ("inflight_1.png", png1, "image/png")})
    status, _, resp1 = client.post("/api/documents", headers={"content-type": ct1}, body=body1)
    assert status == 200
    doc1_id = json.loads(resp1.decode("utf-8"))["id"]

    client.post(f"/api/documents/{doc1_id}/extract")
    assert started.wait(timeout=5.0), "Document 1 processing did not start"

    patch_body = json.dumps({"dpi": 250, "max_tokens": 2048}).encode("utf-8")
    status, _, resp_patch = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status == 200
    assert json.loads(resp_patch.decode("utf-8"))["updated"] is True

    gate.set()
    for _ in range(50):
        j1 = orchestrator.get_job(doc1_id)
        if j1 and j1.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)
    assert j1 is not None and j1.status == JobStatus.SUCCESS

    assert len(mock_eng.executed_configs) >= 1
    assert mock_eng.executed_configs[0] is not None
    assert mock_eng.executed_configs[0].dpi == 100

    mock_eng.process_gate = None
    mock_eng.processing_started = None
    png2 = _create_sample_png_bytes(60, 60)
    body2, ct2 = urllib3.encode_multipart_formdata({"file": ("subsequent_2.png", png2, "image/png")})
    status, _, resp2 = client.post("/api/documents", headers={"content-type": ct2}, body=body2)
    assert status == 200
    doc2_id = json.loads(resp2.decode("utf-8"))["id"]

    client.post(f"/api/documents/{doc2_id}/extract")
    for _ in range(50):
        j2 = orchestrator.get_job(doc2_id)
        if j2 and j2.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)
    assert j2 is not None and j2.status == JobStatus.SUCCESS

    assert len(mock_eng.executed_configs) >= 2
    assert mock_eng.executed_configs[1] is not None
    assert mock_eng.executed_configs[1].dpi == 250
    assert mock_eng.settings.max_tokens == 2048

    assert env_file.exists()
    env_text = env_file.read_text(encoding="utf-8")
    assert "OCR_DPI='250'" in env_text
    assert "OCR_MAX_TOKENS='2048'" in env_text

    repo_post = repo_env.read_bytes() if repo_env.exists() else None
    assert repo_post == repo_pre

    orchestrator.stop()


def test_patch_settings_rejects_non_llama_server_binary(client: AsgiClient) -> None:
    """Verify PATCH /api/settings rejects executables not named llama-server."""
    body = json.dumps({"llama_server_path": "C:\\Windows\\System32\\cmd.exe"}).encode("utf-8")
    status, _, resp = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=body,
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert "Server binary must be named llama-server or llama-server.exe" in data["detail"]


def test_dialog_file_returns_409_when_locked(client: AsgiClient) -> None:
    """Verify POST /api/dialog/file returns 409 Conflict when a dialog is already open."""
    from web.app import _dialog_lock

    asyncio.run(_dialog_lock.acquire())
    try:
        status, _, body = client.post("/api/dialog/file")
        assert status == 409
        data = json.loads(body.decode("utf-8"))
        assert "already open" in data["detail"].lower()
    finally:
        if _dialog_lock.locked():
            _dialog_lock.release()


def test_health_reflects_runtime_mode_and_settings() -> None:
    """Verify /health reflects current runtime_mode and dynamic app settings."""
    settings = Settings(runtime_mode="custom", managed_backend_override="cuda")
    app = create_app(settings=settings)
    client = AsgiClient(app)
    status, _, resp = client.request("GET", "/health")
    assert status == 200
    data = json.loads(resp.decode("utf-8"))
    assert data["runtime_mode"] == "custom"
    assert data["managed_backend_override"] == "cuda"
    assert data["active_backend"] == "custom:cuda"


def test_patch_settings_returns_500_on_env_persistence_failure() -> None:
    """Verify PATCH /api/settings returns HTTP 500 if save_to_env fails with OSError."""
    app = create_app()
    with patch("config.settings.Settings.save_to_env", side_effect=OSError("Disk write failed")):
        client = AsgiClient(app)
        status, _, resp = client.request(
            "PATCH",
            "/api/settings",
            body=json.dumps({"dpi": 200}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert status == 500
        data = json.loads(resp.decode("utf-8"))
        assert "Failed to persist settings to disk" in data["detail"]


def test_diagnostics_run_closes_engine() -> None:
    """Verify run_diagnostics() closes the allocated engine in finally block."""
    from core.diagnostics import run_diagnostics
    from core.hardware import HardwareProfile
    settings = Settings()
    mock_engine = MagicMock(spec=OCREngine)

    report = run_diagnostics(
        settings=settings,
        server_prober=lambda *a, **k: (ServerStatus.READY, "Online"),
        runtime_checker=lambda *a, **k: True,
        runtime_path_getter=lambda *a, **k: Path("llama-server.exe"),
        hardware_detector=lambda: HardwareProfile(cpu_name="Test CPU", vram_mb=4096),
        engine_factory=lambda **k: mock_engine,
    )
    assert report is not None
    mock_engine.verify_backend.assert_called_once_with(force=True)
    mock_engine.close.assert_called_once()
