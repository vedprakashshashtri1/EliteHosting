from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class DetectedVariable(BaseModel):
    name: str
    is_secret: bool = False
    is_required: bool = False
    default_value: Optional[str] = None
    description: str = ""
    detected_in_file: Optional[str] = None

class DetectionResult(BaseModel):
    runtime: str
    framework: str
    entry_point: str
    dependency_file: Optional[str] = None
    process_type: str = "worker"  # worker, web, static, cron
    start_command: str
    build_command: Optional[str] = None
    listening_port: Optional[int] = None
    confidence: str = "high"  # high, medium, low
    detected_env_vars: List[DetectedVariable] = []
    suggested_alternatives: List[Dict[str, Any]] = []
    notes: List[str] = []

class BaseDetector(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        pass
