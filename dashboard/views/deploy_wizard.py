import os
import uuid
import time
import shutil
from pathlib import Path
import streamlit as st

from elite_cloud.dashboard.components.cards import render_header, render_status_badge
from elite_cloud.config import TEMP_DIR, WORKSPACES_DIR, PROJECT_ROOT, BASE_DOMAIN
from elite_cloud.storage.db import db
from elite_cloud.storage.security import encrypt_secret
from elite_cloud.detectors.registry import detector_registry
from elite_cloud.detectors.doc_generator import generate_deployment_guide
from elite_cloud.orchestrator.zip_validator import ZipValidator, ZipSecurityError
from elite_cloud.orchestrator.deployment_queue import orchestrator

def render_deploy_wizard(user: dict):
    render_header("Deploy Application", "One-click deployment from ZIP archive with intelligent auto-detection.")

    st.markdown("""
    <div style="background: rgba(0, 242, 254, 0.05); border: 1px solid rgba(0, 242, 254, 0.2); border-radius: 12px; padding: 16px; margin-bottom: 24px;">
        <span style="color: #00f2fe; font-weight: 700;">💡 How it works:</span>
        <span style="color: #94a3b8; font-size: 0.9rem;">
        Upload any Python, Node.js, Frontend, or Docker project archive. The orchestrator automatically parses the codebase, identifies entry points, maps environment variables and allocates isolated compute resources.
        </span>
    </div>
    """, unsafe_allow_html=True)

    # Option A: Upload file, or Option B: Choose existing zip in workspace
    upload_tab, existing_tab = st.tabs(["📤 Upload New ZIP", "📂 Workspace Archives"])

    selected_zip_path = None
    archive_name = None

    with upload_tab:
        uploaded_file = st.file_uploader("Select project ZIP archive", type=["zip"], help="Maximum archive size: 100 MB")
        if uploaded_file:
            temp_save = TEMP_DIR / f"upload_{uploaded_file.name}"
            with open(temp_save, "wb") as f:
                f.write(uploaded_file.getbuffer())
            selected_zip_path = temp_save
            archive_name = uploaded_file.name

    with existing_tab:
        local_zips = list(PROJECT_ROOT.glob("*.zip"))
        if local_zips:
            zip_options = [z.name for z in local_zips]
            chosen_zip = st.selectbox("Select pre-existing archive from workspace:", zip_options)
            if st.button("Use Selected Archive", key="use_existing_zip"):
                selected_zip_path = PROJECT_ROOT / chosen_zip
                archive_name = chosen_zip
                st.session_state["chosen_archive_path"] = str(selected_zip_path)
                st.session_state["chosen_archive_name"] = archive_name

    if "chosen_archive_path" in st.session_state and not selected_zip_path:
        selected_zip_path = Path(st.session_state["chosen_archive_path"])
        archive_name = st.session_state["chosen_archive_name"]

    if not selected_zip_path:
        return

    st.markdown("---")
    st.markdown(f"### 🔍 Analyzing `{archive_name}`...")

    # Validate and inspect
    temp_extract = TEMP_DIR / f"wizard_extract_{uuid.uuid4()}"
    try:
        file_count, total_bytes = ZipValidator.validate_and_extract(selected_zip_path, temp_extract)
        detection = detector_registry.detect(temp_extract)
    except ZipSecurityError as z_err:
        st.error(f"❌ Security Verification Failed: {z_err}")
        return
    except Exception as ex:
        st.error(f"❌ Extraction error: {ex}")
        return

    # Detection Results Display Card
    col_det1, col_det2, col_det3, col_det4 = st.columns(4)
    with col_det1:
        st.metric("Detected Runtime", detection.runtime.upper())
    with col_det2:
        st.metric("Framework", detection.framework)
    with col_det3:
        st.metric("Entry Point", detection.entry_point)
    with col_det4:
        st.metric("Confidence", detection.confidence.upper())

    # Project configuration form
    with st.form("deployment_config_form"):
        st.subheader("⚙️ Deployment Configuration")

        default_name = Path(archive_name).stem.replace("-main", "").replace("-master", "")
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            project_name = st.text_input("Project Name", value=default_name)
        with c_p2:
            default_sub = "".join(c if c.isalnum() else "-" for c in default_name.lower()).strip("-")
            subdomain = st.text_input("Subdomain URL", value=default_sub, help=f"Will be accessible via http://{default_sub}.{BASE_DOMAIN}")

        c_c1, c_c2, c_c3 = st.columns(3)
        with c_c1:
            process_type = st.selectbox("Process Architecture", ["worker", "web", "static"], index=["worker", "web", "static"].index(detection.process_type))
        with c_c2:
            start_cmd = st.text_input("Start Command", value=detection.start_command)
        with c_c3:
            port_val = st.number_input("Application Port", value=detection.listening_port or 8080 if process_type != "worker" else 0)

        # Environment variables section
        st.markdown("#### 🔑 Detected Environment Variables")
        env_inputs = {}
        if detection.detected_env_vars:
            for v in detection.detected_env_vars:
                req_badge = "🔴 Required" if v.is_required else "⚪ Optional"
                label = f"{v.name} ({req_badge})"
                if v.is_secret:
                    val = st.text_input(label, type="password", value=v.default_value or "", help=v.description)
                else:
                    val = st.text_input(label, value=v.default_value or "", help=v.description)
                env_inputs[v.name] = (val, v.is_secret, v.is_required, v.description)
        else:
            st.caption("No specific environment variables required by code inspection.")

        # Custom variables adder
        custom_vars_raw = st.text_area(
            "Add Custom Environment Variables (.env format)",
            placeholder="CUSTOM_KEY=custom_value\nANOTHER_SECRET=my_secret_token",
            help="One variable per line in KEY=VALUE format"
        )

        submit_deploy = st.form_submit_button("🚀 Deploy Application Now", use_container_width=True)

    if submit_deploy:
        with st.spinner("Deploying application... Storing archive, preparing sandbox, launching service..."):
            project_id = str(uuid.uuid4())
            workspace_dir = WORKSPACES_DIR / project_id

            # Move extracted directory to persistent workspace
            if workspace_dir.exists():
                shutil.rmtree(workspace_dir)
            shutil.move(str(temp_extract), str(workspace_dir))

            # Store in GridFS
            archive_bytes = selected_zip_path.read_bytes()
            gridfs_id = db.save_archive_to_gridfs(archive_bytes, archive_name)

            # Create Project Record
            slug = "".join(c if c.isalnum() else "-" for c in subdomain.lower()).strip("-")
            project_doc = {
                "_id": project_id,
                "name": project_name,
                "slug": slug,
                "owner_id": user["_id"],
                "runtime": detection.runtime,
                "framework": detection.framework,
                "entry_point": detection.entry_point,
                "start_command": start_cmd,
                "process_type": process_type,
                "listening_port": port_val if process_type != "worker" else None,
                "subdomain": slug,
                "status": "pending"
            }
            db.create_project(project_doc)

            # Revision 1
            rev_id = str(uuid.uuid4())
            db.create_revision({
                "_id": rev_id,
                "project_id": project_id,
                "revision_number": 1,
                "commit_message": f"Initial deployment from {archive_name}",
                "author_id": user["_id"],
                "gridfs_id": gridfs_id,
                "file_count": file_count,
                "total_size_bytes": total_bytes
            })
            db.update_project(project_id, {"active_revision_id": rev_id})

            # Save Environment Variables
            for k, (v_val, is_sec, is_req, desc) in env_inputs.items():
                db.set_env_var(project_id, k, encrypt_secret(v_val), is_secret=is_sec, is_required=is_req, description=desc)

            # Parse custom variables
            if custom_vars_raw:
                for line in custom_vars_raw.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        c_k, c_v = line.split("=", 1)
                        c_k, c_v = c_k.strip(), c_v.strip()
                        db.set_env_var(project_id, c_k, encrypt_secret(c_v), is_secret=False)

            # Execute Deployment
            try:
                orchestrator.deploy_project(project_id)
                st.success(f"🎉 Application '{project_name}' deployed successfully!")
                st.session_state["selected_project_id"] = project_id
                st.session_state["current_page"] = "Project Details"
                time.sleep(1)
                st.rerun()
            except Exception as d_err:
                st.error(f"❌ Deployment failed: {d_err}")
