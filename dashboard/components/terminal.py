import streamlit as st
from typing import List, Dict, Any

def render_terminal(logs: List[Dict[str, Any]], title: str = "Live Application Console", height: int = 400):
    st.markdown("""
    <div style="background: #090d16; border: 1px solid #1e293b; border-radius: 12px 12px 0 0; padding: 10px 16px; display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; gap: 8px;">
            <div style="width: 10px; height: 10px; border-radius: 50%; background: #ff5f56;"></div>
            <div style="width: 10px; height: 10px; border-radius: 50%; background: #ffbd2e;"></div>
            <div style="width: 10px; height: 10px; border-radius: 50%; background: #27c93f;"></div>
        </div>
        <div style="font-family: 'Fira Code', monospace; font-size: 0.8rem; color: #94a3b8;">""" + title + """</div>
        <div style="font-size: 0.75rem; color: #64748b;">STDOUT / STDERR</div>
    </div>
    """, unsafe_allow_html=True)

    if not logs:
        log_content = "Waiting for process logs... Process starting up.\n"
    else:
        lines = []
        for l in logs:
            source = l.get("source", "app").upper()
            ts = str(l.get("timestamp", ""))[:19]
            color = "#ef4444" if source == "STDERR" or l.get("level") == "ERROR" else "#38bdf8"
            lines.append(f"[{ts}] [{source}] {l.get('message', '')}")
        log_content = "\n".join(lines)

    st.text_area(
        label="Terminal Output",
        value=log_content,
        height=height,
        disabled=True,
        label_visibility="collapsed"
    )
