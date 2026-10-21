import os
import io
import time
import uuid
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from elite_cloud.config import TELEGRAM_BOT_TOKEN, TEMP_DIR, WORKSPACES_DIR, BASE_DOMAIN
from elite_cloud.storage.db import db
from elite_cloud.storage.security import mask_secrets, encrypt_secret, decrypt_secret
from elite_cloud.detectors.registry import detector_registry
from elite_cloud.orchestrator.zip_validator import ZipValidator, ZipSecurityError
from elite_cloud.orchestrator.deployment_queue import orchestrator
from elite_cloud.orchestrator.process_manager import process_manager
from elite_cloud.orchestrator.metrics_collector import MetricsCollector

logger = logging.getLogger("elite_cloud.telegram")

def get_linked_user(chat_id: int) -> Optional[Dict[str, Any]]:
    return db.get_user_by_telegram_chat_id(chat_id)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_linked_user(chat_id)

    if not user:
        msg = (
            "🚀 *Welcome to Elite Cloud Hosting Remote Manager*\n\n"
            "Your Telegram account is not yet paired with an account on the platform.\n\n"
            "To pair your account:\n"
            "1. Log in to the Streamlit Dashboard.\n"
            "2. Navigate to **Telegram Integration**.\n"
            "3. Generate a 6-digit pairing code.\n"
            "4. Send `/account <code>` here (e.g. `/account 123456`)."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    msg = (
        f"👋 *Welcome back, {user['username']}!*\n\n"
        "⚡ *Elite Cloud Management Bot is Ready*\n\n"
        "You can manage all your cloud applications, bots and websites directly from here.\n\n"
        "📦 *To deploy a new app:* Simply send any **ZIP archive** directly to this chat!\n\n"
        "📌 *Quick Commands:*\n"
        "• `/projects` - View & manage your projects\n"
        "• `/resources` - View system CPU, RAM & disk\n"
        "• `/help` - View all available commands"
    )
    keyboard = [
        [InlineKeyboardButton("📂 My Projects", callback_data="list_projects")],
        [InlineKeyboardButton("📊 System Resources", callback_data="system_resources")]
    ]
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ Please provide your 6-digit code. Example:\n`/account 123456`", parse_mode="Markdown")
        return

    code = context.args[0].strip()
    user_id = db.verify_and_consume_telegram_link(code, chat_id)
    if user_id:
        user = db.db.users.find_one({"_id": user_id})
        await update.message.reply_text(
            f"✅ *Success! Account successfully linked to `{user['username']}`.*\n"
            "You can now manage deployments or send ZIP files to deploy immediately.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ *Invalid or expired pairing code.* Please generate a new one on the dashboard.", parse_mode="Markdown")

async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_linked_user(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please pair your account first using `/account <code>`.")
        return

    projects = db.list_projects(owner_id=user["_id"] if user.get("role") != "admin" else None)
    if not projects:
        await update.message.reply_text("📦 You have no projects yet. Send a ZIP file to deploy one!")
        return

    keyboard = []
    text_lines = ["📂 *Your Applications & Bots:*\n"]
    for p in projects:
        slug = p.get("slug")
        status_emoji = "🟢" if process_manager.is_running(p["_id"]) else "🔴"
        text_lines.append(f"{status_emoji} *{p.get('name')}* (`{slug}`) - {p.get('runtime', '').upper()} / {p.get('framework', '')}")
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} {p.get('name')}", callback_data=f"proj_{p['_id']}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("\n".join(text_lines), parse_mode="Markdown", reply_markup=reply_markup)

async def cmd_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys_m = MetricsCollector.get_system_metrics()
    msg = (
        "📊 *Elite Cloud Infrastructure Status:*\n\n"
        f"• **CPU Load:** `{sys_m['system_cpu_percent']}%`\n"
        f"• **RAM Usage:** `{sys_m['system_memory_used_mb']} MB` / `{sys_m['system_memory_total_mb']} MB` ({sys_m['system_memory_percent']}%)\n"
        f"• **Storage:** `{sys_m['system_disk_used_gb']} GB` / `{sys_m['system_disk_total_gb']} GB` ({sys_m['system_disk_percent']}%)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_linked_user(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first via `/account <code>` before deploying.")
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith(".zip"):
        await update.message.reply_text("⚠️ Only `.zip` archives are supported for deployment.")
        return

    status_msg = await update.message.reply_text("📥 *Receiving archive... Validating safety and scanning project...*", parse_mode="Markdown")

    # Download file
    temp_zip = TEMP_DIR / f"tg_{uuid.uuid4()}_{doc.file_name}"
    temp_extract = TEMP_DIR / f"tg_extract_{uuid.uuid4()}"

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(str(temp_zip))

        # Validate & Extract
        file_count, total_bytes = ZipValidator.validate_and_extract(temp_zip, temp_extract)

        # Detect
        detection = detector_registry.detect(temp_extract)

        # Prepare Project
        raw_name = Path(doc.file_name).stem.replace("-main", "").replace("-master", "")
        slug = "".join(c if c.isalnum() else "-" for c in raw_name.lower()).strip("-")
        existing = db.get_project_by_slug(slug)
        if existing:
            slug = f"{slug}-{int(time.time()) % 1000}"

        project_id = str(uuid.uuid4())
        workspace_dir = WORKSPACES_DIR / project_id
        os.rename(temp_extract, workspace_dir)

        # Store in GridFS
        gridfs_id = db.save_archive_to_gridfs(temp_zip.read_bytes(), doc.file_name)

        project_data = {
            "_id": project_id,
            "name": raw_name,
            "slug": slug,
            "owner_id": user["_id"],
            "runtime": detection.runtime,
            "framework": detection.framework,
            "entry_point": detection.entry_point,
            "start_command": detection.start_command,
            "process_type": detection.process_type,
            "listening_port": detection.listening_port,
            "subdomain": slug,
            "status": "pending"
        }
        db.create_project(project_data)

        # Revision 1
        rev_id = str(uuid.uuid4())
        db.create_revision({
            "_id": rev_id,
            "project_id": project_id,
            "revision_number": 1,
            "commit_message": "Deployed via Telegram Bot",
            "author_id": user["_id"],
            "gridfs_id": gridfs_id,
            "file_count": file_count,
            "total_size_bytes": total_bytes
        })
        db.update_project(project_id, {"active_revision_id": rev_id})

        # Save detected variables
        for v in detection.detected_env_vars:
            db.set_env_var(
                project_id=project_id,
                key=v.name,
                value_encrypted=encrypt_secret(v.default_value or ""),
                is_secret=v.is_secret,
                is_required=v.is_required,
                description=v.description
            )

        # Auto Deploy
        # Deployment performs filesystem, package and process work. Run it off
        # the Telegram event loop so commands and status updates stay responsive.
        await asyncio.to_thread(orchestrator.deploy_project, project_id)

        # Send deployment summary
        msg = (
            f"🚀 *Project Deployed Successfully!*\n\n"
            f"• **Project Name:** `{raw_name}`\n"
            f"• **Runtime:** `{detection.runtime.upper()}` ({detection.framework})\n"
            f"• **Entry Point:** `{detection.entry_point}`\n"
            f"• **Process Type:** `{detection.process_type.upper()}`\n"
            f"• **Start Command:** `{detection.start_command}`\n"
        )
        if detection.listening_port:
            msg += f"• **Subdomain URL:** `http://{slug}.{BASE_DOMAIN}`\n"

        keyboard = [
            [InlineKeyboardButton("📜 View Logs", callback_data=f"logs_{project_id}")],
            [InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{project_id}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{project_id}")]
        ]
        await status_msg.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    except ZipSecurityError as z_err:
        await status_msg.edit_text(f"❌ Archive security error:\n{z_err}")
    except Exception as e:
        logger.exception("Telegram deployment failed for %s", doc.file_name)
        await status_msg.edit_text(f"❌ Deployment failed:\n{e}")
    finally:
        if temp_zip.exists():
            temp_zip.unlink()

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "list_projects":
        chat_id = update.effective_chat.id
        user = get_linked_user(chat_id)
        if not user:
            await query.edit_message_text("Please link your account first.")
            return
        projects = db.list_projects(owner_id=user["_id"] if user.get("role") != "admin" else None)
        keyboard = [[InlineKeyboardButton(f"{'🟢' if process_manager.is_running(p['_id']) else '🔴'} {p['name']}", callback_data=f"proj_{p['_id']}")] for p in projects]
        await query.edit_message_text("📂 *Select a Project:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("proj_"):
        project_id = data.split("proj_", 1)[1]
        p = db.get_project(project_id)
        if not p:
            await query.edit_message_text("Project not found.")
            return
        is_running = process_manager.is_running(project_id)
        status_str = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        msg = (
            f"📦 *{p.get('name')}*\n"
            f"• Status: {status_str}\n"
            f"• Runtime: `{p.get('runtime')}` / `{p.get('framework')}`\n"
            f"• Start: `{p.get('start_command')}`\n"
        )
        if p.get("listening_port"):
            msg += f"• URL: `http://{p.get('subdomain')}.{BASE_DOMAIN}`\n"

        keyboard = [
            [InlineKeyboardButton("📜 Logs", callback_data=f"logs_{project_id}")],
            [
                InlineKeyboardButton("▶️ Start", callback_data=f"start_{project_id}") if not is_running else InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{project_id}"),
                InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{project_id}")
            ],
            [InlineKeyboardButton("🔙 Back to Projects", callback_data="list_projects")]
        ]
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("start_"):
        pid = data.split("start_", 1)[1]
        await asyncio.to_thread(orchestrator.deploy_project, pid)
        await query.edit_message_text("▶️ *Application started!*", parse_mode="Markdown")

    elif data.startswith("stop_"):
        pid = data.split("stop_", 1)[1]
        orchestrator.stop_project(pid)
        await query.edit_message_text("🛑 *Application stopped.*", parse_mode="Markdown")

    elif data.startswith("restart_"):
        pid = data.split("restart_", 1)[1]
        await asyncio.to_thread(orchestrator.restart_project, pid)
        await query.edit_message_text("🔄 *Application restarted!*", parse_mode="Markdown")

    elif data.startswith("logs_"):
        pid = data.split("logs_", 1)[1]
        logs = db.get_logs(pid, limit=25)
        log_text = "\n".join([f"[{l['source'].upper()}] {l['message']}" for l in logs]) or "No logs available yet."
        if len(log_text) > 3500:
            log_text = log_text[-3500:]
        await query.edit_message_text(f"📜 *Recent Logs:*\n```\n{log_text}\n```", parse_mode="Markdown")

def create_telegram_bot() -> Optional[Application]:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not provided. Telegram bot runner disabled.")
        return None
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("account", cmd_account))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("resources", cmd_resources))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(callback_router))
    return app
