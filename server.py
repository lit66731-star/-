"""
Auto Messenger MCP Server (Context-Aware + Auto Trigger)
========================================================
Features:
  - MCP tools: save_context, get_context, send_batch, etc.
  - HTTP POST /trigger — call DeepSeek to generate 2-3 context-aware
    messages every 5 minutes via cron-job.org
  - get_pending / mark_sent — retrieve & confirm auto-generated messages

Deploy: Render.com (free) or Fly.io
Trigger: cron-job.org → POST /trigger every 5 min
"""

import os
import json
import logging
import argparse
import threading
import hashlib
import hmac
from datetime import datetime, timezone

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from fastmcp import FastMCP

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto-messenger")

# ── Config ───────────────────────────────────────────────────────────
WEBHOOK_URL       = os.environ.get("WEBHOOK_URL", "")
CONVERSATION_FILE = os.environ.get("CONVERSATION_FILE", "/tmp/auto-conversation.jsonl")
SERVER_NAME       = os.environ.get("SERVER_NAME", "Auto Messenger")
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL    = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TRIGGER_SECRET    = os.environ.get("TRIGGER_SECRET", "")
PENDING_FILE      = os.environ.get("PENDING_FILE", "/tmp/auto-pending.jsonl")

_file_lock = threading.Lock()

# ── FastMCP App ──────────────────────────────────────────────────────
mcp = FastMCP(SERVER_NAME)

# ── File I/O ─────────────────────────────────────────────────────────

def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

def _append_entry(entry: dict) -> dict:
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _file_lock:
        _ensure_dir(CONVERSATION_FILE)
        with open(CONVERSATION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

def _read_entries(limit: int = 50) -> list[dict]:
    try:
        with _file_lock:
            with open(CONVERSATION_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
    except FileNotFoundError:
        return []
    entries = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line: continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries

def _read_pending() -> list[dict]:
    """Read all pending (unsent) auto-generated messages."""
    try:
        with _file_lock:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
    except FileNotFoundError:
        return []
    entries = []
    for line in lines:
        line = line.strip()
        if not line: continue
        try:
            e = json.loads(line)
            if e.get("status") == "pending":
                entries.append(e)
        except json.JSONDecodeError:
            continue
    return entries

def _write_pending(messages: list[dict]) -> None:
    """Overwrite pending file with new messages."""
    with _file_lock:
        _ensure_dir(PENDING_FILE)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

def _append_pending(msg: dict) -> None:
    msg["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _file_lock:
        _ensure_dir(PENDING_FILE)
        with open(PENDING_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

def _mark_all_sent() -> int:
    """Mark all pending messages as sent. Returns count."""
    entries = _read_pending()
    count = len(entries)
    for e in entries:
        e["status"] = "sent"
        # Also save to conversation
        _append_entry({"role": "assistant", "content": e["content"], "source": "auto"})
    # Clear pending file
    with _file_lock:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            pass
    return count

# ── Helpers ──────────────────────────────────────────────────────────

async def post_to_webhook(content: str) -> dict:
    payload = {"content": content, "timestamp": datetime.now(timezone.utc).isoformat(), "source": "auto-messenger-mcp"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(WEBHOOK_URL, json=payload)
        resp.raise_for_status()
        return {"status_code": resp.status_code, "response": resp.text[:200]}

def _format_entries(entries: list[dict], max_len: int = 300) -> str:
    if not entries: return "（暂无聊天记录）"
    lines = []
    for e in entries:
        ts = e.get("timestamp", "?")[:19]
        role = e.get("role", "?")
        content = e.get("content", "")
        if len(content) > max_len: content = content[:max_len] + "..."
        icon = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role, "📝")
        lines.append(f"[{ts}] {icon} {role}: {content}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  DeepSeek AI — generate context-aware messages
# ═══════════════════════════════════════════════════════════════════════

DEEPSEEK_SYSTEM_PROMPT = """你是一个正在参与群聊的AI助手。你需要基于聊天上下文，生成2-3条自然的接话。

要求：
1. 必须承接最近的对话内容，像真人一样自然聊天
2. 不要突然切换话题，不要发无关内容
3. 如果用户在问问题，就回答；如果在闲聊，就接着聊
4. 每条消息不要太长（50字以内），像手机聊天一样随意
5. 2-3条消息之间要有逻辑关联，像连续说话
6. 不要重复之前说过的话
7. 不要用"大家好""我来接话了"这类开场白

请直接返回JSON数组格式，不要加任何解释：
["消息1", "消息2", "消息3"]"""


async def call_deepseek(context_text: str) -> list[str]:
    """Call DeepSeek API to generate 2-3 messages based on context."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DeepSeek API key not set — using fallback messages")
        return _fallback_messages()

    user_prompt = f"以下是最近的聊天记录：\n\n{context_text}\n\n请基于以上对话，生成2-3条自然的接话。"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 600,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"].strip()

            # Parse JSON array from response
            messages = _parse_deepseek_response(raw)
            logger.info("DeepSeek generated %d messages", len(messages))
            return messages

    except Exception as exc:
        logger.error("DeepSeek API call failed: %s", exc)
        return _fallback_messages()


def _parse_deepseek_response(raw: str) -> list[str]:
    """Try to parse JSON array from DeepSeek response. Robust against markdown wrapping."""
    # Try direct JSON parse
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return [str(m) for m in result[:3]]
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    import re
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(m) for m in result[:3]]
        except json.JSONDecodeError:
            pass

    # Fallback: split by newlines and clean up
    lines = [l.strip().lstrip('123456789.-) "') for l in raw.split('\n') if l.strip()]
    lines = [l for l in lines if l and len(l) > 2]
    return lines[:3] if lines else _fallback_messages()


def _fallback_messages() -> list[str]:
    """Fallback messages when DeepSeek is unavailable."""
    return [
        "大家还在吗？👋",
        "上面的话题还挺有意思的~",
    ]


# ═══════════════════════════════════════════════════════════════════════
#  HTTP Trigger Endpoint (called by cron-job.org)
# ═══════════════════════════════════════════════════════════════════════

async def trigger_endpoint(request: Request) -> JSONResponse:
    """
    POST /trigger
    Called by cron-job.org every 5 minutes.
    Reads conversation context → calls DeepSeek → stores pending messages.
    """
    # Optional: verify secret to prevent abuse
    if TRIGGER_SECRET:
        body = await request.body()
        sig = request.headers.get("X-Trigger-Secret", "")
        expected = hmac.new(TRIGGER_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    # 1. Read recent context
    entries = _read_entries(limit=30)
    if not entries:
        logger.info("Trigger: no context yet, skipping generation")
        return JSONResponse({"status": "skipped", "reason": "no context"}, status_code=200)

    context_text = _format_entries(entries)

    # 2. Call DeepSeek to generate messages
    messages = await call_deepseek(context_text)

    if not messages:
        return JSONResponse({"status": "skipped", "reason": "generation failed"}, status_code=200)

    # 3. Store as pending (also send via webhook if configured)
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for i, msg in enumerate(messages):
        _append_pending({
            "batch_id": batch_id,
            "index": i,
            "content": msg,
            "status": "pending",
        })

    # 4. Optionally send to webhook immediately
    webhook_results = []
    if WEBHOOK_URL:
        for msg in messages:
            try:
                await post_to_webhook(msg)
                webhook_results.append("ok")
            except Exception as exc:
                webhook_results.append(f"failed: {exc}")

    logger.info("Trigger: generated %d messages (batch=%s)", len(messages), batch_id)

    return JSONResponse({
        "status": "ok",
        "batch_id": batch_id,
        "count": len(messages),
        "messages": messages,
        "webhook": webhook_results if webhook_results else "not configured",
    }, status_code=200)


# ═══════════════════════════════════════════════════════════════════════
#  MCP Tools
# ═══════════════════════════════════════════════════════════════════════

# ── Context Tools ────────────────────────────────────────────────────

@mcp.tool()
async def save_context(role: str, content: str) -> str:
    """保存聊天记录。role: user/assistant/system"""
    if role not in ("user", "assistant", "system"):
        return f"⚠️ 无效角色 '{role}'，请用 user / assistant / system"
    entry = _append_entry({"role": role, "content": content})
    ts = entry["timestamp"][:19]
    return f"✅ 已保存 [{ts}] {role}: {content[:80]}{'...' if len(content)>80 else ''}"


@mcp.tool()
async def get_context(limit: int = 30) -> str:
    """读取最近对话上下文。limit 默认30，最大100。"""
    limit = min(max(limit, 1), 100)
    entries = _read_entries(limit)
    if not entries:
        return "📭 还没有任何聊天记录。请先通过 save_context 保存对话。"
    body = _format_entries(entries)
    return f"📋 最近 {len(entries)} 条对话：\n{'─'*50}\n{body}\n{'─'*50}\n⚠️ 请基于以上上下文生成回复。"


@mcp.tool()
async def get_last_user_message() -> str:
    """获取用户最后一条消息。"""
    entries = _read_entries(100)
    for e in reversed(entries):
        if e.get("role") == "user":
            return f"[{e.get('timestamp','?')[:19]}] 用户最后说：{e['content']}"
    return "📭 还没有用户消息。"


# ── Pending Queue Tools ──────────────────────────────────────────────

@mcp.tool()
async def get_pending() -> str:
    """
    获取待发送的自动生成消息。
    定时任务生成的对话会先存在这里，你需要在对话开始时检查并发送。
    """
    entries = _read_pending()
    if not entries:
        return "📭 没有待发送的消息。"

    # Group by batch
    batches = {}
    for e in entries:
        bid = e.get("batch_id", "unknown")
        if bid not in batches:
            batches[bid] = []
        batches[bid].append(e)

    output = []
    for bid, msgs in sorted(batches.items()):
        output.append(f"\n📦 批次 {bid} ({len(msgs)}条):")
        for m in msgs:
            output.append(f"  [{m.get('index',0)}] {m['content']}")

    output.append(f"\n共 {len(entries)} 条待发送。请调用 send_pending 发送它们。")
    return "\n".join(output)


@mcp.tool()
async def send_pending() -> str:
    """
    发送所有待发送消息。调用后：
    1. 消息会自动存档到对话记录
    2. 如果配置了 WEBHOOK_URL 也会发送
    3. 清空待发送队列
    """
    entries = _read_pending()
    if not entries:
        return "📭 没有待发送的消息。"

    count = len(entries)
    results = []

    for e in entries:
        content = e["content"]
        # Send via webhook if configured
        if WEBHOOK_URL:
            try:
                await post_to_webhook(content)
                results.append(f"  ✅ {content[:60]}...")
            except Exception as exc:
                results.append(f"  ❌ webhook失败: {exc}")
        else:
            results.append(f"  📤 {content}")

    # Mark all as sent + save to conversation
    _mark_all_sent()

    summary = f"📬 已发送 {count} 条消息:\n" + "\n".join(results)
    return summary


@mcp.tool()
async def generate_now() -> str:
    """
    立即触发一次消息生成（和定时触发一样）。
    读取对话上下文 → 调 DeepSeek → 存到待发队列。
    返回生成的消息内容。
    """
    entries = _read_entries(limit=30)
    if not entries:
        return "⚠️ 没有对话上下文，无法生成。请先聊几句。"

    context_text = _format_entries(entries)
    messages = await call_deepseek(context_text)

    if not messages:
        return "❌ 消息生成失败，请稍后重试。"

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for i, msg in enumerate(messages):
        _append_pending({"batch_id": batch_id, "index": i, "content": msg, "status": "pending"})

    output = [f"🎲 已生成 {len(messages)} 条消息（批次 {batch_id}）："]
    for i, m in enumerate(messages, 1):
        output.append(f"  {i}. {m}")
    output.append("\n请调用 send_pending 发送它们。")
    return "\n".join(output)


# ── Message Tools ────────────────────────────────────────────────────

@mcp.tool()
async def send_message(content: str) -> str:
    """发送单条消息并自动存档。"""
    _append_entry({"role": "assistant", "content": content})
    if WEBHOOK_URL:
        try:
            r = await post_to_webhook(content)
            return f"✅ 已发送到 webhook (HTTP {r['status_code']})\n   {content}"
        except Exception as exc:
            return f"❌ Webhook 失败: {exc}"
    return f"📤 已发送:\n{content}"


@mcp.tool()
async def send_batch(messages: list[str]) -> str:
    """批量发送2-3条消息。调用前先 get_context 了解上下文！"""
    if not messages:
        return "⚠️ 没有要发送的消息。"
    results = []
    for i, msg in enumerate(messages, 1):
        _append_entry({"role": "assistant", "content": msg})
        if WEBHOOK_URL:
            try:
                await post_to_webhook(msg)
                results.append(f"  {i}. ✅ {msg[:60]}...")
            except Exception as exc:
                results.append(f"  {i}. ❌ {exc}")
        else:
            results.append(f"  {i}. 📤 {msg}")
    return f"📬 已发送 {len(messages)} 条:\n" + "\n".join(results)


# ── Housekeeping ─────────────────────────────────────────────────────

@mcp.tool()
async def get_stats() -> str:
    """对话统计。"""
    entries = _read_entries(1000)
    if not entries: return "📭 还没有任何记录。"
    roles = {}
    for e in entries:
        roles[e.get("role", "?")] = roles.get(e.get("role", "?"), 0) + 1
    first_ts = entries[0].get("timestamp", "?")[:19]
    last_ts = entries[-1].get("timestamp", "?")[:19]
    role_info = "\n".join(f"  {r}: {c} 条" for r, c in sorted(roles.items()))
    pending_count = len(_read_pending())
    return f"📊 统计\n  总记录: {len(entries)} 条\n  时间: {first_ts} → {last_ts}\n  角色:\n{role_info}\n  待发送: {pending_count} 条"


@mcp.tool()
async def clear_context() -> str:
    """清空所有对话记录。不可恢复！"""
    try:
        os.remove(CONVERSATION_FILE)
        return "🗑️ 对话记录已清空。"
    except FileNotFoundError:
        return "📭 没有可清空的记录。"


# ═══════════════════════════════════════════════════════════════════════
#  App Assembly & Entrypoint
# ═══════════════════════════════════════════════════════════════════════

def build_app() -> Starlette:
    """
    Build a combined Starlette app with:
      - /sse          → FastMCP SSE handler
      - /messages/    → FastMCP messages handler
      - /trigger      → custom trigger endpoint (POST)
    """
    # Get FastMCP's internal ASGI app
    # FastMCP 2.x creates the app during run(). We peek at _create_app.
    # Actually, let's access the app through the FastMCP instance.
    try:
        # FastMCP 2.x/3.x: mcp.app or mcp._app
        mcp_app = getattr(mcp, 'app', None) or getattr(mcp, '_app', None)
        if mcp_app is None:
            # Force app creation by accessing the property
            if hasattr(mcp, 'sse_app'):
                mcp_app = mcp.sse_app()
            elif hasattr(mcp, 'build_app'):
                mcp_app = mcp.build_app()
            else:
                # Last resort: create it ourselves
                mcp_app = mcp._create_app()
    except Exception:
        mcp_app = mcp._create_app()

    # Our custom trigger route
    trigger_route = Route("/trigger", trigger_endpoint, methods=["POST"])

    # Create combined routes: custom first, then MCP handles the rest
    from starlette.routing import Mount
    routes = [
        trigger_route,
        Mount("/", app=mcp_app),
    ]

    return Starlette(routes=routes)


def main():
    parser = argparse.ArgumentParser(description="Auto Messenger MCP Server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    logger.info("Starting '%s' on %s:%d", SERVER_NAME, args.host, args.port)
    logger.info("Webhook: %s", "configured" if WEBHOOK_URL else "NOT configured")
    logger.info("DeepSeek: %s", "configured" if DEEPSEEK_API_KEY else "NOT configured")
    logger.info("Trigger secret: %s", "configured" if TRIGGER_SECRET else "NOT configured (anyone can trigger)")

    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
