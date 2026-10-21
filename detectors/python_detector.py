import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.variable_scanner import VariableScanner

COMMON_PYTHON_ENTRIES = ["main.py", "bot.py", "app.py", "run.py", "server.py", "manage.py", "index.py"]

TELEGRAM_PACKAGES = {"python-telegram-bot", "telebot", "pyTelegramBotAPI", "pyrogram", "telethon", "aiogram"}
DISCORD_PACKAGES = {"discord", "discord.py", "nextcord", "disnake", "hikari"}

class PythonDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "python"

    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        # Check if project contains Python files or requirements
        py_files = list(project_path.glob("*.py"))
        req_file = project_path / "requirements.txt"
        pyproject = project_path / "pyproject.toml"
        pipfile = project_path / "Pipfile"
        procfile = project_path / "Procfile"

        if not py_files and not req_file.exists() and not pyproject.exists():
            return None

        # Read requirements / dependencies
        dep_content = ""
        dep_filename = None
        if req_file.exists():
            dep_filename = "requirements.txt"
            try:
                dep_content += req_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        if pyproject.exists():
            dep_filename = dep_filename or "pyproject.toml"
            try:
                dep_content += pyproject.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        # Check for Procfile
        proc_cmd = None
        if procfile.exists():
            try:
                for line in procfile.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("web:"):
                        proc_cmd = line.split("web:", 1)[1].strip()
                    elif line.startswith("worker:") and not proc_cmd:
                        proc_cmd = line.split("worker:", 1)[1].strip()
            except Exception:
                pass

        # Determine entry points
        available_entries = [p.name for p in py_files if p.name in COMMON_PYTHON_ENTRIES]
        # Also any other py files
        all_py = [p.name for p in py_files]

        # Scan variables
        detected_vars = VariableScanner.scan_directory(project_path)

        # Inspect Python files content for frameworks
        all_content = dep_content.lower()
        framework = "python-worker"
        process_type = "worker"
        default_port = None
        start_command = ""
        primary_entry = "main.py"
        confidence = "medium"

        # Check for manage.py (Django)
        if (project_path / "manage.py").exists():
            return DetectionResult(
                runtime="python",
                framework="django",
                entry_point="manage.py",
                dependency_file=dep_filename,
                process_type="web",
                start_command="python manage.py runserver 0.0.0.0:$PORT",
                listening_port=8000,
                confidence="high",
                detected_env_vars=detected_vars,
                notes=["Detected Django project via manage.py"]
            )

        # Check each py file for imports
        imports_found = set()
        for py in py_files[:10]:
            try:
                txt = py.read_text(encoding="utf-8", errors="ignore")
                for line in txt.splitlines():
                    if line.startswith("import ") or line.startswith("from "):
                        imports_found.add(line.lower())
            except Exception:
                pass

        joined_imports = " ".join(imports_found) + " " + all_content

        # 1. Telegram Bot
        if any(pkg in joined_imports for pkg in ["telegram", "telebot", "pyrogram", "telethon", "aiogram"]) or any("bot" in e for e in available_entries):
            framework = "telegram-bot"
            process_type = "worker"
            primary_entry = "bot.py" if "bot.py" in available_entries else (available_entries[0] if available_entries else "main.py")
            start_command = f"python {primary_entry}"
            confidence = "high"

        # 2. Streamlit Application
        elif "streamlit" in joined_imports:
            framework = "streamlit"
            process_type = "web"
            default_port = 8501
            primary_entry = "app.py" if "app.py" in available_entries else (available_entries[0] if available_entries else "main.py")
            start_command = f"streamlit run {primary_entry} --server.address 0.0.0.0 --server.port $PORT"
            confidence = "high"

        # 3. FastAPI Application
        elif "fastapi" in joined_imports:
            framework = "fastapi"
            process_type = "web"
            default_port = 8000
            primary_entry = "main.py" if "main.py" in available_entries else (available_entries[0] if available_entries else "app.py")
            mod_name = Path(primary_entry).stem
            start_command = f"uvicorn {mod_name}:app --host 0.0.0.0 --port $PORT"
            confidence = "high"

        # 4. Flask Application
        elif "flask" in joined_imports:
            framework = "flask"
            process_type = "web"
            default_port = 5000
            primary_entry = "app.py" if "app.py" in available_entries else (available_entries[0] if available_entries else "main.py")
            start_command = f"python {primary_entry}"
            confidence = "high"

        # 5. Discord Bot
        elif any(pkg in joined_imports for pkg in ["discord", "nextcord", "disnake"]):
            framework = "discord-bot"
            process_type = "worker"
            primary_entry = "bot.py" if "bot.py" in available_entries else (available_entries[0] if available_entries else "main.py")
            start_command = f"python {primary_entry}"
            confidence = "high"

        # 6. Generic Python script
        else:
            primary_entry = available_entries[0] if available_entries else (all_py[0] if all_py else "main.py")
            start_command = proc_cmd if proc_cmd else f"python {primary_entry}"
            framework = "python-generic"
            process_type = "worker"
            confidence = "medium"

        if proc_cmd:
            start_command = proc_cmd

        # Alternative suggestions if multiple entry points exist
        alternatives = []
        for alt in available_entries:
            if alt != primary_entry:
                alternatives.append({
                    "entry_point": alt,
                    "start_command": f"python {alt}",
                    "framework": framework
                })

        return DetectionResult(
            runtime="python",
            framework=framework,
            entry_point=primary_entry,
            dependency_file=dep_filename,
            process_type=process_type,
            start_command=start_command,
            listening_port=default_port,
            confidence=confidence,
            detected_env_vars=detected_vars,
            suggested_alternatives=alternatives,
            notes=[f"Detected Python runtime with primary entry: {primary_entry}"]
        )
