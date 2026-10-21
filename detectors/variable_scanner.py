import ast
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
from elite_cloud.detectors.base import DetectedVariable

SECRET_KEYWORDS = {
    "TOKEN", "SECRET", "KEY", "PASSWORD", "PASS", "HASH",
    "AUTH", "PRIVATE", "CREDENTIAL", "MONGO_URI", "DATABASE_URL",
    "SESSION_STRING", "API_ID", "API_HASH", "BOT_TOKEN", "WEBHOOK"
}

NODE_ENV_PATTERN = re.compile(r"process\.env(?:\.([A-Za-z0-9_]+)|\[['\"]([A-Za-z0-9_]+)['\"]\])")
ENV_FILE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$")

class PythonASTVarVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.variables: Dict[str, DetectedVariable] = {}

    def visit_Call(self, node):
        # Detect os.getenv("NAME", "default") or os.environ.get("NAME", "default")
        func = node.func
        is_getenv = False
        if isinstance(func, ast.Attribute) and func.attr in ("getenv", "get"):
            if isinstance(func.value, ast.Name) and func.value.id == "os" and func.attr == "getenv":
                is_getenv = True
            elif isinstance(func.value, ast.Attribute) and func.value.attr == "environ":
                is_getenv = True

        if is_getenv and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                var_name = first_arg.value
                default_val = None
                is_required = True
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    default_val = str(node.args[1].value)
                    is_required = False
                self._record(var_name, default_val, is_required)

        self.generic_visit(node)

    def visit_Subscript(self, node):
        # Detect os.environ["NAME"]
        val = node.value
        if isinstance(val, ast.Attribute) and val.attr == "environ":
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                var_name = node.slice.value
                self._record(var_name, None, True)
        self.generic_visit(node)

    def _record(self, name: str, default_val: Optional[str], is_required: bool):
        is_secret = any(k in name.upper() for k in SECRET_KEYWORDS)
        if name not in self.variables or (is_required and not self.variables[name].is_required):
            self.variables[name] = DetectedVariable(
                name=name,
                is_secret=is_secret,
                is_required=is_required,
                default_value=default_val,
                description=f"Detected in {self.filename}",
                detected_in_file=self.filename
            )

class VariableScanner:
    @staticmethod
    def scan_directory(project_path: Path, max_files: int = 50) -> List[DetectedVariable]:
        results: Dict[str, DetectedVariable] = {}
        scanned_count = 0

        # 1. Scan .env.example, .env.sample, .env
        for env_file_name in [".env.example", ".env.sample", ".env.template", ".env"]:
            env_file = project_path / env_file_name
            if env_file.is_file():
                try:
                    with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            m = ENV_FILE_PATTERN.match(line.strip())
                            if m and not line.strip().startswith("#"):
                                key, raw_val = m.group(1), m.group(2).strip("\"' ")
                                is_sec = any(k in key.upper() for k in SECRET_KEYWORDS)
                                is_req = not bool(raw_val)
                                results[key] = DetectedVariable(
                                    name=key,
                                    is_secret=is_sec,
                                    is_required=is_req,
                                    default_value=raw_val if raw_val else None,
                                    description=f"Defined in {env_file_name}",
                                    detected_in_file=env_file_name
                                )
                except Exception:
                    pass

        # 2. Walk directory for source files
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}]
            for file in files:
                if scanned_count >= max_files:
                    break
                p = Path(root) / file
                rel = str(p.relative_to(project_path))
                
                # Python files
                if file.endswith(".py"):
                    scanned_count += 1
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            tree = ast.parse(f.read(), filename=rel)
                        visitor = PythonASTVarVisitor(rel)
                        visitor.visit(tree)
                        for k, v in visitor.variables.items():
                            if k not in results or (v.is_required and not results[k].is_required):
                                results[k] = v
                    except Exception:
                        # Fallback regex for python if AST fails on syntax error
                        try:
                            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            for m in re.finditer(r"os\.(?:environ(?:\[['\"]|\.get\(['\"])|getenv\(['\"])([A-Za-z0-9_]+)", content):
                                k = m.group(1)
                                is_sec = any(kw in k.upper() for kw in SECRET_KEYWORDS)
                                if k not in results:
                                    results[k] = DetectedVariable(
                                        name=k,
                                        is_secret=is_sec,
                                        is_required=True,
                                        description=f"Detected in {rel}",
                                        detected_in_file=rel
                                    )
                        except Exception:
                            pass

                # JavaScript / TypeScript files
                elif file.endswith((".js", ".ts", ".mjs", ".jsx", ".tsx")):
                    scanned_count += 1
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        for m in NODE_ENV_PATTERN.finditer(content):
                            k = m.group(1) or m.group(2)
                            if k and k not in {"NODE_ENV", "PATH"}:
                                is_sec = any(kw in k.upper() for kw in SECRET_KEYWORDS)
                                if k not in results:
                                    results[k] = DetectedVariable(
                                        name=k,
                                        is_secret=is_sec,
                                        is_required=True,
                                        description=f"Detected in {rel}",
                                        detected_in_file=rel
                                    )
                    except Exception:
                        pass

        # Sort: required first, then secrets, then alphabetical
        sorted_vars = sorted(
            results.values(),
            key=lambda x: (not x.is_required, not x.is_secret, x.name)
        )
        return sorted_vars

import os
