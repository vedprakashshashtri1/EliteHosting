import time
import streamlit as st

from elite_cloud.dashboard.components.cards import render_header, render_status_badge, render_metric_card
from elite_cloud.dashboard.components.terminal import render_terminal
from elite_cloud.storage.db import db
from elite_cloud.storage.security import encrypt_secret, decrypt_secret
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.metrics_collector import MetricsCollector
from elite_cloud.orchestrator.deployment_queue import orchestrator
from elite_cloud.detectors.doc_generator import generate_deployment_guide
from elite_cloud.detectors.base import DetectionResult
from elite_cloud.config import BASE_DOMAIN, WORKSPACES_DIR

def render_project_detail(user: dict):
    project_id = st.session_state.get("selected_project_id")
    if not project_id:
        st.warning("No project selected. Please choose a project from the Projects page.")
        if st.button("⬅️ Return to Projects"):
            st.session_state["current_page"] = "Projects"
            st.rerun()
        return

    p = db.get_project(project_id)
    if not p:
        st.error("Selected project was not found.")
        return

    is_running = process_manager.is_running(project_id)
    instance = process_manager.get_instance(project_id)
    metrics = MetricsCollector.get_process_metrics(instance.pid if instance else None, WORKSPACES_DIR / project_id)

    # Top Navigation and Header
    c_back, c_status = st.columns([4, 1])
    with c_back:
        render_header(f"Project Hub: {p.get('name')}", f"Slug: {p.get('slug')} | Runtime: {p.get('runtime', '').upper()} ({p.get('framework')})")
    with c_status:
        st.markdown(f"<div style='text-align: right; margin-top: 10px;'>{render_status_badge('running' if is_running else 'stopped')}</div>", unsafe_allow_html=True)

    # Real-time Telemetry Bar
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        render_metric_card("Memory (RAM)", f"{metrics.get('memory_mb', 0.0)} MB")
    with m2:
        render_metric_card("CPU Load", f"{metrics.get('cpu_percent', 0.0)}%")
    with m3:
        render_metric_card("Disk Used", f"{metrics.get('disk_mb', 0.0)} MB")
    with m4:
        render_metric_card("Uptime", f"{metrics.get('uptime_seconds', 0.0)}s")
    with m5:
        render_metric_card("Restarts", str(instance.restart_count if instance else 0))

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Lifecycle Action Buttons Bar
    col_act1, col_act2, col_act3, col_act4, col_act5 = st.columns([1, 1, 1, 1, 1])
    with col_act1:
        if is_running:
            if st.button("🛑 Stop App", key="pd_stop", use_container_width=True):
                process_manager.stop_application(project_id)
                st.rerun()
        else:
            if st.button("▶️ Start App", key="pd_start", use_container_width=True):
                orchestrator.deploy_project(project_id)
                st.rerun()
    with col_act2:
        if st.button("🔄 Restart", key="pd_restart", use_container_width=True):
            orchestrator.restart_project(project_id)
            st.rerun()
    with col_act3:
        if st.button("⚡ Redeploy", key="pd_redeploy", use_container_width=True):
            orchestrator.deploy_project(project_id)
            st.rerun()
    with col_act4:
        if st.button("📁 File Manager", key="pd_files", use_container_width=True):
            st.session_state["current_page"] = "File Manager"
            st.rerun()
    with col_act5:
        port = p.get("listening_port")
        sub = p.get("subdomain") or p.get("slug")
        if port:
            url = f"http://{sub}.{BASE_DOMAIN}"
            st.link_button("🌐 Open App", url, use_container_width=True)

    # Tabs for Management
    tab_console, tab_env, tab_revisions, tab_docs, tab_settings = st.tabs([
        "📜 Live Logs", "🔑 Environment Variables", "🕒 Revisions & Rollback", "📖 Deployment Guide", "⚙️ Settings"
    ])

    # 1. Live Logs Tab
    with tab_console:
        c_ref, c_clear = st.columns([4, 1])
        with c_clear:
            if st.button("🔄 Refresh Logs", key="refresh_logs"):
                st.rerun()
        logs = db.get_logs(project_id, limit=200)
        render_terminal(logs, title=f"Logs: {p.get('name')}", height=420)

    # 2. Environment Variables Tab
    with tab_env:
        st.subheader("🔑 Environment Variables & Secrets")
        vars_list = db.get_env_vars(project_id)

        if vars_list:
            for v in vars_list:
                c_k, c_v, c_del = st.columns([3, 4, 1])
                with c_k:
                    sec_tag = "🔒 [SECRET]" if v.get("is_secret") else "⚙️ [CONFIG]"
                    st.markdown(f"**`{v['key']}`** <span style='font-size:0.75rem; color:#94a3b8;'>{sec_tag}</span>", unsafe_allow_html=True)
                with c_v:
                    raw = decrypt_secret(v.get("value_encrypted", ""))
                    val_display = "••••••••••••" if v.get("is_secret") else raw
                    st.code(val_display, language="text")
                with c_del:
                    if st.button("🗑️", key=f"del_var_{v['key']}"):
                        db.delete_env_var(project_id, v["key"])
                        st.rerun()
        else:
            st.caption("No environment variables configured.")

        # Add new variable form
        with st.expander("➕ Add / Update Environment Variable"):
            with st.form("add_var_form"):
                new_k = st.text_input("Variable Key", placeholder="e.g. BOT_TOKEN or DATABASE_URL")
                new_v = st.text_input("Variable Value", placeholder="Enter value here")
                is_sec = st.checkbox("Mask as Secret", value=True)
                if st.form_submit_button("Save Variable"):
                    if new_k:
                        db.set_env_var(project_id, new_k.strip(), encrypt_secret(new_v.strip()), is_secret=is_sec)
                        st.success(f"Variable {new_k} saved!")
                        st.rerun()

    # 3. Revisions & Rollback Tab
    with tab_revisions:
        st.subheader("🕒 Revision History (GridFS Snapshots)")
        revisions = db.list_revisions(project_id)
        if not revisions:
            st.info("No revisions recorded.")
        else:
            for rev in revisions:
                is_active = rev["_id"] == p.get("active_revision_id")
                badge = " 🟢 ACTIVE RELEASE" if is_active else ""
                with st.container():
                    st.markdown(f"""
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between;">
                            <b>Revision #{rev.get('revision_number')}</b>: <i>{rev.get('commit_message')}</i>
                            <span style="color: #10b981; font-weight: 600;">{badge}</span>
                        </div>
                        <div style="font-size: 0.8rem; color: #64748b; margin-top: 4px;">
                            Files: {rev.get('file_count', 0)} | Size: {round(rev.get('total_size_bytes', 0) / 1024, 1)} KB | Date: {str(rev.get('created_at'))[:19]}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if not is_active:
                        if st.button(f"⏪ Rollback to Rev #{rev.get('revision_number')}", key=f"roll_{rev['_id']}"):
                            with st.spinner("Rolling back application release..."):
                                orchestrator.rollback_project(project_id, rev["_id"])
                                st.success(f"Rolled back to Revision #{rev.get('revision_number')}!")
                                time.sleep(1)
                                st.rerun()

    # 4. Deployment Guide & Troubleshooting Tab
    with tab_docs:
        det_res = DetectionResult(
            runtime=p.get("runtime", "python"),
            framework=p.get("framework", "generic"),
            entry_point=p.get("entry_point", "main.py"),
            start_command=p.get("start_command", "python main.py"),
            listening_port=p.get("listening_port"),
            process_type=p.get("process_type", "worker")
        )
        guide_md = generate_deployment_guide(p.get("name"), det_res)
        st.markdown(guide_md)

    # 5. Settings Tab
    with tab_settings:
        st.subheader("⚙️ Project Settings")
        with st.form("project_settings_form"):
            e_name = st.text_input("Application Name", value=p.get("name"))
            e_cmd = st.text_input("Start Command", value=p.get("start_command"))
            e_entry = st.text_input("Entry Point", value=p.get("entry_point"))
            e_sub = st.text_input("Subdomain", value=p.get("subdomain") or p.get("slug"))
            save_set = st.form_submit_button("Save Changes")
            if save_set:
                db.update_project(project_id, {
                    "name": e_name,
                    "start_command": e_cmd,
                    "entry_point": e_entry,
                    "subdomain": e_sub
                })
                st.success("Project settings updated.")
                st.rerun()

        st.markdown("---")
        st.markdown("#### ⚠️ Danger Zone")
        if st.button("🗑️ Delete Project Permanently", key="danger_del_proj", type="secondary"):
            process_manager.stop_application(project_id)
            db.delete_project(project_id)
            st.session_state["selected_project_id"] = None
            st.session_state["current_page"] = "Projects"
            st.success("Project deleted.")
            time.sleep(1)
            st.rerun()
