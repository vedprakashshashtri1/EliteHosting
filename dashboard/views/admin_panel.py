import streamlit as st
import pandas as pd
from elite_cloud.dashboard.components.cards import render_header
from elite_cloud.storage.db import db
from elite_cloud.orchestrator.metrics_collector import MetricsCollector

def render_admin_panel(user: dict):
    render_header("Administrator Control Center", "Audit trail, user roles, system capacity and infrastructure controls.")

    if user.get("role") != "admin":
        st.error("⛔ Access Denied. Administrator privileges required.")
        return

    tab_users, tab_audit, tab_capacity = st.tabs(["👥 User Management", "📜 Audit Logs", "⚙️ Worker Nodes & Capacity"])

    # 1. User Management
    with tab_users:
        st.subheader("Registered Platform Users")
        users = list(db.db.users.find({}, {"password_hash": 0}))
        user_rows = []
        for u in users:
            user_rows.append({
                "User ID": u["_id"][:8],
                "Username": u.get("username"),
                "Email": u.get("email"),
                "Role": u.get("role", "developer").upper(),
                "Telegram Linked": "✅ Yes" if u.get("telegram_chat_id") else "❌ No",
                "Created": str(u.get("created_at"))[:19]
            })
        st.dataframe(pd.DataFrame(user_rows), use_container_width=True)

    # 2. Audit Logs
    with tab_audit:
        st.subheader("Platform Security Audit Trail")
        audit_logs = db.get_audit_logs(limit=100)
        if audit_logs:
            audit_rows = []
            for a in audit_logs:
                audit_rows.append({
                    "Timestamp": str(a.get("timestamp"))[:19],
                    "Action": a.get("action"),
                    "Target Type": a.get("target_type"),
                    "Target ID": str(a.get("target_id", ""))[:8],
                    "User ID": str(a.get("user_id", ""))[:8]
                })
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True)
        else:
            st.caption("No audit entries yet.")

    # 3. Capacity & Worker Status
    with tab_capacity:
        st.subheader("Host Compute Worker Capacity")
        sys_m = MetricsCollector.get_system_metrics()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**CPU Capacity:** `{sys_m['system_cpu_percent']}%` currently utilized")
            st.markdown(f"**Physical RAM:** `{sys_m['system_memory_used_mb']} MB` / `{sys_m['system_memory_total_mb']} MB`")
        with c2:
            st.markdown(f"**Disk Storage:** `{sys_m['system_disk_used_gb']} GB` / `{sys_m['system_disk_total_gb']} GB`")
            st.markdown(f"**Database Status:** `{'In-Memory Mock' if db.is_mock else 'MongoDB Atlas / Standalone'}`")
