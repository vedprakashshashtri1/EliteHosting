import streamlit as st
from elite_cloud.dashboard.components.cards import render_header, render_metric_card, render_status_badge
from elite_cloud.storage.db import db
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.metrics_collector import MetricsCollector

def render_overview(user: dict):
    render_header("Platform Overview", "Real-time metrics, active deployments and global infrastructure health.")

    owner_id = user["_id"] if user.get("role") != "admin" else None
    projects = db.list_projects(owner_id=owner_id)
    running_count = sum(1 for p in projects if process_manager.is_running(p["_id"]))
    sys_m = MetricsCollector.get_system_metrics()

    # Top KPI Metrics
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Total Projects", str(len(projects)), f"{running_count} active")
    with c2:
        render_metric_card("Running Services", str(running_count), "Workers & APIs")
    with c3:
        render_metric_card("Host Memory", f"{sys_m['system_memory_used_mb']} MB", f"{sys_m['system_memory_percent']}% utilized")
    with c4:
        render_metric_card("CPU Load", f"{sys_m['system_cpu_percent']}%", "Multi-core aggregate")

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    # Active Deployments Table / Cards
    st.subheader("⚡ Live Applications & Background Workers")
    if not projects:
        st.info("No applications deployed yet. Click **New Deployment** in the sidebar to upload a ZIP archive.")
        return

    for p in projects[:6]:
        pid = p["_id"]
        is_running = process_manager.is_running(pid)
        instance = process_manager.get_instance(pid)
        metrics = MetricsCollector.get_process_metrics(instance.pid if instance else None)

        with st.container():
            st.markdown(f"""
            <div class="elite-card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div>
                        <span style="font-size: 1.25rem; font-weight: 700; color: #f8fafc;">{p.get('name')}</span>
                        <span style="font-size: 0.85rem; color: #94a3b8; margin-left: 8px;">({p.get('slug')})</span>
                    </div>
                    <div>
                        {render_status_badge("running" if is_running else "stopped")}
                    </div>
                </div>
                <div style="display: flex; gap: 24px; font-size: 0.85rem; color: #94a3b8;">
                    <div>⚙️ <b>Runtime:</b> {p.get('runtime', '').upper()} ({p.get('framework')})</div>
                    <div>📦 <b>Process:</b> {p.get('process_type', '').upper()}</div>
                    <div>💾 <b>RAM:</b> {metrics.get('memory_mb', 0.0)} MB</div>
                    <div>⚡ <b>CPU:</b> {metrics.get('cpu_percent', 0.0)}%</div>
                    <div>⏱️ <b>Uptime:</b> {metrics.get('uptime_seconds', 0.0)}s</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            b_col1, b_col2, b_col3, b_col4 = st.columns([1, 1, 1, 3])
            with b_col1:
                if is_running:
                    if st.button("🛑 Stop", key=f"ov_stop_{pid}", use_container_width=True):
                        process_manager.stop_application(pid)
                        st.rerun()
                else:
                    if st.button("▶️ Start", key=f"ov_start_{pid}", use_container_width=True):
                        from elite_cloud.orchestrator.deployment_queue import orchestrator
                        orchestrator.deploy_project(pid)
                        st.rerun()
            with b_col2:
                if st.button("🔄 Restart", key=f"ov_restart_{pid}", use_container_width=True):
                    from elite_cloud.orchestrator.deployment_queue import orchestrator
                    orchestrator.restart_project(pid)
                    st.rerun()
            with b_col3:
                if st.button("📂 Manage", key=f"ov_manage_{pid}", use_container_width=True):
                    st.session_state["selected_project_id"] = pid
                    st.session_state["current_page"] = "Project Details"
                    st.rerun()
