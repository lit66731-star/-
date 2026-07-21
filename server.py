"""
Auto Messenger MCP Server
==========================
An MCP server that provides message sending tools for AI clients like Kelivo.
Deploy to Fly.io (free) and connect from iOS Kelivo app via SSE transport.

Usage:
    python server.py              # default SSE transport on port 8000
    python server.py --port 8080  # custom port
"""

import os
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastmcp import FastMCP

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("auto-messenger")

# ── Config ───────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
MESSAGE_LOG_FILE = os.environ.get("MESSAGE_LOG_FILE", "/tmp/auto-messages.jsonl")
SERVER_NAME = os.environ.get("SERVER_NAME", "Auto Messenger")

# ── FastMCP App ──────────────────────────────────────────────────────
mcp = FastMCP(SERVER_NAME)


# ── Helpers ──────────────────────────────────────────────────────────
def log_message(content: str, status: str = "sent") -> dict:
    """Write a message to the local JSONL log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "status": status,
    }
    try:
        os.makedirs(os.path.dirname(MESSAGE_LOG_FILE) or ".", exist_ok=True)
        with open(MESSAGE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("Failed to write message log: %s", e)
    return entry


async def post_to_webhook(content: str) -> dict:
    """POST a message to the configured webhook URL. Returns result info."""
    payload = {
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "auto-messenger-mcp",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(WEBHOOK_URL, json=payload)
        resp.raise_for_status()
        return {"status_code": resp.status_code, "response": resp.text[:200]}


# ── MCP Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def send_message(content: str) -> str:
    """
    Send a single message immediately.

    - If a WEBHOOK_URL is configured (Discord, Slack, custom API, etc.),
      the message is POSTed to that URL.
    - Otherwise the message is logged locally and returned for display
      in the chat (Kelivo / Claude Code will show it).

    Use this when you need to send a single message to the configured channel.

    Args:
        content: The exact text you want to send.

    Returns:
        A confirmation string showing what happened.
    """
    logger.info("Sending message (first 80 chars): %s", content[:80])

    # Webhook mode
    if WEBHOOK_URL:
        try:
            result = await post_to_webhook(content)
            log_message(content, "sent_to_webhook")
            return (
                f"✅ Message delivered to webhook (HTTP {result['status_code']})\n"
                f"   Content: {content}"
            )
        except Exception as exc:
            logger.error("Webhook send failed: %s", exc)
            log_message(content, f"webhook_failed: {exc}")
            return f"❌ Webhook send failed: {exc}\n   Message was NOT sent."

    # Local-only mode — message appears in chat
    log_message(content, "displayed")
    return f"📤 Message sent:\n{content}"


@mcp.tool()
async def send_batch(messages: list[str]) -> str:
    """
    Send 2-3 messages in a batch — exactly what you need for the
    "every 5 minutes, 2-3 messages" workflow.

    Each message is sent independently; results are collected and
    returned as a single summary.

    Args:
        messages: A list of message strings, e.g. ["Hello!", "How are you?", "Bye!"]

    Returns:
        A numbered summary of each message's delivery status.
    """
    logger.info("Sending batch of %d messages", len(messages))

    if not messages:
        return "⚠️ No messages provided. Nothing was sent."

    results = []
    for i, msg in enumerate(messages, 1):
        result = await send_message(msg)
        results.append(f"  {i}. {result}")

    summary = f"📬 Batch complete — {len(messages)} message(s):\n" + "\n".join(results)
    return summary


@mcp.tool()
async def get_history(limit: int = 20) -> str:
    """
    Read back recent messages from the server-side log.

    Useful for checking what was sent in previous batches and
    avoiding repetition.

    Args:
        limit: How many recent messages to return (default 20, max 100).

    Returns:
        Timestamped history of recent messages.
    """
    limit = min(max(limit, 1), 100)

    try:
        with open(MESSAGE_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return "📭 No message history yet — nothing has been sent."

    recent = lines[-limit:]
    out_lines = []
    for line in recent:
        try:
            e = json.loads(line)
            ts = e.get("timestamp", "?")[:19]
            st = e.get("status", "?")
            ct = e.get("content", "")[:120]
            out_lines.append(f"[{ts}] {st}: {ct}")
        except json.JSONDecodeError:
            continue

    if not out_lines:
        return "📭 No valid entries in history."

    return "📋 Recent messages:\n" + "\n".join(out_lines)


@mcp.tool()
async def clear_history() -> str:
    """
    Delete all locally logged message history. Irreversible.
    Use before starting a fresh session.
    """
    try:
        os.remove(MESSAGE_LOG_FILE)
        return "🗑️ Message history cleared."
    except FileNotFoundError:
        return "📭 No history to clear."
    except Exception as exc:
        return f"❌ Failed to clear history: {exc}"


# ── Entrypoint ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto Messenger MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port to listen on (default: 8000, or $PORT env var)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--transport",
        default="sse",
        choices=["sse", "streamable-http"],
        help="MCP transport protocol (default: sse)",
    )
    args = parser.parse_args()

    logger.info(
        "Starting '%s' on %s:%d (transport=%s)",
        SERVER_NAME, args.host, args.port, args.transport,
    )
    logger.info("Webhook: %s", "configured" if WEBHOOK_URL else "NOT configured (local-only mode)")

    mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
