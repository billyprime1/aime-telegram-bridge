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
LEAD_PULLER_URL = os.getenv("LEAD_PULLER_URL", "http://localhost:8200")
LEAD_PULLER_KEY = os.getenv("LEAD_PULLER_KEY", "aime-cognitive-pag-2026")

VALID_VERTICALS = ["medspa", "dental", "saas", "ecommerce", "cpa_accounting", "pharma", "manufacturing", "fintech", "all"]
VALID_SIDES = ["seller", "buyer", "both"]

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
        "/leads — Lead puller (pull, status, credits, jobs)\n"
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


# ── Lead Puller Commands ──

async def leads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leads command for pulling leads.
    Usage:
      /leads pull <vertical> <side> <target>
      /leads status <job_id>
      /leads credits
      /leads jobs
    Examples:
      /leads pull dental seller 50
      /leads pull all both 20
      /leads status abc123
      /leads credits
    """
    if not is_owner(update):
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "🔍 Lead Puller Commands\n\n"
            "/leads pull <vertical> <side> <target>\n"
            "  Start a new lead pull\n"
            "  Verticals: medspa, dental, saas, ecommerce, cpa_accounting, pharma, manufacturing, fintech, all\n"
            "  Sides: seller, buyer, both\n"
            "  Target: leads per vertical (5-200)\n\n"
            "/leads status <job_id>\n"
            "  Check status of a running job\n\n"
            "/leads credits\n"
            "  Check LeadMagic credit balance\n\n"
            "/leads jobs\n"
            "  Show recent pull jobs\n\n"
            "Examples:\n"
            "  /leads pull dental seller 50\n"
            "  /leads pull all both 20\n"
            "  /leads credits"
        )
        return

    subcmd = args[0].lower()
    await update.message.chat.send_action(ChatAction.TYPING)

    if subcmd == "pull":
        # Parse: /leads pull <vertical> <side> <target>
        if len(args) < 4:
            await update.message.reply_text(
                "⚠️ Usage: /leads pull <vertical> <side> <target>\n"
                "Example: /leads pull dental seller 50"
            )
            return

        vertical = args[1].lower()
        side = args[2].lower()
        try:
            target = min(200, max(5, int(args[3])))
        except ValueError:
            await update.message.reply_text("⚠️ Target must be a number (5-200)")
            return

        if vertical not in VALID_VERTICALS:
            await update.message.reply_text(f"⚠️ Invalid vertical: {vertical}\nValid: {', '.join(VALID_VERTICALS)}")
            return
        if side not in VALID_SIDES:
            await update.message.reply_text(f"⚠️ Invalid side: {side}\nValid: seller, buyer, both")
            return

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{LEAD_PULLER_URL}/pull",
                    headers={"X-API-Key": LEAD_PULLER_KEY, "Content-Type": "application/json"},
                    json={"vertical": vertical, "side": side, "target": target, "max_credits": 2000},
                )
                data = resp.json()

            if resp.status_code in (200, 201, 202):
                job_id = data.get("job_id", "?")
                est_credits = round(target * (8 if vertical == "all" else 1) * 1.4)
                await update.message.reply_text(
                    f"🚀 Lead Pull Started\n\n"
                    f"• Job: {job_id}\n"
                    f"• Vertical: {vertical}\n"
                    f"• Side: {side}\n"
                    f"• Target: {target}/vertical\n"
                    f"• Est. credits: ~{est_credits}\n\n"
                    f"Check status: /leads status {job_id}"
                )
            else:
                await update.message.reply_text(f"⚠️ {data.get('error', 'Unknown error')}")
        except Exception as e:
            await update.message.reply_text(f"❌ Lead puller service error: {str(e)[:200]}")

    elif subcmd == "status":
        if len(args) < 2:
            await update.message.reply_text("⚠️ Usage: /leads status <job_id>")
            return

        job_id = args[1]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LEAD_PULLER_URL}/status/{job_id}",
                    headers={"X-API-Key": LEAD_PULLER_KEY},
                )
                data = resp.json()

            if resp.status_code == 404:
                await update.message.reply_text(f"⚠️ Job {job_id} not found")
                return

            status_emoji = {
                "completed": "✅", "running": "⏳", "queued": "📦", "failed": "❌"
            }.get(data.get("status"), "❓")

            msg = f"{status_emoji} Job {data.get('id', job_id)} — {data.get('status', '?').upper()}\n"
            msg += f"• Vertical: {data.get('vertical')} | Side: {data.get('side')}\n"

            progress = data.get("progress", {})
            if progress and data.get("status") in ("running", "queued"):
                msg += f"• Leads found: {progress.get('leads_found', 0)}\n"
                msg += f"• Credits used: {progress.get('credits_used', 0)}\n"
                if progress.get("current_vertical"):
                    msg += f"• Current: {progress.get('current_side')} / {progress.get('current_vertical')}\n"

            results = data.get("results")
            if results and data.get("status") == "completed":
                msg += f"\n📊 Results:\n"
                msg += f"• Total leads: {results.get('total_leads', 0)}\n"
                by_side = results.get("leads_by_side", {})
                msg += f"• Sellers: {by_side.get('seller', 0)} | Buyers: {by_side.get('buyer', 0)}\n"
                msg += f"• LM credits used: {results.get('credits_used', 0)}\n"
                by_vert = results.get("leads_by_vertical", {})
                if by_vert:
                    msg += "\nBy vertical:\n"
                    for v, c in sorted(by_vert.items()):
                        msg += f"  {v}: {c}\n"

            if data.get("error"):
                msg += f"\n❌ Error: {data['error']}"

            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")

    elif subcmd == "credits":
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LEAD_PULLER_URL}/credits",
                    headers={"X-API-Key": LEAD_PULLER_KEY},
                )
                data = resp.json()

            remaining = data.get("credits_remaining", data.get("credits", "?"))
            await update.message.reply_text(f"💳 LeadMagic Credits: {remaining:,}" if isinstance(remaining, (int, float)) else f"💳 LeadMagic: {remaining}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error checking credits: {str(e)[:200]}")

    elif subcmd == "jobs":
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LEAD_PULLER_URL}/jobs",
                    headers={"X-API-Key": LEAD_PULLER_KEY},
                )
                data = resp.json()

            if not data:
                await update.message.reply_text("📂 No recent lead pull jobs")
                return

            msg = "📂 Recent Lead Pulls\n\n"
            for j in data[:10]:
                status_emoji = {"completed": "✅", "running": "⏳", "queued": "📦", "failed": "❌"}.get(j.get("status"), "❓")
                msg += f"{status_emoji} {j.get('id')} — {j.get('vertical')} {j.get('side')} → {j.get('total_leads', 0)} leads\n"
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")

    else:
        await update.message.reply_text(
            f"⚠️ Unknown subcommand: {subcmd}\n"
            "Use: /leads pull, /leads status, /leads credits, /leads jobs"
        )


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
    app.add_handler(CommandHandler("leads", leads_cmd))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
