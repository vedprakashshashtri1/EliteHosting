import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class UserRole(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

class DeploymentStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    DEPLOYING = "deploying"
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    CRASHED = "crashed"
    FAILED = "failed"
    UNHEALTHY = "unhealthy"

class ProcessType(str, Enum):
    WEB = "web"
    WORKER = "worker"
    STATIC = "static"
    CRON = "cron"

class RuntimeType(str, Enum):
    PYTHON = "python"
    NODEJS = "nodejs"
    FRONTEND = "frontend"
    COMPILED = "compiled"
    DOCKER = "docker"

class User(BaseModel):
    id: str = Field(..., alias="_id")
    username: str
    email: str
    password_hash: str
    role: UserRole = UserRole.DEVELOPER
    is_active: bool = True
    telegram_chat_id: Optional[int] = None
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class Project(BaseModel):
    id: str = Field(..., alias="_id")
    name: str
    slug: str
    description: str = ""
    owner_id: str
    runtime: str = "python"
    framework: str = "generic"
    entry_point: str = "main.py"
    start_command: str = "python main.py"
    process_type: ProcessType = ProcessType.WORKER
    listening_port: Optional[int] = None
    subdomain: Optional[str] = None
    custom_domain: Optional[str] = None
    status: DeploymentStatus = DeploymentStatus.PENDING
    active_deployment_id: Optional[str] = None
    active_revision_id: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class SourceRevision(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    revision_number: int
    commit_message: str = "Initial commit"
    author_id: str
    gridfs_id: str
    file_count: int = 0
    total_size_bytes: int = 0
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class DeploymentBuild(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    revision_id: str
    status: DeploymentStatus = DeploymentStatus.PENDING
    build_logs: List[str] = []
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class Deployment(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    revision_id: str
    build_id: str
    status: DeploymentStatus = DeploymentStatus.PENDING
    port: Optional[int] = None
    pid: Optional[int] = None
    container_id: Optional[str] = None
    start_time: Optional[datetime.datetime] = None
    stop_time: Optional[datetime.datetime] = None
    exit_code: Optional[int] = None
    restart_count: int = 0
    health_status: str = "healthy"
    error_message: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class EnvironmentVariable(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    key: str
    value_encrypted: str
    is_secret: bool = False
    is_required: bool = False
    description: str = ""
    environment: str = "production"

    class Config:
        populate_by_name = True

class DomainMapping(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    domain: str
    is_subdomain: bool = True
    is_custom: bool = False
    ssl_status: str = "active"
    target_port: Optional[int] = None
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True

class DeploymentLog(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    deployment_id: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    level: str = "INFO"
    source: str = "app"
    message: str

    class Config:
        populate_by_name = True

class ResourceMetric(BaseModel):
    id: str = Field(..., alias="_id")
    project_id: str
    deployment_id: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    disk_mb: float = 0.0
    uptime_seconds: float = 0.0
    restarts: int = 0

    class Config:
        populate_by_name = True

class TelegramLink(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: str
    code: str
    expires_at: datetime.datetime
    is_used: bool = False

    class Config:
        populate_by_name = True

class AuditLog(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[str] = None
    details: Dict[str, Any] = {}
    ip_address: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    class Config:
        populate_by_name = True
