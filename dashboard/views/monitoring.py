import streamlit as st
import pandas as pd
from elite_cloud.dashboard.components.cards import render_header, render_metric_card
from elite_cloud.storage.db import db
from elite_cloud.orchestrator.metrics_collector import MetricsCollector
from elite_cloud.orchestrator.process_manager import process_manager

def render_monitoring(user: dict):
    render_header("Monitoring & Health", "Live process metrics, memory usage, CPU load and container health.")

    sys_m = MetricsCollector.get_system_metrics()

    # Host Telemetry
    st.subheader("🖥️ Host System Telemetry")
    c1, c2, c3 = st.columns(3)
    with c1:
        render_metric_card("Host CPU Load", f"{sys_m['system_cpu_percent']}%", "All cores")
        st.progress(min(1.0, sys_m['system_cpu_percent'] / 100.0))
    with c2:
        render_metric_card("Host Memory", f"{sys_m['system_memory_used_mb']} MB", f"of {sys_m['system_memory_total_mb']} MB")
        st.progress(min(1.0, sys_m['system_memory_percent'] / 100.0))
    with c3:
        render_metric_card("Host Disk", f"{sys_m['system_disk_used_gb']} GB", f"of {sys_m['system_disk_total_gb']} GB")
        st.progress(min(1.0, sys_m['system_disk_percent'] / 100.0))

    st.markdown("---")

    # Per-Process Metrics Table & Visual Breakdown
    st.subheader("📊 Active Service Metrics Breakdown")
    projects = db.list_projects()
    active_rows = []

    for p in projects:
        pid = p["_id"]
        is_running = process_manager.is_running(pid)
        instance = process_manager.get_instance(pid)
        metrics = MetricsCollector.get_process_metrics(instance.pid if instance else None)

        active_rows.append({
            "Project": p.get("name"),
            "Status": "🟢 Running" if is_running else "⚪ Stopped",
            "Runtime": p.get("runtime", "").upper(),
            "PID": instance.pid if instance and is_running else "-",
            "RAM (MB)": metrics.get("memory_mb", 0.0),
            "CPU (%)": metrics.get("cpu_percent", 0.0),
            "Threads": metrics.get("threads", 0),
            "Uptime (s)": metrics.get("uptime_seconds", 0.0),
            "Restarts": instance.restart_count if instance else 0
        })

    if active_rows:
        df = pd.DataFrame(active_rows)
        st.dataframe(df, use_container_width=True)

        # Bar chart comparison
        running_df = df[df["RAM (MB)"] > 0]
        if not running_df.empty:
            st.markdown("#### Memory Allocation (MB)")
            st.bar_chart(running_df.set_index("Project")["RAM (MB)"])
    else:
        st.info("No applications to display metrics for.")
