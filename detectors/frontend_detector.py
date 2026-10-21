import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.variable_scanner import VariableScanner

class FrontendDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "frontend"

    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        index_html = project_path / "index.html"
        pkg_file = project_path / "package.json"
        angular_json = project_path / "angular.json"
        svelte_config = project_path / "svelte.config.js"
        vite_config = list(project_path.glob("vite.config.*"))

        # Check for Angular
        if angular_json.exists():
            return DetectionResult(
                runtime="frontend",
                framework="angular",
                entry_point="angular.json",
                dependency_file="package.json",
                process_type="static",
                build_command="npm run build",
                start_command="python -m http.server $PORT --directory dist",
                listening_port=8080,
                confidence="high",
                detected_env_vars=VariableScanner.scan_directory(project_path),
                notes=["Detected Angular Single Page App"]
            )

        # Check for Svelte
        if svelte_config.exists():
            return DetectionResult(
                runtime="frontend",
                framework="svelte",
                entry_point="svelte.config.js",
                dependency_file="package.json",
                process_type="web",
                build_command="npm run build",
                start_command="node build",
                listening_port=3000,
                confidence="high",
                detected_env_vars=VariableScanner.scan_directory(project_path),
                notes=["Detected Svelte / SvelteKit application"]
            )

        # Check for Vite / React / Vue
        if pkg_file.exists():
            try:
                data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                scripts = data.get("scripts", {})
                
                framework = None
                if "react" in deps:
                    framework = "react-vite" if vite_config else "react"
                elif "vue" in deps:
                    framework = "vue-vite" if vite_config else "vue"

                if framework:
                    return DetectionResult(
                        runtime="frontend",
                        framework=framework,
                        entry_point="package.json",
                        dependency_file="package.json",
                        process_type="static",
                        build_command="npm run build",
                        start_command="python -m http.server $PORT --directory dist",
                        listening_port=8080,
                        confidence="high",
                        detected_env_vars=VariableScanner.scan_directory(project_path),
                        notes=[f"Detected modern frontend framework: {framework}"]
                    )
            except Exception:
                pass

        # Static HTML website
        if index_html.exists():
            return DetectionResult(
                runtime="frontend",
                framework="static-html",
                entry_point="index.html",
                process_type="static",
                start_command="python -m http.server $PORT",
                listening_port=8080,
                confidence="high",
                detected_env_vars=VariableScanner.scan_directory(project_path),
                notes=["Detected static HTML website"]
            )

        return None
