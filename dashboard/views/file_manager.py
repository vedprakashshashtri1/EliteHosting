import os
import uuid
from pathlib import Path
import streamlit as st

from elite_cloud.dashboard.components.cards import render_header
from elite_cloud.storage.db import db
from elite_cloud.config import WORKSPACES_DIR, TEMP_DIR
from elite_cloud.orchestrator.zip_validator import ZipValidator

def render_file_manager(user: dict):
    project_id = st.session_state.get("selected_project_id")
    if not project_id:
        st.warning("Please select a project first.")
        return

    p = db.get_project(project_id)
    if not p:
        st.error("Project not found.")
        return

    ws = WORKSPACES_DIR / project_id
    if not ws.exists():
        ws.mkdir(parents=True, exist_ok=True)

    render_header(f"File Manager: {p.get('name')}", f"GitHub-like code explorer and revision editor for project `{p.get('slug')}`")

    # Top Action Bar: Create File, Create Folder, Download ZIP
    c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 2])
    with c_btn1:
        with st.popover("📄 New File"):
            new_file_name = st.text_input("File path (e.g. src/app.py):")
            if st.button("Create File", key="btn_create_file"):
                if new_file_name:
                    target = ws / new_file_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    st.success(f"Created {new_file_name}")
                    st.rerun()

    with c_btn2:
        with st.popover("📁 New Folder"):
            new_folder_name = st.text_input("Folder path (e.g. assets/css):")
            if st.button("Create Folder", key="btn_create_folder"):
                if new_folder_name:
                    (ws / new_folder_name).mkdir(parents=True, exist_ok=True)
                    st.success(f"Created folder {new_folder_name}")
                    st.rerun()

    with c_btn3:
        # Download ZIP
        temp_zip = TEMP_DIR / f"{p.get('slug')}_export.zip"
        ZipValidator.create_zip_from_dir(ws, temp_zip)
        with open(temp_zip, "rb") as f:
            st.download_button(
                label="📦 Download Complete Project ZIP",
                data=f.read(),
                file_name=f"{p.get('slug')}.zip",
                mime="application/zip",
                use_container_width=True
            )

    st.markdown("---")

    # Collect all project files
    files_list = []
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
        for f in files:
            rel = str(Path(root, f).relative_to(ws)).replace("\\", "/")
            files_list.append(rel)

    files_list.sort()

    col_tree, col_editor = st.columns([1, 3])

    # Left Column: File Tree Explorer
    with col_tree:
        st.markdown("#### 📂 Project Files")
        if not files_list:
            st.caption("No files in workspace.")
            selected_file = None
        else:
            selected_file = st.selectbox("Select file to inspect & edit:", files_list, key="file_selector")

    # Right Column: Code Editor & Revision Commit
    with col_editor:
        if selected_file:
            target_path = ws / selected_file
            st.markdown(f"#### ✏️ Editing `{selected_file}`")

            # Determine syntax highlighting language
            suffix = target_path.suffix.lstrip(".").lower()
            lang_map = {
                "py": "python",
                "js": "javascript",
                "ts": "typescript",
                "html": "html",
                "css": "css",
                "json": "json",
                "md": "markdown",
                "sh": "bash",
                "yaml": "yaml",
                "yml": "yaml",
                "txt": "text"
            }
            code_lang = lang_map.get(suffix, "text")

            # Read current content
            try:
                curr_content = target_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                curr_content = ""

            # Code editor text area
            edited_content = st.text_area(
                label=f"File Editor ({code_lang})",
                value=curr_content,
                height=450,
                key=f"editor_{selected_file}"
            )

            # Commit changes bar
            c_msg, c_save, c_del = st.columns([3, 1, 1])
            with c_msg:
                commit_msg = st.text_input("Commit Message", value=f"Update {selected_file}", key="commit_input")
            with c_save:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("💾 Commit & Save", key="save_file_btn", use_container_width=True):
                    target_path.write_text(edited_content, encoding="utf-8")
                    
                    # Snapshot into GridFS as new revision
                    temp_rev_zip = TEMP_DIR / f"rev_{uuid.uuid4()}.zip"
                    ZipValidator.create_zip_from_dir(ws, temp_rev_zip)
                    gridfs_id = db.save_archive_to_gridfs(temp_rev_zip.read_bytes(), f"{project_id}_rev.zip")
                    temp_rev_zip.unlink(missing_ok=True)

                    rev_count = len(db.list_revisions(project_id))
                    new_rev = db.create_revision({
                        "_id": str(uuid.uuid4()),
                        "project_id": project_id,
                        "revision_number": rev_count + 1,
                        "commit_message": commit_msg or f"Edit {selected_file}",
                        "author_id": user["_id"],
                        "gridfs_id": gridfs_id,
                        "file_count": len(files_list),
                        "total_size_bytes": sum(f.stat().st_size for f in ws.rglob('*') if f.is_file())
                    })
                    db.update_project(project_id, {"active_revision_id": new_rev["_id"]})
                    st.success(f"Committed Revision #{new_rev['revision_number']}! Ready to redeploy.")
                    st.rerun()

            with c_del:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("🗑️ Delete File", key="del_file_btn", use_container_width=True):
                    target_path.unlink(missing_ok=True)
                    st.warning(f"Deleted {selected_file}")
                    st.rerun()
        else:
            st.info("Select a file on the left to view or edit code.")
