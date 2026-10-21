import streamlit as st
from typing import Optional, Dict, Any

def render_header(title: str, subtitle: str = ""):
    st.markdown(f'<div class="elite-header-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="elite-header-subtitle">{subtitle}</div>', unsafe_allow_html=True)

def render_status_badge(status: str) -> str:
    s = (status or "stopped").lower()
    badge_class = f"status-{s}"
    emoji_map = {
        "running": "🟢",
        "stopped": "⚪",
        "building": "🟡",
        "deploying": "🟡",
        "crashed": "🔴",
        "failed": "🔴",
        "unhealthy": "⚠️"
    }
    emoji = emoji_map.get(s, "⚪")
    return f'<span class="status-badge {badge_class}">{emoji} {s.upper()}</span>'

def render_metric_card(label: str, value: str, subtext: str = ""):
    sub_html = f'<div style="font-size: 0.75rem; color: #64748b; margin-top: 2px;">{subtext}</div>' if subtext else ""
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-value">{value}</div>
        <div class="metric-label">{label}</div>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)
