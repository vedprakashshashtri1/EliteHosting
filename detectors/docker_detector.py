from pathlib import Path
from typing import Optional
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.variable_scanner import VariableScanner

class DockerDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "docker"

    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        dockerfile = project_path / "Dockerfile"
        compose_file = project_path / "docker-compose.yml"
        if not dockerfile.exists() and not compose_file.exists():
            return None

        detected_vars = VariableScanner.scan_directory(project_path)
        port = None
        if dockerfile.exists():
            try:
                for line in dockerfile.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip().upper().startswith("EXPOSE "):
                        parts = line.strip().split()
                        if len(parts) > 1 and parts[1].isdigit():
                            port = int(parts[1])
            except Exception:
                pass

        return DetectionResult(
            runtime="docker",
            framework="dockerfile",
            entry_point="Dockerfile" if dockerfile.exists() else "docker-compose.yml",
            dependency_file="Dockerfile" if dockerfile.exists() else None,
            process_type="web" if port else "worker",
            start_command="docker build -t app . && docker run -p $PORT:" + str(port or 8080) + " app",
            listening_port=port,
            confidence="high",
            detected_env_vars=detected_vars,
            notes=["Detected containerized Docker application"]
        )
