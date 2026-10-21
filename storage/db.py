import os
import uuid
import datetime
import logging
from typing import Optional, List, Dict, Any
from pymongo import MongoClient
import gridfs
import mongomock

from elite_cloud.config import MONGO_URI, MONGO_DB_NAME
from elite_cloud.storage.security import hash_password

logger = logging.getLogger("elite_cloud.db")

class DatabaseManager:
    def __init__(self, uri: str = MONGO_URI, db_name: str = MONGO_DB_NAME):
        self.uri = uri
        self.db_name = db_name
        self.client = None
        self.db = None
        self.fs = None
        self.is_mock = False
        self._init_connection()

    def _init_connection(self):
        try:
            # Attempt to connect to real MongoDB with short timeout
            real_client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
            real_client.admin.command('ping')
            self.client = real_client
            self.db = self.client[self.db_name]
            self.fs = gridfs.GridFS(self.db)
            self.is_mock = False
            logger.info("Connected successfully to MongoDB at %s", self.uri)
        except Exception as e:
            logger.warning("MongoDB not reachable (%s). Falling back to in-memory mongomock database.", e)
            try:
                import mongomock.gridfs
                mongomock.gridfs.enable_gridfs_integration()
            except Exception:
                pass
            self.client = mongomock.MongoClient()
            self.db = self.client[self.db_name]
            self.is_mock = True
            try:
                self.fs = gridfs.GridFS(self.db)
            except Exception:
                self.fs = None
            self._mock_files = {}
            
        self._init_indexes()
        self._seed_admin_user()

    def _init_indexes(self):
        try:
            self.db.users.create_index("username", unique=True)
            self.db.users.create_index("email", unique=True)
            self.db.projects.create_index("slug", unique=True)
            self.db.projects.create_index("owner_id")
            self.db.deployments.create_index("project_id")
            self.db.source_revisions.create_index("project_id")
            self.db.domain_mappings.create_index("domain", unique=True)
            self.db.environment_variables.create_index([("project_id", 1), ("key", 1)], unique=True)
            self.db.deployment_logs.create_index([("project_id", 1), ("timestamp", -1)])
            self.db.resource_metrics.create_index([("project_id", 1), ("timestamp", -1)])
            self.db.telegram_links.create_index("code", unique=True)
        except Exception as e:
            logger.debug("Index creation notice: %s", e)

    def _seed_admin_user(self):
        admin = self.db.users.find_one({"username": "admin"})
        if not admin:
            admin_user = {
                "_id": str(uuid.uuid4()),
                "username": "admin",
                "email": "admin@elitecloud.local",
                "password_hash": hash_password("admin123456"),
                "role": "admin",
                "is_active": True,
                "telegram_chat_id": None,
                "created_at": datetime.datetime.now(datetime.timezone.utc),
                "updated_at": datetime.datetime.now(datetime.timezone.utc)
            }
            self.db.users.insert_one(admin_user)
            logger.info("Default administrator seeded: admin / admin123456")

    # GridFS File Storage
    def save_archive_to_gridfs(self, file_bytes: bytes, filename: str) -> str:
        if self.fs:
            try:
                grid_in = self.fs.put(file_bytes, filename=filename)
                return str(grid_in)
            except Exception:
                pass
        fid = str(uuid.uuid4())
        self._mock_files[fid] = file_bytes
        return fid

    def get_archive_from_gridfs(self, gridfs_id: str) -> Optional[bytes]:
        if gridfs_id in getattr(self, "_mock_files", {}):
            return self._mock_files[gridfs_id]
        if self.fs:
            try:
                from bson.objectid import ObjectId
                oid = ObjectId(gridfs_id) if ObjectId.is_valid(gridfs_id) else gridfs_id
                return self.fs.get(oid).read()
            except Exception as e:
                logger.error("Failed to retrieve GridFS file %s: %s", gridfs_id, e)
        return None

    def delete_archive_from_gridfs(self, gridfs_id: str) -> bool:
        if gridfs_id in getattr(self, "_mock_files", {}):
            del self._mock_files[gridfs_id]
            return True
        if self.fs:
            try:
                from bson.objectid import ObjectId
                oid = ObjectId(gridfs_id) if ObjectId.is_valid(gridfs_id) else gridfs_id
                self.fs.delete(oid)
                return True
            except Exception:
                return False
        return False

    # Projects
    def create_project(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        if "_id" not in project_data:
            project_data["_id"] = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        project_data.setdefault("created_at", now)
        project_data.setdefault("updated_at", now)
        self.db.projects.insert_one(project_data)
        return project_data

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.db.projects.find_one({"_id": project_id})

    def get_project_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.db.projects.find_one({"slug": slug})

    def list_projects(self, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {}
        if owner_id:
            query["owner_id"] = owner_id
        return list(self.db.projects.find(query).sort("created_at", -1))

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> bool:
        updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        result = self.db.projects.update_one({"_id": project_id}, {"$set": updates})
        return result.modified_count > 0 or result.matched_count > 0

    def delete_project(self, project_id: str) -> bool:
        self.db.projects.delete_one({"_id": project_id})
        self.db.deployments.delete_many({"project_id": project_id})
        self.db.source_revisions.delete_many({"project_id": project_id})
        self.db.deployment_builds.delete_many({"project_id": project_id})
        self.db.environment_variables.delete_many({"project_id": project_id})
        self.db.deployment_logs.delete_many({"project_id": project_id})
        self.db.resource_metrics.delete_many({"project_id": project_id})
        self.db.domain_mappings.delete_many({"project_id": project_id})
        return True

    # Revisions & Builds
    def create_revision(self, revision_data: Dict[str, Any]) -> Dict[str, Any]:
        if "_id" not in revision_data:
            revision_data["_id"] = str(uuid.uuid4())
        revision_data.setdefault("created_at", datetime.datetime.now(datetime.timezone.utc))
        self.db.source_revisions.insert_one(revision_data)
        return revision_data

    def list_revisions(self, project_id: str) -> List[Dict[str, Any]]:
        return list(self.db.source_revisions.find({"project_id": project_id}).sort("revision_number", -1))

    def get_revision(self, revision_id: str) -> Optional[Dict[str, Any]]:
        return self.db.source_revisions.find_one({"_id": revision_id})

    # Deployments
    def create_deployment(self, deployment_data: Dict[str, Any]) -> Dict[str, Any]:
        if "_id" not in deployment_data:
            deployment_data["_id"] = str(uuid.uuid4())
        deployment_data.setdefault("created_at", datetime.datetime.now(datetime.timezone.utc))
        self.db.deployments.insert_one(deployment_data)
        return deployment_data

    def update_deployment(self, deployment_id: str, updates: Dict[str, Any]) -> bool:
        result = self.db.deployments.update_one({"_id": deployment_id}, {"$set": updates})
        return result.modified_count > 0 or result.matched_count > 0

    def get_deployment(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        return self.db.deployments.find_one({"_id": deployment_id})

    def list_deployments(self, project_id: str) -> List[Dict[str, Any]]:
        return list(self.db.deployments.find({"project_id": project_id}).sort("created_at", -1))

    # Environment Variables
    def set_env_var(self, project_id: str, key: str, value_encrypted: str, is_secret: bool = False, is_required: bool = False, description: str = ""):
        doc = {
            "project_id": project_id,
            "key": key,
            "value_encrypted": value_encrypted,
            "is_secret": is_secret,
            "is_required": is_required,
            "description": description,
            "environment": "production"
        }
        self.db.environment_variables.update_one(
            {"project_id": project_id, "key": key},
            {"$set": doc, "$setOnInsert": {"_id": str(uuid.uuid4())}},
            upsert=True
        )

    def get_env_vars(self, project_id: str) -> List[Dict[str, Any]]:
        return list(self.db.environment_variables.find({"project_id": project_id}))

    def delete_env_var(self, project_id: str, key: str) -> bool:
        res = self.db.environment_variables.delete_one({"project_id": project_id, "key": key})
        return res.deleted_count > 0

    # Logs & Metrics
    def add_log(self, project_id: str, deployment_id: Optional[str], level: str, source: str, message: str):
        log_entry = {
            "_id": str(uuid.uuid4()),
            "project_id": project_id,
            "deployment_id": deployment_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "level": level,
            "source": source,
            "message": message
        }
        self.db.deployment_logs.insert_one(log_entry)

    def get_logs(self, project_id: str, limit: int = 200, level: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {"project_id": project_id}
        if level:
            query["level"] = level
        return list(self.db.deployment_logs.find(query).sort("timestamp", -1).limit(limit))[::-1]

    def add_metric(self, project_id: str, deployment_id: Optional[str], cpu: float, memory: float, disk: float, uptime: float, restarts: int):
        metric = {
            "_id": str(uuid.uuid4()),
            "project_id": project_id,
            "deployment_id": deployment_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "cpu_percent": cpu,
            "memory_mb": memory,
            "disk_mb": disk,
            "uptime_seconds": uptime,
            "restarts": restarts
        }
        self.db.resource_metrics.insert_one(metric)

    def get_metrics(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self.db.resource_metrics.find({"project_id": project_id}).sort("timestamp", -1).limit(limit))[::-1]

    # Telegram Pairing Links
    def create_telegram_link(self, user_id: str, code: str, minutes_valid: int = 15) -> str:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes_valid)
        self.db.telegram_links.delete_many({"user_id": user_id})
        self.db.telegram_links.insert_one({
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "code": code,
            "expires_at": expires_at,
            "is_used": False
        })
        return code

    def verify_and_consume_telegram_link(self, code: str, telegram_chat_id: int) -> Optional[str]:
        now = datetime.datetime.now(datetime.timezone.utc)
        record = self.db.telegram_links.find_one({"code": code, "is_used": False})
        if not record:
            return None
        # Check expiration
        exp = record["expires_at"]
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.timezone.utc)
        if now > exp:
            return None
        
        user_id = record["user_id"]
        self.db.telegram_links.update_one({"_id": record["_id"]}, {"$set": {"is_used": True}})
        self.db.users.update_one({"_id": user_id}, {"$set": {"telegram_chat_id": telegram_chat_id}})
        return user_id

    def get_user_by_telegram_chat_id(self, chat_id: int) -> Optional[Dict[str, Any]]:
        return self.db.users.find_one({"telegram_chat_id": chat_id})

    # Domains
    def register_domain(self, project_id: str, domain: str, is_subdomain: bool = True, target_port: Optional[int] = None):
        self.db.domain_mappings.update_one(
            {"domain": domain},
            {"$set": {
                "project_id": project_id,
                "domain": domain,
                "is_subdomain": is_subdomain,
                "is_custom": not is_subdomain,
                "ssl_status": "active",
                "target_port": target_port,
                "created_at": datetime.datetime.now(datetime.timezone.utc)
            }},
            upsert=True
        )

    def get_domain_mapping(self, domain: str) -> Optional[Dict[str, Any]]:
        return self.db.domain_mappings.find_one({"domain": domain})

    def list_domains(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = {"project_id": project_id} if project_id else {}
        return list(self.db.domain_mappings.find(query))

    # Audit Logs
    def log_audit(self, user_id: Optional[str], action: str, target_type: str, target_id: Optional[str] = None, details: Dict[str, Any] = None, ip: Optional[str] = None):
        entry = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "ip_address": ip,
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
        }
        self.db.audit_logs.insert_one(entry)

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.db.audit_logs.find().sort("timestamp", -1).limit(limit))

# Global DB instance singleton
db = DatabaseManager()
