from pathlib import Path
from typing import Optional
from elite_cloud.detectors.base import BaseDetector, DetectionResult
from elite_cloud.detectors.variable_scanner import VariableScanner

class CompiledDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "compiled"

    def detect(self, project_path: Path) -> Optional[DetectionResult]:
        go_mod = project_path / "go.mod"
        cargo_toml = project_path / "Cargo.toml"
        pom_xml = project_path / "pom.xml"
        build_gradle = project_path / "build.gradle"

        detected_vars = VariableScanner.scan_directory(project_path)

        # Go
        if go_mod.exists():
            return DetectionResult(
                runtime="compiled",
                framework="go",
                entry_point="main.go",
                dependency_file="go.mod",
                process_type="web",
                build_command="go build -o server .",
                start_command="./server",
                listening_port=8080,
                confidence="high",
                detected_env_vars=detected_vars,
                notes=["Detected Go compiled application"]
            )

        # Rust
        if cargo_toml.exists():
            return DetectionResult(
                runtime="compiled",
                framework="rust",
                entry_point="src/main.rs",
                dependency_file="Cargo.toml",
                process_type="web",
                build_command="cargo build --release",
                start_command="./target/release/app",
                listening_port=8080,
                confidence="high",
                detected_env_vars=detected_vars,
                notes=["Detected Rust application"]
            )

        # Java
        if pom_xml.exists() or build_gradle.exists():
            return DetectionResult(
                runtime="compiled",
                framework="java",
                entry_point="pom.xml" if pom_xml.exists() else "build.gradle",
                dependency_file="pom.xml" if pom_xml.exists() else "build.gradle",
                process_type="web",
                build_command="mvn package" if pom_xml.exists() else "gradle build",
                start_command="java -jar target/*.jar",
                listening_port=8080,
                confidence="high",
                detected_env_vars=detected_vars,
                notes=["Detected Java JVM application"]
            )

        return None
