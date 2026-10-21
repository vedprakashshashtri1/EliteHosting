import streamlit as st
from elite_cloud.dashboard.components.cards import render_header, render_status_badge
from elite_cloud.storage.db import db
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.metrics_collector import MetricsCollector
from elite_cloud.orchestrator.deployment_queue import orchestrator
from elite_cloud.config import BASE_DOMAIN

def render_projects_list(user: dict):
    render_header("Projects & Applications", "Manage all deployed services, Telegram bots, APIs and websites.")

    owner_id = user["_id"] if user.get("role") != "admin" else None
    all_projects = db.list_projects(owner_id=owner_id)

    if not all_projects:
        st.info("📦 No projects found. Click **New Deployment** in the sidebar to get started.")
        return

    # Filter & Search bar
    c_s, c_f = st.columns([3, 1])
    with c_s:
        search_q = st.text_input("🔍 Search projects by name, slug or runtime...", placeholder="Type to filter...")
    with c_f:
        status_filter = st.selectbox("Status Filter", ["All", "Running", "Stopped", "Crashed"])

    filtered = []
    for p in all_projects:
        is_running = process_manager.is_running(p["_id"])
        curr_status = "Running" if is_running else "Stopped"
        if status_filter != "All" and curr_status != status_filter:
            continue
        if search_q:
            query = search_q.lower()
            if query not in p.get("name", "").lower() and query not in p.get("slug", "").lower() and query not in p.get("runtime", "").lower():
                continue
        filtered.append(p)

    st.markdown(f"Showing **{len(filtered)}** of {len(all_projects)} applications")

    for p in filtered:
        pid = p["_id"]
        is_running = process_manager.is_running(pid)
        instance = process_manager.get_instance(pid)
        metrics = MetricsCollector.get_process_metrics(instance.pid if instance else None)
        port = p.get("listening_port")
        subdomain = p.get("subdomain") or p.get("slug")
        url = f"http://{subdomain}.{BASE_DOMAIN}" if port else None

        with st.container():
            st.markdown(f"""
            <div class="elite-card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <span style="font-size: 1.3rem; font-weight: 700; color: #f8fafc;">{p.get('name')}</span>
                            {render_status_badge("running" if is_running else "stopped")}
                        </div>
                        <div style="color: #64748b; font-size: 0.85rem; margin-top: 4px;">ID: <code>{pid[:8]}</code> | Slug: <code>{p.get('slug')}</code></div>
                    </div>
                    <div>
                        {f'<a href="{url}" target="_blank" style="text-decoration: none; background: rgba(0,242,254,0.15); color: #00f2fe; padding: 6px 14px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; border: 1px solid rgba(0,242,254,0.3);">🌐 Open Website</a>' if url and is_running else ''}
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 16px; margin-top: 16px; padding: 12px; background: rgba(0,0,0,0.25); border-radius: 8px; font-size: 0.85rem;">
                    <div>⚙️ <b>Runtime:</b><br><span style="color: #cbd5e1;">{p.get('runtime', '').upper()}</span></div>
                    <div>📦 <b>Framework:</b><br><span style="color: #cbd5e1;">{p.get('framework')}</span></div>
                    <div>🎯 <b>Entry:</b><br><span style="color: #cbd5e1;">{p.get('entry_point')}</span></div>
                    <div>💾 <b>RAM:</b><br><span style="color: #cbd5e1;">{metrics.get('memory_mb', 0.0)} MB</span></div>
                    <div>⚡ <b>CPU:</b><br><span style="color: #cbd5e1;">{metrics.get('cpu_percent', 0.0)}%</span></div>
                    <div>⏱️ <b>Uptime:</b><br><span style="color: #cbd5e1;">{metrics.get('uptime_seconds', 0.0)}s</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
            with c1:
                if is_running:
                    if st.button("🛑 Stop", key=f"pl_stop_{pid}", use_container_width=True):
                        process_manager.stop_application(pid)
                        st.rerun()
                else:
                    if st.button("▶️ Start", key=f"pl_start_{pid}", use_container_width=True):
                        orchestrator.deploy_project(pid)
                        st.rerun()
            with c2:
                if st.button("🔄 Restart", key=f"pl_restart_{pid}", use_container_width=True):
                    orchestrator.restart_project(pid)
                    st.rerun()
            with c3:
                if st.button("⚙️ Manage Hub", key=f"pl_manage_{pid}", use_container_width=True):
                    st.session_state["selected_project_id"] = pid
                    st.session_state["current_page"] = "Project Details"
                    st.rerun()
