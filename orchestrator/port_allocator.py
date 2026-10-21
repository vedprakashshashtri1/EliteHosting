import socket
import threading
from typing import Dict, Optional
from elite_cloud.config import APP_PORT_MIN, APP_PORT_MAX

class PortAllocator:
    def __init__(self, min_port: int = APP_PORT_MIN, max_port: int = APP_PORT_MAX):
        self.min_port = min_port
        self.max_port = max_port
        self.allocated_ports: Dict[str, int] = {}  # project_id -> port
        self.lock = threading.Lock()

    def is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', port))
                return True
            except OSError:
                return False

    def allocate_port(self, project_id: str) -> int:
        with self.lock:
            # If already assigned and free, keep it
            if project_id in self.allocated_ports:
                existing = self.allocated_ports[project_id]
                if self.is_port_available(existing):
                    return existing

            used_ports = set(self.allocated_ports.values())
            for candidate in range(self.min_port, self.max_port + 1):
                if candidate not in used_ports and self.is_port_available(candidate):
                    self.allocated_ports[project_id] = candidate
                    return candidate

            raise RuntimeError(f"No available ports in range {self.min_port}-{self.max_port}")

    def release_port(self, project_id: str) -> Optional[int]:
        with self.lock:
            return self.allocated_ports.pop(project_id, None)

    def get_port(self, project_id: str) -> Optional[int]:
        return self.allocated_ports.get(project_id)

port_allocator = PortAllocator()
