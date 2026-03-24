"""
AIME Telegram Operator Console
Connects Billy's Telegram directly to Agent 71 (Friday) via the AIME Runner.
Full read + write access to the entire AIME platform.

This is NOT a chatbot wrapper — it's an operator console.
Agent 71 has tools: supabase, web_search, slack, gmail, gdrive, ghl, sheets, leadmagic
Everything Billy asks gets executed through the full intelligence stack.
"""

import os
import json
import asyncio
import logging
import httpx
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode, ChatAction

# ── Config ──
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("TELEGRAM_OWNER_ID", "0"))
AGENT_RUNNER_URL = os.getenv("AGENT_RUNNER_URL", "http://localhost:8100")
AGENT_ID = int(os.getenv("AGENT_ID", "71"))
API_KEY = os.getenv("AGENT_RUNNER_API_KEY", "aime-runner-pag-2026")
USER_ID = os.getenv("AIME_USER_ID", "c832b518-8d44-41dd-ac74-b75500d7ce4b")

# Telegram message limit
TG_MAX_LEN = 4000

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("aime-telegram")

# ── Session tracking (one persistent session per user) ──
_session_id: str | None = None


def chunk_message(text: str, max_len: int = TG_MAX_LEN) -> list[str]:
    """Split a long message into Telegram-safe chunks, breaking at newlines."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last newline before the limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            # No newline — find last space
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            # No space either — hard cut
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def call_agent(message: str) -> str:
    """Send a message to Agent 71 via AIME Runner and return the response."""
    global _session_id

    payload = {
        "message": message,
        "user_id": USER_ID,
    }
    if _session_id:
        payload["session_id"] = _session_id

    url = f"{AGENT_RUNNER_URL}/agents/{AGENT_ID}/run?api_key={API_KEY}"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Persist session for conversation continuity
    if data.get("session_id"):
        _session_id = data["session_id"]

    return data.get("response") or data.get("message") or "No response from Friday."


def is_owner(update: Update) -> bool:
    """Only respond to the owner."""
    return update.effective_user and update.effective_user.id == OWNER_ID


# ── Handlers ──

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.reply_text(
        "⚡ AIME Operator Console — Online\n\n"
        "You have full access to the AIME platform through Agent 71.\n\n"
        "Ask anything — KPIs, deal pipeline, VP reports, market intel.\n"
        "Give commands — add buy boxes, update campaigns, manage leads.\n"
        "Send documents — P&Ls, contracts, spreadsheets for analysis.\n\n"
        "Commands:\n"
        "/status — System health check\n"
        "/reset — Clear conversation context\n"
        "/help — Show this message"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.reply_text(
        "🔧 AIME Operator Console\n\n"
        "Just type naturally. Examples:\n"
        "• \"What are today's KPIs?\"\n"
        "• \"What did the VP of Sales report?\"\n"
        "• \"Add a new dental buy box, $1M-$3M, Southeast US\"\n"
        "• \"Pause the deal hunter agent\"\n"
        "• \"How many deals came in this week?\"\n"
        "• \"Draft an LOI for the medspa deal at $2.5M\"\n"
        "• \"Show me the buyer pipeline status\"\n"
        "• \"Search for SaaS companies doing $500K+ ARR in Texas\"\n\n"
        "/status — Quick system health\n"
        "/reset — Fresh conversation\n"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{AGENT_RUNNER_URL}/health?api_key={API_KEY}"
            )
            health = resp.json()
            status = "✅ Online" if resp.status_code == 200 else "⚠️ Degraded"
    except Exception as e:
        status = f"❌ Offline — {e}"
        health = {}

    msg = f"📡 AIME System Status: {status}\n"
    if health:
        msg += f"• Runner: {health.get('status', 'unknown')}\n"
        msg += f"• Agents: {health.get('agents_loaded', '?')}\n"
    msg += f"• Session: {'Active' if _session_id else 'New'}\n"
    msg += f"• Agent: Friday (ID {AGENT_ID})"

    await update.message.reply_text(msg)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    global _session_id
    _session_id = None
    await update.message.reply_text("🔄 Conversation reset. Fresh context.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward text messages to Agent 71."""
    if not is_owner(update):
        return

    user_text = update.message.text
    if not user_text:
        return

    log.info(f"Message from owner: {user_text[:100]}...")
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        response = await call_agent(user_text)
    except httpx.HTTPStatusError as e:
        response = f"⚠️ Runner returned {e.response.status_code}. Service may be restarting."
        log.error(f"Agent call failed: {e}")
    except httpx.ConnectError:
        response = "⚠️ Can't reach the AIME Runner. Service may be down."
        log.error("Connection refused to AIME Runner")
    except Exception as e:
        response = f"⚠️ Error: {str(e)[:200]}"
        log.error(f"Unexpected error: {e}")

    # Send response, chunked if needed
    chunks = chunk_message(response)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk)
        except Exception as e:
            # If markdown fails, send as plain text
            await update.message.reply_text(chunk)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads — describe to Agent 71 for analysis."""
    if not is_owner(update):
        return

    doc = update.message.document
    caption = update.message.caption or ""

    # Tell Agent 71 about the document
    msg = f"[User uploaded a document: {doc.file_name} ({doc.mime_type}, {doc.file_size} bytes)]"
    if caption:
        msg += f"\nUser says: {caption}"
    else:
        msg += "\nPlease analyze this document and provide key insights."

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        response = await call_agent(msg)
    except Exception as e:
        response = f"⚠️ Error processing document: {str(e)[:200]}"

    chunks = chunk_message(response)
    for chunk in chunks:
        await update.message.reply_text(chunk)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads."""
    if not is_owner(update):
        return

    caption = update.message.caption or ""
    msg = "[User sent a photo/screenshot]"
    if caption:
        msg += f"\nUser says: {caption}"
    else:
        msg += "\nPlease analyze what's in this image."

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        response = await call_agent(msg)
    except Exception as e:
        response = f"⚠️ Error: {str(e)[:200]}"

    chunks = chunk_message(response)
    for chunk in chunks:
        await update.message.reply_text(chunk)


def main():
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        return
    if OWNER_ID == 0:
        log.error("TELEGRAM_OWNER_ID not set")
        return

    log.info(f"Starting AIME Telegram Console — Agent {AGENT_ID}")
    log.info(f"Runner: {AGENT_RUNNER_URL}")
    log.info(f"Owner: {OWNER_ID}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
