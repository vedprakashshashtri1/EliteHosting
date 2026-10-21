from typing import List
from elite_cloud.detectors.base import DetectionResult

def generate_deployment_guide(project_name: str, detection: DetectionResult) -> str:
    required_vars = [v for v in detection.detected_env_vars if v.is_required]
    optional_vars = [v for v in detection.detected_env_vars if not v.is_required]

    md = []
    md.append(f"# 🚀 DEPLOYMENT GUIDE: {project_name.upper()}")
    md.append("")
    md.append(f"**Runtime:** `{detection.runtime.upper()}`  ")
    md.append(f"**Framework:** `{detection.framework}`  ")
    md.append(f"**Primary Entry Point:** `{detection.entry_point}`  ")
    md.append(f"**Dependencies File:** `{detection.dependency_file or 'None'}`  ")
    md.append(f"**Process Architecture:** `{detection.process_type.upper()}`  ")
    md.append(f"**Start Command:** `{detection.start_command}`  ")
    if detection.listening_port:
        md.append(f"**Listening Port:** `{detection.listening_port}`  ")
    md.append(f"**Detection Confidence:** `{detection.confidence.upper()}`  ")
    md.append("")
    
    md.append("## 🔑 ENVIRONMENT CONFIGURATION")
    if required_vars:
        md.append("### Required Variables (Must be configured before launch):")
        for v in required_vars:
            secret_badge = "🔒 `SECRET`" if v.is_secret else "⚙️ `CONFIG`"
            src = f" *(from {v.detected_in_file})*" if v.detected_in_file else ""
            md.append(f"- **`{v.name}`** - {secret_badge}{src}")
    else:
        md.append("*(No required environment variables detected)*")

    if optional_vars:
        md.append("\n### Optional / Default Variables:")
        for v in optional_vars:
            def_str = f" [default: `{v.default_value}`]" if v.default_value else ""
            md.append(f"- **`{v.name}`**{def_str}")

    md.append("\n## 📋 RECOMMENDED DEPLOYMENT WORKFLOW")
    md.append("1. **Upload Source Archive:** ZIP extracted and analyzed.")
    md.append("2. **Review Auto-Settings:** Confirm or adjust the start command and port above.")
    md.append("3. **Input Secrets:** Provide the values for all marked required variables.")
    md.append("4. **Deploy Application:** Click **Deploy** to isolate dependencies and start.")
    md.append("5. **Live Monitoring:** Inspect real-time stdout/stderr logs and resource usage.")

    md.append("\n## 🛠️ TROUBLESHOOTING & COMMON PITFALLS")
    if "telegram" in detection.framework:
        md.append("- **Telegram 409 Conflict:** Ensure no other bot instance or webhook is active with this `BOT_TOKEN`.")
        md.append("- **Invalid Token (404/401):** Double check you copied the token accurately from @BotFather.")
        md.append("- **Polling Timeouts:** In workers, make sure your bot uses `drop_pending_updates=True` on startup.")
    elif "streamlit" in detection.framework:
        md.append("- **Port Binding:** Streamlit must bind to `0.0.0.0` with `--server.port $PORT` and `--server.headless true`.")
        md.append("- **Websocket / CORS:** If accessing through subdomains, verify CORS settings are enabled.")
    elif "fastapi" in detection.framework or "flask" in detection.framework:
        md.append("- **0.0.0.0 Binding:** Web servers must listen on host `0.0.0.0` (not `127.0.0.1` or `localhost`).")
        md.append("- **Dynamic Port:** The application must read `os.getenv('PORT')` to allow reverse proxy routing.")
    elif "nextjs" in detection.framework or "node" in detection.runtime:
        md.append("- **Node Modules:** Never upload `node_modules` inside your ZIP archive; dependencies are installed during build.")
        md.append("- **Production Mode:** Use `NODE_ENV=production` for optimized build artifacts.")

    md.append("- **Exit Code 137 (OOM):** If the process terminates abruptly, check RAM limits in Resource Settings.")
    md.append("- **Persistent Storage:** Local file writes are isolated to your project directory.")

    return "\n".join(md)
