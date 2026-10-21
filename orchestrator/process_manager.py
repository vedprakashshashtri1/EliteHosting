import os
import sys
import time
import signal
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
import psutil

from elite_cloud.config import WORKSPACES_DIR, LOGS_DIR, PYTHON_BIN, NODE_BIN
from elite_cloud.storage.security import mask_secrets, decrypt_secret
from elite_cloud.storage.db import db
from elite_cloud.storage.models import DeploymentStatus

class ProcessInstance:
    def __init__(self, project_id: str, deployment_id: str, command: str, cwd: Path, env: Dict[str, str], port: Optional[int] = None):
        self.project_id = project_id
        self.deployment_id = deployment_id
        self.command = command
        self.cwd = cwd
        self.env = env
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.start_time: Optional[float] = None
        self.restart_count: int = 0
        self.is_intentionally_stopped: bool = False
        self.log_file = LOGS_DIR / f"{project_id}.log"
        self._threads: List[threading.Thread] = []

class ProcessManager:
    def __init__(self):
        self.instances: Dict[str, ProcessInstance] = {}  # project_id -> ProcessInstance
        self.lock = threading.Lock()
        self._monitor_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
        self._monitor_thread.start()

    def start_application(
        self,
        project_id: str,
        deployment_id: str,
        start_command: str,
        workspace_dir: Path,
        port: Optional[int] = None,
        additional_env: Optional[Dict[str, str]] = None,
        restart_count: int = 0
    ) -> ProcessInstance:
        with self.lock:
            # Stop existing instance if running
            if project_id in self.instances:
                self._stop_instance(self.instances[project_id], graceful=True)

            # Build environment variables
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PORT"] = str(port) if port else "8080"
            env["PATH"] = str(Path(PYTHON_BIN).parent) + os.pathsep + str(Path(PYTHON_BIN).parent / "Scripts") + os.pathsep + env.get("PATH", "")

            # Inject decrypted project secrets
            raw_vars = db.get_env_vars(project_id)
            known_secrets = []
            for v in raw_vars:
                key = v["key"]
                val = decrypt_secret(v.get("value_encrypted", ""))
                env[key] = val
                if v.get("is_secret"):
                    known_secrets.append(val)

            if additional_env:
                env.update(additional_env)

            # Replace start command tokens (e.g. python, node, $PORT)
            cmd = start_command
            if cmd.startswith("python "):
                cmd = f'"{PYTHON_BIN}" ' + cmd[7:]
            elif cmd.startswith("streamlit "):
                cmd = f'"{PYTHON_BIN}" -m streamlit ' + cmd[10:]
            elif cmd.startswith("uvicorn "):
                cmd = f'"{PYTHON_BIN}" -m uvicorn ' + cmd[8:]
            elif cmd.startswith("node "):
                cmd = f'"{NODE_BIN}" ' + cmd[5:]

            if port:
                cmd = cmd.replace("$PORT", str(port)).replace("%PORT%", str(port))

            instance = ProcessInstance(
                project_id=project_id,
                deployment_id=deployment_id,
                command=cmd,
                cwd=workspace_dir,
                env=env,
                port=port
            )
            instance.restart_count = restart_count

            # Launch process
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(workspace_dir),
                    env=env,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                )
                instance.process = proc
                instance.pid = proc.pid
                instance.start_time = time.time()
                self.instances[project_id] = instance

                # Stream logs
                t_out = threading.Thread(target=self._stream_pipe, args=(instance, proc.stdout, "stdout", known_secrets), daemon=True)
                t_err = threading.Thread(target=self._stream_pipe, args=(instance, proc.stderr, "stderr", known_secrets), daemon=True)
                t_out.start()
                t_err.start()
                instance._threads.extend([t_out, t_err])

                # Update database
                dep_doc = db.db.deployments.find_one({"_id": deployment_id})
                start_dt = dep_doc.get("created_at") if dep_doc else datetime.datetime.now(datetime.timezone.utc)
                db.update_deployment(deployment_id, {
                    "status": DeploymentStatus.RUNNING.value,
                    "pid": proc.pid,
                    "port": port,
                    "start_time": start_dt
                })
                db.update_project(project_id, {
                    "status": DeploymentStatus.RUNNING.value,
                    "active_deployment_id": deployment_id,
                    "listening_port": port
                })
                db.add_log(project_id, deployment_id, "INFO", "system", f"Process started successfully (PID: {proc.pid})")

                return instance
            except Exception as e:
                db.update_deployment(deployment_id, {
                    "status": DeploymentStatus.FAILED.value,
                    "error_message": str(e)
                })
                db.update_project(project_id, {"status": DeploymentStatus.FAILED.value})
                db.add_log(project_id, deployment_id, "ERROR", "system", f"Failed to start process: {e}")
                raise

    def stop_application(self, project_id: str) -> bool:
        with self.lock:
            instance = self.instances.get(project_id)
            if not instance:
                return False
            instance.is_intentionally_stopped = True
            self._stop_instance(instance, graceful=True)
            self.instances.pop(project_id, None)

            db.update_project(project_id, {"status": DeploymentStatus.STOPPED.value})
            if instance.deployment_id:
                db.update_deployment(instance.deployment_id, {"status": DeploymentStatus.STOPPED.value})
                db.add_log(project_id, instance.deployment_id, "INFO", "system", "Application stopped by user.")
            return True

    def restart_application(self, project_id: str) -> bool:
        with self.lock:
            instance = self.instances.get(project_id)
            if not instance:
                return False
            cmd = instance.command
            cwd = instance.cwd
            dep_id = instance.deployment_id
            port = instance.port

        self.stop_application(project_id)
        time.sleep(0.5)
        self.start_application(project_id, dep_id, cmd, cwd, port=port)
        return True

    def is_running(self, project_id: str) -> bool:
        instance = self.instances.get(project_id)
        if not instance or not instance.process:
            return False
        return instance.process.poll() is None

    def get_instance(self, project_id: str) -> Optional[ProcessInstance]:
        return self.instances.get(project_id)

    def _stop_instance(self, instance: ProcessInstance, graceful: bool = True):
        if not instance.process:
            return
        try:
            parent = psutil.Process(instance.process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
            try:
                parent.wait(timeout=3)
            except psutil.TimeoutExpired:
                for child in children:
                    try:
                        child.kill()
                    except Exception:
                        pass
                parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            try:
                instance.process.kill()
            except Exception:
                pass

    def _stream_pipe(self, instance: ProcessInstance, pipe, source: str, known_secrets: List[str]):
        try:
            with open(instance.log_file, "a", encoding="utf-8") as f:
                for line in iter(pipe.readline, ''):
                    if not line:
                        break
                    clean_line = line.rstrip()
                    if not clean_line:
                        continue
                    # Redact secrets
                    masked = mask_secrets(clean_line, known_secrets)
                    # Write to file
                    f.write(f"[{source.upper()}] {masked}\n")
                    f.flush()
                    # Write to DB
                    level = "ERROR" if source == "stderr" else "INFO"
                    db.add_log(instance.project_id, instance.deployment_id, level, source, masked)
        except Exception:
            pass
        finally:
            pipe.close()

    def _health_monitor_loop(self):
        while True:
            time.sleep(2)
            with self.lock:
                current_instances = list(self.instances.items())

            for project_id, instance in current_instances:
                if instance.process and not instance.is_intentionally_stopped:
                    poll = instance.process.poll()
                    if poll is not None:
                        # Process exited unexpectedly
                        exit_code = poll
                        level = "INFO" if exit_code == 0 else "ERROR"
                        db.add_log(project_id, instance.deployment_id, level, "system", f"Process exited with code {exit_code}")

                        # Auto-restart recovery (up to 3 times)
                        if exit_code != 0 and instance.restart_count < 3:
                            instance.restart_count += 1
                            db.add_log(project_id, instance.deployment_id, "WARN", "system", f"Auto-restarting crashed process (Attempt {instance.restart_count}/3)...")
                            time.sleep(1.5)
                            try:
                                self.start_application(
                                    project_id,
                                    instance.deployment_id,
                                    instance.command,
                                    instance.cwd,
                                    port=instance.port,
                                    restart_count=instance.restart_count
                                )
                            except Exception as re_err:
                                db.add_log(project_id, instance.deployment_id, "ERROR", "system", f"Auto-restart failed: {re_err}")
                        else:
                            db.update_project(project_id, {"status": DeploymentStatus.CRASHED.value})
                            db.update_deployment(instance.deployment_id, {
                                "status": DeploymentStatus.CRASHED.value,
                                "exit_code": exit_code
                            })
                            with self.lock:
                                self.instances.pop(project_id, None)

process_manager = ProcessManager()
