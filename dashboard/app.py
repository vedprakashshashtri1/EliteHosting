import sys
from pathlib import Path

# Add project root to sys.path so modules resolve cleanly
CURRENT_FILE = Path(__file__).resolve()
PROJECT_DIR = CURRENT_FILE.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st
from elite_cloud.storage.db import db
from elite_cloud.storage.security import verify_password, hash_password
from elite_cloud.dashboard.views.overview import render_overview
from elite_cloud.dashboard.views.projects import render_projects_list
from elite_cloud.dashboard.views.deploy_wizard import render_deploy_wizard
from elite_cloud.dashboard.views.project_detail import render_project_detail
from elite_cloud.dashboard.views.file_manager import render_file_manager
from elite_cloud.dashboard.views.domains import render_domains
from elite_cloud.dashboard.views.monitoring import render_monitoring
from elite_cloud.dashboard.views.telegram_link import render_telegram_link
from elite_cloud.dashboard.views.admin_panel import render_admin_panel

st.set_page_config(
    page_title="Elite Cloud Hosting",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load theme CSS
css_path = Path(__file__).parent / "styles" / "theme.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# Session state initialization
if "user" not in st.session_state:
    st.session_state["user"] = None
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Overview"
if "selected_project_id" not in st.session_state:
    st.session_state["selected_project_id"] = None

# Auto-login default admin if in single-tenant/development mode
if not st.session_state["user"]:
    admin_user = db.db.users.find_one({"username": "admin"})
    if admin_user:
        st.session_state["user"] = admin_user

user = st.session_state["user"]

# ----------------- LOGIN / REGISTER IF NOT LOGGED IN ----------------- #
if not user:
    st.markdown("""
    <div style="text-align: center; margin-top: 50px; margin-bottom: 30px;">
        <h1 class="elite-header-title">⚡ ELITE CLOUD HOSTING</h1>
        <p class="elite-header-subtitle">Enterprise-grade multi-app deployment platform</p>
    </div>
    """, unsafe_allow_html=True)

    tab_login, tab_reg = st.tabs(["🔐 Sign In", "📝 Create Account"])

    with tab_login:
        with st.form("login_form"):
            uname = st.text_input("Username", value="admin")
            pword = st.text_input("Password", type="password", value="admin123456")
            submit_login = st.form_submit_button("Sign In to Control Center", use_container_width=True)
            if submit_login:
                matched = db.db.users.find_one({"username": uname})
                if matched and verify_password(pword, matched.get("password_hash", "")):
                    st.session_state["user"] = matched
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

    with tab_reg:
        with st.form("register_form"):
            r_uname = st.text_input("Choose Username")
            r_email = st.text_input("Email Address")
            r_pword = st.text_input("Choose Password", type="password")
            submit_reg = st.form_submit_button("Create Account", use_container_width=True)
            if submit_reg and r_uname and r_pword:
                import uuid
                u_id = str(uuid.uuid4())
                new_u = {
                    "_id": u_id,
                    "username": r_uname.strip(),
                    "email": r_email.strip(),
                    "password_hash": hash_password(r_pword),
                    "role": "developer",
                    "is_active": True,
                    "telegram_chat_id": None
                }
                db.db.users.insert_one(new_u)
                st.session_state["user"] = new_u
                st.success("Account created successfully!")
                st.rerun()

    st.stop()

# ----------------- SIDEBAR NAVIGATION ----------------- #
with st.sidebar:
    st.markdown("""
    <div style="padding: 10px 0 20px 0;">
        <div style="font-size: 1.4rem; font-weight: 800; background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
            ⚡ ELITE CLOUD
        </div>
        <div style="font-size: 0.75rem; color: #64748b; letter-spacing: 0.5px;">MULTI-APP PLATFORM</div>
    </div>
    """, unsafe_allow_html=True)

    # User Profile Pill
    st.markdown(f"""
    <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 10px 14px; margin-bottom: 20px;">
        <div style="font-size: 0.85rem; font-weight: 700; color: #f8fafc;">👤 {user.get('username')}</div>
        <div style="font-size: 0.75rem; color: #00f2fe; text-transform: uppercase;">Role: {user.get('role', 'developer')}</div>
    </div>
    """, unsafe_allow_html=True)

    # Navigation Links
    pages = [
        ("📊 Overview", "Overview"),
        ("📂 Projects", "Projects"),
        ("🚀 New Deployment", "New Deployment"),
        ("⚙️ Project Details", "Project Details"),
        ("📁 File Manager", "File Manager"),
        ("🌐 Domains & Routing", "Domains"),
        ("📈 Monitoring & Health", "Monitoring"),
        ("🤖 Telegram Remote", "Telegram Link")
    ]

    if user.get("role") == "admin":
        pages.append(("🛡️ Admin Panel", "Admin Panel"))

    for label, page_key in pages:
        is_active = st.session_state["current_page"] == page_key
        button_type = "primary" if is_active else "secondary"
        if st.button(label, key=f"nav_{page_key}", use_container_width=True, type=button_type):
            st.session_state["current_page"] = page_key
            st.rerun()

    st.markdown("---")

    # Fast Project Switcher
    projects = db.list_projects(owner_id=user["_id"] if user.get("role") != "admin" else None)
    if projects:
        st.markdown("<div style='font-size: 0.8rem; color: #94a3b8; font-weight: 600; margin-bottom: 6px;'>SWITCH PROJECT</div>", unsafe_allow_html=True)
        p_names = {p["_id"]: p.get("name") for p in projects}
        selected_id = st.session_state.get("selected_project_id")
        current_idx = list(p_names.keys()).index(selected_id) if selected_id in p_names else 0
        new_selection = st.selectbox(
            "Select Project",
            options=list(p_names.keys()),
            format_func=lambda x: p_names[x],
            index=current_idx,
            label_visibility="collapsed"
        )
        if new_selection != selected_id:
            st.session_state["selected_project_id"] = new_selection
            st.rerun()

    st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
    if st.button("🚪 Sign Out", key="sidebar_logout", use_container_width=True):
        st.session_state["user"] = None
        st.session_state["selected_project_id"] = None
        st.session_state["current_page"] = "Overview"
        st.rerun()

# ----------------- PAGE ROUTING ----------------- #
page = st.session_state["current_page"]

if page == "Overview":
    render_overview(user)
elif page == "Projects":
    render_projects_list(user)
elif page == "New Deployment":
    render_deploy_wizard(user)
elif page == "Project Details":
    render_project_detail(user)
elif page == "File Manager":
    render_file_manager(user)
elif page == "Domains":
    render_domains(user)
elif page == "Monitoring":
    render_monitoring(user)
elif page == "Telegram Link":
    render_telegram_link(user)
elif page == "Admin Panel":
    render_admin_panel(user)
