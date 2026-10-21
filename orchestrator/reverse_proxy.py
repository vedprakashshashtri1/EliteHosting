from typing import List, Dict, Any, Optional
from elite_cloud.config import BASE_DOMAIN, API_PORT
from elite_cloud.storage.db import db

RESERVED_SUBDOMAINS = {
    "admin", "api", "dashboard", "internal", "status", "health",
    "bot", "mail", "ftp", "localhost", "elite", "cloud", "auth",
    "login", "register", "system", "metrics", "test", "demo"
}

class ReverseProxyManager:
    @staticmethod
    def is_subdomain_available(subdomain: str, current_project_id: Optional[str] = None) -> bool:
        clean = subdomain.strip().lower()
        if clean in RESERVED_SUBDOMAINS:
            return False
        if not clean.replace("-", "").isalnum():
            return False

        full_domain = f"{clean}.{BASE_DOMAIN}"
        existing = db.get_domain_mapping(full_domain)
        if not existing:
            return True
        if current_project_id and existing.get("project_id") == current_project_id:
            return True
        return False

    @staticmethod
    def register_domain(
        project_id: str,
        domain: str,
        is_subdomain: bool = True,
        target_port: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create or update the routing record used by proxy config generators."""
        existing = db.get_domain_mapping(domain)
        if existing and existing.get("project_id") != project_id:
            raise ValueError(f"Domain is already assigned: {domain}")

        db.register_domain(
            project_id=project_id,
            domain=domain,
            is_subdomain=is_subdomain,
            target_port=target_port
        )
        return db.get_domain_mapping(domain) or {
            "project_id": project_id,
            "domain": domain,
            "is_subdomain": is_subdomain,
            "target_port": target_port
        }

    @staticmethod
    def generate_caddyfile() -> str:
        """Generates dynamic Caddyfile config for all active domain mappings."""
        lines = [
            "# Auto-generated Caddy configuration by Elite Cloud Hosting",
            f"{{",
            f"    admin off",
            f"}}",
            ""
        ]

        # Route API and Dashboard
        lines.append(f"api.{BASE_DOMAIN} {{")
        lines.append(f"    reverse_proxy 127.0.0.1:{API_PORT}")
        lines.append("}\n")

        # Route User Applications
        domains = db.list_domains()
        for d in domains:
            domain_name = d.get("domain")
            port = d.get("target_port")
            if domain_name and port:
                lines.append(f"{domain_name} {{")
                lines.append(f"    reverse_proxy 127.0.0.1:{port}")
                lines.append("}\n")

        return "\n".join(lines)

    @staticmethod
    def generate_traefik_config() -> Dict[str, Any]:
        """Generates dynamic Traefik YAML configuration."""
        routers = {}
        services = {}
        domains = db.list_domains()
        for d in domains:
            domain_name = d.get("domain")
            port = d.get("target_port")
            if domain_name and port:
                name = domain_name.replace(".", "-")
                routers[name] = {
                    "rule": f"Host(`{domain_name}`)",
                    "service": name
                }
                services[name] = {
                    "loadBalancer": {
                        "servers": [{"url": f"http://127.0.0.1:{port}"}]
                    }
                }

        return {
            "http": {
                "routers": routers,
                "services": services
            }
        }

reverse_proxy_manager = ReverseProxyManager()
