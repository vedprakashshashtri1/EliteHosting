import time
from pathlib import Path
from typing import Dict, Any, Optional
import psutil

class MetricsCollector:
    @staticmethod
    def get_process_metrics(pid: Optional[int], workspace_path: Optional[Path] = None) -> Dict[str, Any]:
        result = {
            "is_alive": False,
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "threads": 0,
            "uptime_seconds": 0.0,
            "disk_mb": 0.0,
            "status": "stopped"
        }

        # Calculate disk usage of workspace
        if workspace_path and workspace_path.exists():
            total_bytes = 0
            try:
                for entry in workspace_path.rglob('*'):
                    if entry.is_file():
                        total_bytes += entry.stat().st_size
                result["disk_mb"] = round(total_bytes / (1024 * 1024), 2)
            except Exception:
                pass

        if not pid:
            return result

        try:
            p = psutil.Process(pid)
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                result["is_alive"] = True
                result["status"] = "running"
                result["cpu_percent"] = round(p.cpu_percent(interval=0.05), 1)
                
                # Include children memory
                mem_bytes = p.memory_info().rss
                for child in p.children(recursive=True):
                    try:
                        mem_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                result["memory_mb"] = round(mem_bytes / (1024 * 1024), 2)
                result["threads"] = p.num_threads()
                result["uptime_seconds"] = round(time.time() - p.create_time(), 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            result["is_alive"] = False
            result["status"] = "crashed"

        return result

    @staticmethod
    def get_system_metrics() -> Dict[str, Any]:
        vm = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.1)
        disk = psutil.disk_usage('/') if not hasattr(psutil.disk_usage, 'c:') else psutil.disk_usage('C:\\')
        return {
            "system_cpu_percent": cpu_pct,
            "system_memory_used_mb": round(vm.used / (1024 * 1024), 1),
            "system_memory_total_mb": round(vm.total / (1024 * 1024), 1),
            "system_memory_percent": vm.percent,
            "system_disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "system_disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "system_disk_percent": disk.percent
        }
