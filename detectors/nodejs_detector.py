import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.variable_scanner import VariableScanner

COMMON_NODE_ENTRIES = ["index.js", "server.js", "app.js", "main.js", "index.ts", "server.ts", "app.ts"]

class NodejsDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "nodejs"

    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        pkg_file = project_path / "package.json"
        js_files = list(project_path.glob("*.js")) + list(project_path.glob("*.ts"))
        
        if not pkg_file.exists() and not js_files:
            return None

        # Exclude pure static frontends (handled by FrontendDetector) if it's vite/react without server
        is_next = False
        scripts = {}
        deps = {}
        dev_deps = {}
        pkg_main = None

        if pkg_file.exists():
            try:
                data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                scripts = data.get("scripts", {})
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                pkg_main = data.get("main")
            except Exception:
                pass

        all_deps = {**deps, **dev_deps}

        # Check for Next.js
        if "next" in all_deps:
            detected_vars = VariableScanner.scan_directory(project_path)
            return DetectionResult(
                runtime="nodejs",
                framework="nextjs",
                entry_point="package.json",
                dependency_file="package.json",
                process_type="web",
                start_command="npm run start",
                build_command="npm run build",
                listening_port=3000,
                confidence="high",
                detected_env_vars=detected_vars,
                notes=["Detected Next.js fullstack application"]
            )

        # Check for Telegram bot (telegraf, grammy, node-telegram-bot-api)
        is_telegram = any(p in all_deps for p in ["telegraf", "grammy", "node-telegram-bot-api"])
        is_discord = "discord.js" in all_deps
        is_express = "express" in all_deps
        is_fastify = "fastify" in all_deps
        is_nest = "@nestjs/core" in all_deps

        # Skip if this is a purely frontend client project (vite/react/vue without backend)
        if ("vite" in all_deps or "react-scripts" in all_deps) and not (is_express or is_telegram or is_discord or is_fastify or is_nest):
            return None

        # Select entry point
        primary_entry = pkg_main or "index.js"
        if not (project_path / primary_entry).exists():
            for c in COMMON_NODE_ENTRIES:
                if (project_path / c).exists():
                    primary_entry = c
                    break

        framework = "nodejs-generic"
        process_type = "worker"
        default_port = None
        start_cmd = f"node {primary_entry}"

        if "start" in scripts:
            start_cmd = "npm start"

        if is_telegram:
            framework = "nodejs-telegram-bot"
            process_type = "worker"
        elif is_discord:
            framework = "nodejs-discord-bot"
            process_type = "worker"
        elif is_express:
            framework = "express"
            process_type = "web"
            default_port = 3000
        elif is_nest:
            framework = "nest"
            process_type = "web"
            default_port = 3000
        elif is_fastify:
            framework = "fastify"
            process_type = "web"
            default_port = 3000

        detected_vars = VariableScanner.scan_directory(project_path)

        return DetectionResult(
            runtime="nodejs",
            framework=framework,
            entry_point=primary_entry,
            dependency_file="package.json" if pkg_file.exists() else None,
            process_type=process_type,
            start_command=start_cmd,
            listening_port=default_port,
            confidence="high" if pkg_file.exists() else "medium",
            detected_env_vars=detected_vars,
            notes=[f"Detected Node.js runtime ({framework})"]
        )
