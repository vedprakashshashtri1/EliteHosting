import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import os
import io
import time
import uuid
import zipfile
import pytest
from fastapi.testclient import TestClient

from elite_cloud.config import TEMP_DIR, WORKSPACES_DIR
from elite_cloud.storage.security import (
    hash_password, verify_password,
    create_access_token, decode_access_token,
    encrypt_secret, decrypt_secret, mask_secrets
)
from elite_cloud.storage.db import db
from elite_cloud.detectors.registry import detector_registry
from elite_cloud.detectors.variable_scanner import VariableScanner
from elite_cloud.orchestrator.zip_validator import ZipValidator, ZipSecurityError
from elite_cloud.orchestrator.port_allocator import port_allocator
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.deployment_queue import orchestrator
from elite_cloud.api.main import app

client = TestClient(app)

# ----------------- 1. SECURITY & CRYPTOGRAPHY TESTS ----------------- #
def test_password_hashing():
    pw = "SecretP@ssw0rd!123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

def test_fernet_secret_encryption():
    raw_secret = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    encrypted = encrypt_secret(raw_secret)
    assert encrypted != raw_secret
    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_secret

def test_secret_masking_in_logs():
    sample_log = "Connected to bot 123456789:ABCdefGHIjklMNOpqrsTUVwxyz with Bearer eyJhbGciOiJIUzI1NiJ9"
    masked = mask_secrets(sample_log)
    assert "123456789:ABCdefGHIjklMNOpqrsTUVwxyz" not in masked
    assert "[REDACTED_TELEGRAM_TOKEN]" in masked
    assert "[REDACTED_BEARER_TOKEN]" in masked

def test_jwt_generation_and_decode():
    token = create_access_token({"sub": "user_123", "role": "admin"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload.get("sub") == "user_123"
    assert payload.get("role") == "admin"

# ----------------- 2. ZIP VALIDATION & SAFETY TESTS ----------------- #
def test_safe_zip_extraction(tmp_path):
    zip_file = tmp_path / "valid.zip"
    dest_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("main.py", "print('hello world')")
        zf.writestr("requirements.txt", "fastapi\nuvicorn\n")

    count, total_bytes = ZipValidator.validate_and_extract(zip_file, dest_dir)
    assert count == 2
    assert (dest_dir / "main.py").exists()
    assert (dest_dir / "requirements.txt").exists()

def test_zip_slip_rejection(tmp_path):
    malicious_zip = tmp_path / "malicious.zip"
    dest_dir = tmp_path / "dest"

    with zipfile.ZipFile(malicious_zip, "w") as zf:
        # Malicious entry with path traversal
        zf.writestr("../../evil.txt", "malicious payload")

    with pytest.raises(ZipSecurityError, match="path traversal"):
        ZipValidator.validate_and_extract(malicious_zip, dest_dir)

# ----------------- 3. RUNTIME DETECTORS & VARIABLE SCANNER ----------------- #
def test_python_telegram_bot_detection(tmp_path):
    bot_dir = tmp_path / "my_tg_bot"
    bot_dir.mkdir()
    (bot_dir / "bot.py").write_text("from telegram.ext import Application\nimport os\nTOKEN = os.getenv('BOT_TOKEN')\n")
    (bot_dir / "requirements.txt").write_text("python-telegram-bot>=20.0\n")

    res = detector_registry.detect(bot_dir)
    assert res.runtime == "python"
    assert res.framework == "telegram-bot"
    assert res.entry_point == "bot.py"
    assert res.process_type == "worker"
    assert any(v.name == "BOT_TOKEN" and v.is_secret for v in res.detected_env_vars)

def test_streamlit_detection(tmp_path):
    st_dir = tmp_path / "my_st_app"
    st_dir.mkdir()
    (st_dir / "app.py").write_text("import streamlit as st\nst.title('My App')\n")
    (st_dir / "requirements.txt").write_text("streamlit\n")

    res = detector_registry.detect(st_dir)
    assert res.runtime == "python"
    assert res.framework == "streamlit"
    assert res.entry_point == "app.py"
    assert res.process_type == "web"
    assert res.listening_port == 8501

def test_nodejs_express_detection(tmp_path):
    node_dir = tmp_path / "my_express_api"
    node_dir.mkdir()
    (node_dir / "package.json").write_text('{"name": "api", "dependencies": {"express": "^4.18.2"}, "scripts": {"start": "node index.js"}}')
    (node_dir / "index.js").write_text('const express = require("express"); const port = process.env.PORT || 3000;')

    res = detector_registry.detect(node_dir)
    assert res.runtime == "nodejs"
    assert res.framework == "express"
    assert res.process_type == "web"
    assert res.listening_port == 3000

def test_static_html_detection(tmp_path):
    static_dir = tmp_path / "static_site"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!DOCTYPE html><html><body><h1>Hello</h1></body></html>")

    res = detector_registry.detect(static_dir)
    assert res.runtime == "frontend"
    assert res.framework == "static-html"
    assert res.process_type == "static"

# ----------------- 4. PORT ALLOCATOR & DATABASE STORAGE ----------------- #
def test_port_allocation():
    p1 = "proj_test_1"
    p2 = "proj_test_2"
    port1 = port_allocator.allocate_port(p1)
    port2 = port_allocator.allocate_port(p2)
    assert port1 != port2
    assert port1 >= 8100
    assert port2 >= 8100
    port_allocator.release_port(p1)
    port_allocator.release_port(p2)

def test_gridfs_storage():
    dummy_archive = b"PK\x03\x04dummy_zip_content"
    gridfs_id = db.save_archive_to_gridfs(dummy_archive, "test.zip")
    assert gridfs_id is not None
    fetched = db.get_archive_from_gridfs(gridfs_id)
    assert fetched == dummy_archive
    db.delete_archive_from_gridfs(gridfs_id)

# ----------------- 5. DEPLOYMENT LIFECYCLE & PROCESS SUPERVISION ----------------- #
def test_process_lifecycle(tmp_path):
    proj_id = f"test_proj_{uuid.uuid4().hex[:8]}"
    ws = WORKSPACES_DIR / proj_id
    ws.mkdir(parents=True, exist_ok=True)
    
    # Simple python worker that runs in a loop
    script = (
        "import time, sys\n"
        "print('Worker initialized', flush=True)\n"
        "time.sleep(1)\n"
        "print('Worker tick', flush=True)\n"
    )
    (ws / "worker.py").write_text(script)

    db.create_project({
        "_id": proj_id,
        "name": "Test Worker App",
        "slug": proj_id,
        "owner_id": "test_owner",
        "runtime": "python",
        "framework": "python-worker",
        "entry_point": "worker.py",
        "start_command": "python worker.py",
        "process_type": "worker"
    })

    # Start
    instance = process_manager.start_application(
        project_id=proj_id,
        deployment_id="dep_test_1",
        start_command="python worker.py",
        workspace_dir=ws
    )
    assert instance.pid is not None
    assert process_manager.is_running(proj_id) is True

    time.sleep(0.5)

    # Stop
    stopped = process_manager.stop_application(proj_id)
    assert stopped is True
    assert process_manager.is_running(proj_id) is False

    # Cleanup
    db.delete_project(proj_id)

# ----------------- 6. FASTAPI ENDPOINTS INTEGRATION ----------------- #
def test_api_system_metrics():
    res = client.get("/api/system/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "system_cpu_percent" in data
    assert "system_memory_used_mb" in data

def test_api_project_list():
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
