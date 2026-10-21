import random
import string
import streamlit as st

from elite_cloud.dashboard.components.cards import render_header
from elite_cloud.storage.db import db
from elite_cloud.config import TELEGRAM_BOT_USERNAME

def render_telegram_link(user: dict):
    render_header("Telegram Bot Remote Management", "Deploy, monitor, restart and inspect your applications directly via Telegram.")

    user_id = user["_id"]
    db_user = db.db.users.find_one({"_id": user_id})
    is_linked = bool(db_user.get("telegram_chat_id"))

    if is_linked:
        st.success(f"✅ **Your account is actively linked to Telegram!** (Chat ID: `{db_user['telegram_chat_id']}`)")
        st.markdown(f"""
        You can send commands directly to **@{TELEGRAM_BOT_USERNAME}**:
        - Send any `.zip` archive to automatically build & deploy!
        - `/projects` - List all your services with inline buttons
        - `/status` - Check live health
        - `/resources` - View CPU & RAM load
        """)
        if st.button("Unlink Telegram Account"):
            db.db.users.update_one({"_id": user_id}, {"$set": {"telegram_chat_id": None}})
            st.rerun()
    else:
        st.info("Your account is currently **not linked** to the Telegram Management Bot.")

        st.markdown("""
        ### 🔗 Link Your Account in 2 Simple Steps:
        1. Open the Telegram Bot: **[@EliteCloudManagerBot](https://t.me/EliteCloudManagerBot)**
        2. Generate a 6-digit pairing code below and send `/account <code>` to the bot.
        """)

        if st.button("🔑 Generate One-Time 6-Digit Pairing Code", key="btn_gen_code"):
            code = "".join(random.choices(string.digits, k=6))
            db.create_telegram_link(user_id, code, minutes_valid=15)
            st.session_state["active_pairing_code"] = code

        if "active_pairing_code" in st.session_state:
            code = st.session_state["active_pairing_code"]
            st.markdown(f"""
            <div style="background: rgba(0, 242, 254, 0.1); border: 2px dashed #00f2fe; border-radius: 12px; padding: 24px; text-align: center; margin: 20px 0;">
                <div style="font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px;">Your 15-Minute Pairing Code</div>
                <div style="font-size: 3rem; font-weight: 800; color: #00f2fe; font-family: monospace; letter-spacing: 8px; margin: 8px 0;">{code}</div>
                <div style="font-size: 0.85rem; color: #cbd5e1;">Send to bot: <code>/account {code}</code></div>
            </div>
            """, unsafe_allow_html=True)
