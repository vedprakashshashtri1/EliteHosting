import time
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from elite_cloud.config import WORKSPACES_DIR, PYTHON_BIN, NODE_BIN, BASE_DOMAIN
from elite_cloud.storage.db import db
from elite_cloud.storage.models import DeploymentStatus, ProcessType
from elite_cloud.orchestrator.zip_validator import ZipValidator
from elite_cloud.orchestrator.port_allocator import port_allocator
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.reverse_proxy import reverse_proxy_manager

class DeploymentOrchestrator:
    def deploy_project(self, project_id: str, revision_id: Optional[str] = None) -> Dict[str, Any]:
        project = db.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        # Determine revision
        if not revision_id:
            revision_id = project.get("active_revision_id")
        if not revision_id:
            revisions = db.list_revisions(project_id)
            if not revisions:
                raise ValueError("Project has no source revisions to deploy.")
            revision_id = revisions[0]["_id"]

        revision = db.get_revision(revision_id)
        if not revision:
            raise ValueError(f"Revision {revision_id} not found.")

        # Create Build record
        build_id = str(uuid.uuid4())
        deployment_id = str(uuid.uuid4())
        workspace_dir = WORKSPACES_DIR / project_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        db.db.deployment_builds.insert_one({
            "_id": build_id,
            "project_id": project_id,
            "revision_id": revision_id,
            "status": DeploymentStatus.BUILDING.value,
            "build_logs": [],
            "created_at": time.time()
        })
        db.update_project(project_id, {"status": DeploymentStatus.BUILDING.value})
        db.add_log(project_id, deployment_id, "INFO", "build", f"Beginning build for revision #{revision.get('revision_number', 1)}...")

        # 1. Fetch source from GridFS and extract into workspace
        gridfs_id = revision.get("gridfs_id")
        if gridfs_id:
            archive_bytes = db.get_archive_from_gridfs(gridfs_id)
            if archive_bytes:
                temp_zip = workspace_dir.parent / f"temp_{revision_id}.zip"
                try:
                    temp_zip.write_bytes(archive_bytes)
                    ZipValidator.validate_and_extract(temp_zip, workspace_dir)
                    db.add_log(project_id, deployment_id, "INFO", "build", "Source code extracted successfully.")
                finally:
                    if temp_zip.exists():
                        temp_zip.unlink()

        # 2. Dependency Installation
        build_start = time.time()
        req_file = workspace_dir / "requirements.txt"
        pkg_file = workspace_dir / "package.json"

        # Python dependencies
        if req_file.exists():
            db.add_log(project_id, deployment_id, "INFO", "build", "Installing Python dependencies from requirements.txt...")
            try:
                pip_proc = subprocess.run(
                    [PYTHON_BIN, "-m", "pip", "install", "-r", "requirements.txt", "--no-warn-script-location"],
                    cwd=str(workspace_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=300
                )
                if pip_proc.returncode != 0:
                    db.add_log(project_id, deployment_id, "WARN", "build", f"pip install warning: {pip_proc.stderr[:300]}")
                else:
                    db.add_log(project_id, deployment_id, "INFO", "build", "Dependencies installed successfully.")
            except Exception as e:
                db.add_log(project_id, deployment_id, "WARN", "build", f"pip install notice: {e}")

        # Node dependencies
        elif pkg_file.exists():
            db.add_log(project_id, deployment_id, "INFO", "build", "Installing Node.js dependencies...")
            try:
                npm_cmd = "npm.cmd" if subprocess.os.name == "nt" else "npm"
                subprocess.run([npm_cmd, "install", "--production"], cwd=str(workspace_dir), timeout=300)
                db.add_log(project_id, deployment_id, "INFO", "build", "Node packages installed.")
            except Exception as e:
                db.add_log(project_id, deployment_id, "WARN", "build", f"npm install notice: {e}")

        # Optional build step (e.g. frontend vite build)
        build_cmd = project.get("build_command")
        if build_cmd:
            db.add_log(project_id, deployment_id, "INFO", "build", f"Executing build command: {build_cmd}")
            try:
                subprocess.run(build_cmd, cwd=str(workspace_dir), shell=True, timeout=300)
            except Exception as b_err:
                db.add_log(project_id, deployment_id, "WARN", "build", f"Build command warning: {b_err}")

        # 3. Port Allocation for web processes
        process_type = project.get("process_type", "worker")
        allocated_port = None
        if process_type in ("web", "static"):
            allocated_port = port_allocator.allocate_port(project_id)
            db.add_log(project_id, deployment_id, "INFO", "system", f"Allocated internal HTTP port: {allocated_port}")

            # Register subdomain
            subdomain = project.get("subdomain") or project.get("slug")
            if subdomain:
                domain = f"{subdomain}.{BASE_DOMAIN}"
                reverse_proxy_manager.register_domain(project_id, domain, is_subdomain=True, target_port=allocated_port)

        # 4. Create Deployment record
        db.create_deployment({
            "_id": deployment_id,
            "project_id": project_id,
            "revision_id": revision_id,
            "build_id": build_id,
            "status": DeploymentStatus.DEPLOYING.value,
            "port": allocated_port,
            "restart_count": 0,
            "health_status": "healthy"
        })

        # 5. Start Application
        start_cmd = project.get("start_command") or "python main.py"
        instance = process_manager.start_application(
            project_id=project_id,
            deployment_id=deployment_id,
            start_command=start_cmd,
            workspace_dir=workspace_dir,
            port=allocated_port
        )

        db.update_project(project_id, {
            "active_deployment_id": deployment_id,
            "active_revision_id": revision_id,
            "listening_port": allocated_port,
            "status": DeploymentStatus.RUNNING.value
        })

        db.add_log(project_id, deployment_id, "INFO", "system", f"Deployment {deployment_id[:8]} is now active.")
        return db.get_deployment(deployment_id)

    def stop_project(self, project_id: str) -> bool:
        process_manager.stop_application(project_id)
        port_allocator.release_port(project_id)
        return True

    def restart_project(self, project_id: str) -> bool:
        project = db.get_project(project_id)
        if not project:
            return False
        return self.deploy_project(project_id, project.get("active_revision_id"))

    def rollback_project(self, project_id: str, target_revision_id: str) -> Dict[str, Any]:
        return self.deploy_project(project_id, target_revision_id)

orchestrator = DeploymentOrchestrator()
