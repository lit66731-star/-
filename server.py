"""
Auto Messenger MCP Server (Context-Aware)
==========================================
An MCP server for AI clients like Kelivo that supports context-aware
auto-messaging — every message is tracked in a conversation log so the
AI can read history and generate contextually relevant replies.

Usage:
    python server.py              # SSE transport on port 8000
    python server.py --port 8080  # custom port
"""

import os
import json
import logging
import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path
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
CONVERSATION_FILE = os.environ.get("CONVERSATION_FILE", "/tmp/auto-conversation.jsonl")
SERVER_NAME = os.environ.get("SERVER_NAME", "Auto Messenger")

# Thread lock for file writes (server may handle concurrent requests)
_file_lock = threading.Lock()

# ── FastMCP App ──────────────────────────────────────────────────────
mcp = FastMCP(SERVER_NAME)


# ── Conversation Store ───────────────────────────────────────────────

def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _append_entry(entry: dict) -> dict:
    """Thread-safe append to the conversation JSONL file."""
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _file_lock:
        _ensure_dir(CONVERSATION_FILE)
        with open(CONVERSATION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _read_entries(limit: int = 50) -> list[dict]:
    """Read the most recent entries from the conversation file."""
    try:
        with _file_lock:
            with open(CONVERSATION_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
    except FileNotFoundError:
        return []

    recent = lines[-limit:]
    entries = []
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


# ── Helpers ──────────────────────────────────────────────────────────

async def post_to_webhook(content: str) -> dict:
    """POST a message to the configured webhook URL."""
    payload = {
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "auto-messenger-mcp",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(WEBHOOK_URL, json=payload)
        resp.raise_for_status()
        return {"status_code": resp.status_code, "response": resp.text[:200]}


def _format_entries(entries: list[dict], max_content_len: int = 300) -> str:
    """Format conversation entries into readable text."""
    if not entries:
        return "（暂无聊天记录）"

    lines = []
    for e in entries:
        ts = e.get("timestamp", "?")[:19]
        role = e.get("role", "?")
        content = e.get("content", "")
        if len(content) > max_content_len:
            content = content[:max_content_len] + "..."
        # Visual markers for roles
        role_icon = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role, "📝")
        lines.append(f"[{ts}] {role_icon} {role}: {content}")
    return "\n".join(lines)


# ── MCP Tools ────────────────────────────────────────────────────────

# ═════════════════════════════════════════════════════════════════════
#  CONTEXT TOOLS  — 记忆 & 读取聊天记录
# ═════════════════════════════════════════════════════════════════════

@mcp.tool()
async def save_context(role: str, content: str) -> str:
    """
    保存一条聊天记录到对话上下文中。在发送消息或收到消息后调用，
    这样 AI 下次触发时可以通过 get_context 了解之前聊了什么。

    使用场景：
    - 收到用户消息后：save_context(role="user", content="用户说的话")
    - 发送消息后：save_context(role="assistant", content="你发送的内容")

    Args:
        role: 角色 — "user"（用户）、"assistant"（AI）、或 "system"（系统）
        content: 消息内容

    Returns:
        保存确认
    """
    if role not in ("user", "assistant", "system"):
        return f"⚠️ 无效角色 '{role}'，请用 user / assistant / system"

    entry = _append_entry({"role": role, "content": content})
    ts = entry["timestamp"][:19]
    logger.info("Context saved: [%s] %s: %s", role, ts, content[:60])
    return f"✅ 已保存 [{ts}] {role}: {content[:80]}{'...' if len(content) > 80 else ''}"


@mcp.tool()
async def get_context(limit: int = 30) -> str:
    """
    读取最近的对话上下文。这是核心工具 — 在生成消息前先调用它，
    了解之前聊了什么，确保生成的回复不脱节、不重复。

    Args:
        limit: 读取最近多少条记录（默认 30，最大 100）

    Returns:
        格式化的对话历史
    """
    limit = min(max(limit, 1), 100)
    entries = _read_entries(limit)

    if not entries:
        return "📭 还没有任何聊天记录。请先通过 save_context 保存对话。"

    # Summary statistics
    roles = {}
    for e in entries:
        roles[e.get("role", "?")] = roles.get(e.get("role", "?"), 0) + 1

    stats = "、".join(f"{r}: {c}条" for r, c in sorted(roles.items()))
    body = _format_entries(entries)

    return (
        f"📋 最近 {len(entries)} 条对话记录（{stats}）\n"
        f"{'─' * 50}\n"
        f"{body}\n"
        f"{'─' * 50}\n"
        f"⚠️ 请基于以上上下文生成回复，不要脱离对话内容乱发消息。"
    )


@mcp.tool()
async def get_last_user_message() -> str:
    """
    快速获取用户最后一条消息。当你只需要知道用户最近说了什么时使用。

    Returns:
        用户最后一条消息的内容和时间
    """
    entries = _read_entries(100)
    for e in reversed(entries):
        if e.get("role") == "user":
            ts = e.get("timestamp", "?")[:19]
            return f"[{ts}] 用户最后说：{e['content']}"
    return "📭 还没有用户消息。"


# ═════════════════════════════════════════════════════════════════════
#  MESSAGE TOOLS  — 发送消息
# ═════════════════════════════════════════════════════════════════════

@mcp.tool()
async def send_message(content: str) -> str:
    """
    发送单条消息，并自动保存到对话上下文（role=assistant）。

    调用前请确保已通过 get_context 了解对话背景，
    确保发送的内容与当前对话相关。

    - 如果配置了 WEBHOOK_URL，消息会 POST 到该 URL
    - 否则消息记录在本地并返回显示

    Args:
        content: 要发送的消息文本

    Returns:
        发送结果
    """
    logger.info("Sending: %s", content[:80])

    # 1. Save to context as assistant message
    _append_entry({"role": "assistant", "content": content})

    # 2. Webhook mode
    if WEBHOOK_URL:
        try:
            result = await post_to_webhook(content)
            return (
                f"✅ 已发送到 webhook (HTTP {result['status_code']})\n"
                f"   {content}"
            )
        except Exception as exc:
            logger.error("Webhook failed: %s", exc)
            return f"❌ Webhook 发送失败: {exc}"

    # 3. Local mode
    return f"📤 已发送:\n{content}"


@mcp.tool()
async def send_batch(messages: list[str]) -> str:
    """
    批量发送 2-3 条消息。每条自动保存到对话上下文。

    ⚠️ 重要：调用前必须先调用 get_context 了解对话背景！
    每条消息应该承接上一句，像正常聊天一样自然衔接，
    不要每条都说一个完全不相关的话题。

    推荐用法：
    1. get_context(limit=20) — 了解最近聊了什么
    2. 基于上下文生成 2-3 条自然的接话
    3. send_batch(messages=[...]) — 发送

    Args:
        messages: 消息列表，2-3条为宜，之间有逻辑关联

    Returns:
        发送结果汇总
    """
    if not messages:
        return "⚠️ 没有要发送的消息。"

    logger.info("Batch sending %d messages", len(messages))

    results = []
    for i, msg in enumerate(messages, 1):
        # Save to context
        _append_entry({"role": "assistant", "content": msg})

        # Send via webhook if configured
        if WEBHOOK_URL:
            try:
                r = await post_to_webhook(msg)
                results.append(f"  {i}. ✅ {msg[:60]}...")
            except Exception as exc:
                results.append(f"  {i}. ❌ 失败: {exc}")
        else:
            results.append(f"  {i}. 📤 {msg}")

    summary = f"📬 已发送 {len(messages)} 条消息:\n" + "\n".join(results)
    return summary


# ═════════════════════════════════════════════════════════════════════
#  HOUSEKEEPING TOOLS
# ═════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_stats() -> str:
    """
    查看对话统计：总消息数、时间跨度、角色分布。
    用于了解当前对话状态。
    """
    entries = _read_entries(1000)
    if not entries:
        return "📭 还没有任何记录。"

    total = len(entries)
    roles = {}
    for e in entries:
        roles[e.get("role", "?")] = roles.get(e.get("role", "?"), 0) + 1

    first_ts = entries[0].get("timestamp", "?")[:19]
    last_ts = entries[-1].get("timestamp", "?")[:19]

    role_info = "\n".join(f"  {r}: {c} 条" for r, c in sorted(roles.items()))
    return (
        f"📊 对话统计\n"
        f"  总记录: {total} 条\n"
        f"  时间: {first_ts} → {last_ts}\n"
        f"  角色分布:\n{role_info}"
    )


@mcp.tool()
async def clear_context() -> str:
    """
    清空所有对话记录。不可恢复！
    在新话题开始前使用，避免旧上下文干扰。
    """
    try:
        os.remove(CONVERSATION_FILE)
        return "🗑️ 对话记录已清空，可以开始新话题。"
    except FileNotFoundError:
        return "📭 没有可清空的记录。"


# ── Entrypoint ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto Messenger MCP Server (Context-Aware)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port (default: 8000 or $PORT)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--transport",
        default="sse",
        choices=["sse", "streamable-http"],
        help="MCP transport (default: sse)",
    )
    args = parser.parse_args()

    logger.info("Starting '%s' on %s:%d (transport=%s)", SERVER_NAME, args.host, args.port, args.transport)
    logger.info("Webhook: %s", "configured" if WEBHOOK_URL else "NOT configured (local-only)")
    logger.info("Conversation file: %s", CONVERSATION_FILE)

    mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
