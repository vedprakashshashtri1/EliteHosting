import streamlit as st
from elite_cloud.dashboard.components.cards import render_header
from elite_cloud.storage.db import db
from elite_cloud.config import BASE_DOMAIN
from elite_cloud.orchestrator.reverse_proxy import reverse_proxy_manager

def render_domains(user: dict):
    render_header("Domains & Subdomains", "Manage public HTTPS routing, custom domains and reverse proxy mappings.")

    projects = db.list_projects()
    active_domains = db.list_domains()

    st.markdown("### 🌐 Configured Domain Mappings")
    if active_domains:
        for d in active_domains:
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            with c1:
                st.markdown(f"**`http://{d.get('domain')}`**")
            with c2:
                st.caption(f"Target Port: `{d.get('target_port')}`")
            with c3:
                st.markdown('<span style="color: #10b981; font-weight: 600;">🔒 HTTPS Active</span>', unsafe_allow_html=True)
            with c4:
                st.caption("Active")
    else:
        st.info("No custom domain mappings active yet.")

    st.markdown("---")

    # Add custom domain
    st.subheader("➕ Map Custom Domain")
    with st.form("custom_domain_form"):
        p_choices = {p["_id"]: p.get("name") for p in projects}
        if not p_choices:
            st.warning("No projects available to map.")
            st.form_submit_button("Submit", disabled=True)
            return

        chosen_pid = st.selectbox("Assign to Project", options=list(p_choices.keys()), format_func=lambda x: p_choices[x])
        custom_domain_input = st.text_input("Custom Domain (e.g. app.mycompany.com)", placeholder="subdomain.example.com")
        submit_domain = st.form_submit_button("Register Custom Domain")
        if submit_domain and custom_domain_input:
            proj = db.get_project(chosen_pid)
            port = proj.get("listening_port") or 8080
            reverse_proxy_manager.register_domain(chosen_pid, custom_domain_input.strip().lower(), is_subdomain=False, target_port=port)
            st.success(f"Domain {custom_domain_input} registered and routed to port {port}!")
            st.rerun()

    st.markdown("---")
    st.subheader("⚙️ Reverse Proxy Configuration Preview (Caddyfile)")
    caddy_content = reverse_proxy_manager.generate_caddyfile()
    st.code(caddy_content, language="caddy")
