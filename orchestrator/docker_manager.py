import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from elite_cloud.orchestrator.process_manager import process_manager

class DockerManager:
    def __init__(self):
        self.is_docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        if not shutil.which("docker"):
            return False
        try:
            res = subprocess.run(["docker", "info"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    def deploy(
        self,
        project_id: str,
        deployment_id: str,
        workspace_dir: Path,
        start_command: str,
        port: Optional[int] = None,
        ram_limit_mb: int = 512,
        cpu_limit_pct: float = 100.0
    ):
        # If Docker is available and Dockerfile exists in workspace
        dockerfile = workspace_dir / "Dockerfile"
        if self.is_docker_available and dockerfile.exists():
            image_tag = f"elite_cloud_{project_id.lower()}:latest"
            # Build
            b_res = subprocess.run(["docker", "build", "-t", image_tag, "."], cwd=str(workspace_dir))
            if b_res.returncode == 0:
                # Run container
                port_flag = f"-p {port}:{port}" if port else ""
                cmd = f"docker run -d --rm --name {project_id} -m {ram_limit_mb}m --cpus={cpu_limit_pct/100.0} {port_flag} {image_tag}"
                subprocess.run(cmd, shell=True)
                return True

        # Seamless fallback to isolated process_manager
        return process_manager.start_application(
            project_id=project_id,
            deployment_id=deployment_id,
            start_command=start_command,
            workspace_dir=workspace_dir,
            port=port
        )

docker_manager = DockerManager()
