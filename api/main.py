import os
import uuid
import time
import shutil
import random
import string
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import httpx

from elite_cloud.config import WORKSPACES_DIR, UPLOADS_DIR, TEMP_DIR, BASE_DOMAIN
from elite_cloud.storage.db import db
from elite_cloud.storage.models import (
    User, Project, SourceRevision, DeploymentStatus,
    ProcessType
)
from elite_cloud.detectors.base import DetectedVariable
from elite_cloud.storage.security import (
    hash_password, verify_password,
    create_access_token, decode_access_token,
    encrypt_secret, decrypt_secret, mask_secrets
)
from elite_cloud.detectors.registry import detector_registry
from elite_cloud.detectors.doc_generator import generate_deployment_guide
from elite_cloud.orchestrator.zip_validator import ZipValidator, ZipSecurityError
from elite_cloud.orchestrator.deployment_queue import orchestrator
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.metrics_collector import MetricsCollector
from elite_cloud.orchestrator.port_allocator import port_allocator
from elite_cloud.orchestrator.reverse_proxy import reverse_proxy_manager

app = FastAPI(title="Elite Cloud Hosting API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[Dict[str, Any]]:
    if not token:
        # Default to admin user for direct dashboard sessions if no bearer provided
        admin = db.db.users.find_one({"username": "admin"})
        return admin
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")
    user = db.db.users.find_one({"_id": payload.get("sub")})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ----------------- AUTH ROUTES ----------------- #
@app.post("/api/auth/register")
def register(username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    if db.db.users.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    user_doc = {
        "_id": user_id,
        "username": username,
        "email": email,
        "password_hash": hash_password(password),
        "role": "developer",
        "is_active": True,
        "telegram_chat_id": None,
        "created_at": time.time()
    }
    db.db.users.insert_one(user_doc)
    token = create_access_token({"sub": user_id, "username": username, "role": "developer"})
    return {"access_token": token, "token_type": "bearer", "user": {"id": user_id, "username": username, "role": "developer"}}

@app.post("/api/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = db.db.users.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": user["_id"], "username": user["username"], "role": user.get("role", "developer")})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/auth/me")
def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "id": user["_id"],
        "username": user["username"],
        "email": user["email"],
        "role": user.get("role", "developer"),
        "telegram_linked": bool(user.get("telegram_chat_id"))
    }

@app.post("/api/auth/telegram-pair")
def generate_telegram_pair_code(user: Dict[str, Any] = Depends(get_current_user)):
    code = "".join(random.choices(string.digits, k=6))
    db.create_telegram_link(user["_id"], code, minutes_valid=15)
    return {"code": code, "expires_in_minutes": 15, "bot_username": "EliteCloudManagerBot"}

# ----------------- ZIP UPLOAD & DETECTION ----------------- #
@app.post("/api/projects/upload-zip")
async def upload_zip_and_detect(
    file: UploadFile = File(...),
    project_name: Optional[str] = Form(None),
    user: Dict[str, Any] = Depends(get_current_user)
):
    temp_zip = TEMP_DIR / f"upload_{uuid.uuid4()}_{file.filename}"
    temp_extract = TEMP_DIR / f"extract_{uuid.uuid4()}"
    try:
        with open(temp_zip, "wb") as f:
            content = await file.read()
            f.write(content)

        file_count, total_bytes = ZipValidator.validate_and_extract(temp_zip, temp_extract)

        # Run automated detection
        detection = detector_registry.detect(temp_extract)

        # Derive project name & slug
        name = project_name or Path(file.filename).stem.replace("-main", "").replace("-master", "")
        slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        
        # Ensure slug uniqueness
        existing = db.get_project_by_slug(slug)
        if existing:
            slug = f"{slug}-{random.randint(100, 999)}"

        project_id = str(uuid.uuid4())
        workspace_dir = WORKSPACES_DIR / project_id
        shutil.move(str(temp_extract), str(workspace_dir))

        # Store archive in GridFS
        gridfs_id = db.save_archive_to_gridfs(content, file.filename)

        # Create project record
        project_data = {
            "_id": project_id,
            "name": name,
            "slug": slug,
            "owner_id": user["_id"],
            "runtime": detection.runtime,
            "framework": detection.framework,
            "entry_point": detection.entry_point,
            "start_command": detection.start_command,
            "process_type": detection.process_type,
            "listening_port": detection.listening_port,
            "subdomain": slug,
            "status": DeploymentStatus.PENDING.value
        }
        db.create_project(project_data)

        # Create initial Revision #1
        rev_id = str(uuid.uuid4())
        db.create_revision({
            "_id": rev_id,
            "project_id": project_id,
            "revision_number": 1,
            "commit_message": "Initial archive upload",
            "author_id": user["_id"],
            "gridfs_id": gridfs_id,
            "file_count": file_count,
            "total_size_bytes": total_bytes
        })
        db.update_project(project_id, {"active_revision_id": rev_id})

        # Save detected environment variables
        for v in detection.detected_env_vars:
            db.set_env_var(
                project_id=project_id,
                key=v.name,
                value_encrypted=encrypt_secret(v.default_value or ""),
                is_secret=v.is_secret,
                is_required=v.is_required,
                description=v.description
            )

        # Generate deployment guide
        guide = generate_deployment_guide(name, detection)

        return {
            "project_id": project_id,
            "name": name,
            "slug": slug,
            "detection": detection.dict(),
            "deployment_guide": guide,
            "file_count": file_count,
            "total_bytes": total_bytes
        }
    finally:
        if temp_zip.exists():
            temp_zip.unlink()
        if temp_extract.exists():
            shutil.rmtree(temp_extract, ignore_errors=True)

# ----------------- PROJECTS & DEPLOYMENT CONTROLS ----------------- #
@app.get("/api/projects")
def list_projects(user: Dict[str, Any] = Depends(get_current_user)):
    owner_id = user["_id"] if user.get("role") != "admin" else None
    projects = db.list_projects(owner_id=owner_id)
    # Augment with live status
    for p in projects:
        p_id = p["_id"]
        instance = process_manager.get_instance(p_id)
        p["is_running"] = process_manager.is_running(p_id)
        if p["is_running"]:
            p["metrics"] = MetricsCollector.get_process_metrics(instance.pid if instance else None, WORKSPACES_DIR / p_id)
    return projects

@app.get("/api/projects/{project_id}")
def get_project(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    instance = process_manager.get_instance(project_id)
    p["is_running"] = process_manager.is_running(project_id)
    p["metrics"] = MetricsCollector.get_process_metrics(instance.pid if instance else None, WORKSPACES_DIR / project_id)
    p["variables"] = get_variables(project_id, user)
    return p

@app.put("/api/projects/{project_id}")
def update_project(project_id: str, updates: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
    db.update_project(project_id, updates)
    return db.get_project(project_id)

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    process_manager.stop_application(project_id)
    port_allocator.release_port(project_id)
    shutil.rmtree(WORKSPACES_DIR / project_id, ignore_errors=True)
    db.delete_project(project_id)
    return {"success": True}

@app.post("/api/projects/{project_id}/deploy")
def deploy_project(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    dep = orchestrator.deploy_project(project_id)
    return {"success": True, "deployment": dep}

@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    orchestrator.stop_project(project_id)
    return {"success": True, "status": "stopped"}

@app.post("/api/projects/{project_id}/restart")
def restart_project(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    orchestrator.restart_project(project_id)
    return {"success": True, "status": "restarted"}

@app.post("/api/projects/{project_id}/rollback")
def rollback_project(project_id: str, target_revision_id: str = Form(...), user: Dict[str, Any] = Depends(get_current_user)):
    dep = orchestrator.rollback_project(project_id, target_revision_id)
    return {"success": True, "deployment": dep}

# ----------------- ENVIRONMENT VARIABLES ----------------- #
@app.get("/api/projects/{project_id}/variables")
def get_variables(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    raw = db.get_env_vars(project_id)
    result = []
    for r in raw:
        val = decrypt_secret(r.get("value_encrypted", ""))
        result.append({
            "key": r["key"],
            "value": "••••••••••••" if r.get("is_secret") else val,
            "raw_value": val,
            "is_secret": r.get("is_secret", False),
            "is_required": r.get("is_required", False),
            "description": r.get("description", "")
        })
    return result

@app.post("/api/projects/{project_id}/variables")
def set_variable(
    project_id: str,
    key: str = Form(...),
    value: str = Form(...),
    is_secret: bool = Form(False),
    is_required: bool = Form(False),
    description: str = Form(""),
    user: Dict[str, Any] = Depends(get_current_user)
):
    db.set_env_var(
        project_id=project_id,
        key=key,
        value_encrypted=encrypt_secret(value),
        is_secret=is_secret,
        is_required=is_required,
        description=description
    )
    return {"success": True}

@app.delete("/api/projects/{project_id}/variables/{key}")
def delete_variable(project_id: str, key: str, user: Dict[str, Any] = Depends(get_current_user)):
    db.delete_env_var(project_id, key)
    return {"success": True}

# ----------------- FILE MANAGER ----------------- #
@app.get("/api/projects/{project_id}/files/tree")
def get_file_tree(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    ws = WORKSPACES_DIR / project_id
    if not ws.exists():
        return []

    def build_tree(path: Path) -> List[Dict[str, Any]]:
        items = []
        for p in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                continue
            item = {
                "name": p.name,
                "path": str(p.relative_to(ws)).replace("\\", "/"),
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.is_file() else None
            }
            if p.is_dir():
                item["children"] = build_tree(p)
            items.append(item)
        return items

    return build_tree(ws)

@app.get("/api/projects/{project_id}/files/content")
def get_file_content(project_id: str, path: str = Query(...), user: Dict[str, Any] = Depends(get_current_user)):
    target = (WORKSPACES_DIR / project_id / path).resolve()
    ws_canonical = (WORKSPACES_DIR / project_id).resolve()
    if not str(target).startswith(str(ws_canonical)) or not target.is_file():
        raise HTTPException(status_code=400, detail="Invalid file path")
    try:
        return {"content": target.read_text(encoding="utf-8", errors="ignore")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

@app.post("/api/projects/{project_id}/files/content")
def save_file_content(
    project_id: str,
    path: str = Form(...),
    content: str = Form(...),
    commit_message: str = Form("Edit file via browser"),
    user: Dict[str, Any] = Depends(get_current_user)
):
    ws_canonical = (WORKSPACES_DIR / project_id).resolve()
    target = (ws_canonical / path).resolve()
    if not str(target).startswith(str(ws_canonical)):
        raise HTTPException(status_code=400, detail="Invalid file path")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    # Snapshot into GridFS as new revision
    temp_zip = TEMP_DIR / f"rev_{uuid.uuid4()}.zip"
    try:
        ZipValidator.create_zip_from_dir(ws_canonical, temp_zip)
        zip_bytes = temp_zip.read_bytes()
        gridfs_id = db.save_archive_to_gridfs(zip_bytes, f"{project_id}_rev.zip")

        # Create revision record
        rev_count = len(db.list_revisions(project_id))
        new_rev = db.create_revision({
            "_id": str(uuid.uuid4()),
            "project_id": project_id,
            "revision_number": rev_count + 1,
            "commit_message": commit_message,
            "author_id": user["_id"],
            "gridfs_id": gridfs_id,
            "file_count": sum(1 for _ in ws_canonical.rglob('*') if _.is_file()),
            "total_size_bytes": len(zip_bytes)
        })
        db.update_project(project_id, {"active_revision_id": new_rev["_id"]})
        return {"success": True, "revision": new_rev}
    finally:
        if temp_zip.exists():
            temp_zip.unlink()

@app.get("/api/projects/{project_id}/files/download-zip")
def download_project_zip(project_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    ws = WORKSPACES_DIR / project_id
    if not ws.exists():
        raise HTTPException(status_code=404, detail="Project files not found")

    temp_zip = TEMP_DIR / f"download_{project_id}.zip"
    ZipValidator.create_zip_from_dir(ws, temp_zip)
    return FileResponse(temp_zip, filename=f"{project_id}.zip", media_type="application/zip")

# ----------------- LOGS & METRICS ----------------- #
@app.get("/api/projects/{project_id}/logs")
def get_logs(project_id: str, limit: int = 100, level: Optional[str] = None):
    return db.get_logs(project_id, limit=limit, level=level)

@app.get("/api/system/metrics")
def get_system_metrics():
    return MetricsCollector.get_system_metrics()

# ----------------- BUILT-IN DYNAMIC REVERSE PROXY ----------------- #
@app.api_route("/proxy/{subdomain}/{proxy_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def reverse_proxy_endpoint(subdomain: str, proxy_path: str, request: Request):
    # Lookup domain mapping or project with this subdomain
    domain = f"{subdomain}.{BASE_DOMAIN}"
    mapping = db.get_domain_mapping(domain)
    target_port = None
    if mapping:
        target_port = mapping.get("target_port")
    else:
        proj = db.get_project_by_slug(subdomain)
        if proj:
            target_port = proj.get("listening_port")

    if not target_port:
        raise HTTPException(status_code=404, detail=f"No running application found for subdomain '{subdomain}'")

    url = f"http://127.0.0.1:{target_port}/{proxy_path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Forward request
    async with httpx.AsyncClient(timeout=60.0) as client:
        req_body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)
        try:
            res = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=req_body
            )
            return Response(content=res.content, status_code=res.status_code, headers=dict(res.headers))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Bad Gateway: Unable to connect to application on port {target_port} ({e})")
