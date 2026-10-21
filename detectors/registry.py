from pathlib import Path
from typing import Optional, List
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.docker_detector import DockerDetector
from elite_cloud.detectors.python_detector import PythonDetector
from elite_cloud.detectors.nodejs_detector import NodejsDetector
from elite_cloud.detectors.frontend_detector import FrontendDetector
from elite_cloud.detectors.compiled_detector import CompiledDetector

class DetectorRegistry:
    def __init__(self):
        self.detectors: List[BaseDetector] = [
            DockerDetector(),
            PythonDetector(),
            NodejsDetector(),
            FrontendDetector(),
            CompiledDetector()
        ]

    def register(self, detector: BaseDetector):
        self.detectors.insert(0, detector)

    def detect(self, project_path: Path) -> DetectionResult:
        # Check if project root is nested inside a single subfolder
        effective_path = project_path
        subdirs = [d for d in project_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
        files = [f for f in project_path.iterdir() if f.is_file()]
        if len(subdirs) == 1 and len(files) == 0:
            effective_path = subdirs[0]

        for detector in self.detectors:
            try:
                res = detector.detect(effective_path)
                if res:
                    return res
            except Exception as e:
                pass

        # Fallback default
        return DetectionResult(
            runtime="generic",
            framework="generic-worker",
            entry_point="main.py" if (effective_path / "main.py").exists() else "index.js",
            process_type="worker",
            start_command="python main.py",
            confidence="low",
            notes=["No specific runtime detected. Defaulting to generic worker."]
        )

detector_registry = DetectorRegistry()
