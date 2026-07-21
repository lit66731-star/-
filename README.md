# Auto Messenger MCP Server（上下文感知版）

一个可部署到云端的 MCP 服务器，配合 iOS 上的 **Kelivo** App 使用，实现 **AI 自动定时发送消息 — 基于聊天上下文，不乱发**。

## 🧠 核心设计：上下文感知

```
用户发消息 → save_context(role="user")   → 存入对话记录
AI 发消息  → send_message / send_batch  → 自动存为 assistant 记录
                               ↓
⏰ 5分钟后触发 → get_context() → 读取最近对话
                               ↓
              🤖 基于真实上下文生成 2-3 条自然接话
                               ↓
              send_batch() → 发送 + 自动存档
```

**不会乱发的原因**：每次生成前强制读取对话历史，AI 看到的是真实聊天内容，只能接着聊。

## 功能

| 分类 | 工具 | 说明 |
|------|------|------|
| 🧠 上下文 | `save_context` | 保存一条聊天记录（user/assistant/system） |
| 🧠 上下文 | `get_context` | 读取最近 N 条对话，格式化输出 |
| 🧠 上下文 | `get_last_user_message` | 快速获取用户最后一条消息 |
| 📤 发送 | `send_message` | 发送单条消息 + 自动存档 |
| 📤 发送 | `send_batch` | 批量发送 2-3 条 + 自动存档 |
| 🔧 管理 | `get_stats` | 对话统计（总数、角色分布） |
| 🔧 管理 | `clear_context` | 清空记录，开始新话题 |

---

## 🚀 部署到 Fly.io（免费，推荐）

### 前提条件

1. 注册 [Fly.io](https://fly.io) 账号（免费，需绑卡验证，不扣费）
2. 在你的 Mac 上安装 Fly CLI：

```bash
# macOS
brew install flyctl

# 或者
curl -L https://fly.io/install.sh | sh
```

### 部署步骤

```bash
cd mcp-auto-messenger

# 1. 登录 Fly.io（首次会打开浏览器）
fly auth login

# 2. 创建并部署应用（自动检测 fly.toml）
fly launch

# 部署中会问几个问题，全部回车用默认值即可：
#   - Choose a region: 选离你最近的（如 hkg 香港 / nrt 东京 / sin 新加坡）
#   - Would you like to set up a Postgres? → No
#   - Would you like to deploy now? → Yes

# 3. 部署完成后，获取你的服务器地址：
fly status

# 你的 MCP 服务器地址是：
# https://auto-messenger.fly.dev
# SSE 端点：
# https://auto-messenger.fly.dev/sse
```

### （可选）配置 Webhook 发到外部平台

```bash
# 例如发到 Discord:
fly secrets set WEBHOOK_URL="https://discord.com/api/webhooks/xxx/yyy"

# 发到 Slack:
fly secrets set WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"

# 修改后需要重新部署：
fly deploy
```

---

## 📱 在 Kelivo 中配置

1. 打开 Kelivo App
2. 进入 **设置 → MCP 服务器**
3. 添加新服务器：

| 字段 | 值 |
|------|-----|
| **传输类型** | `SSE` |
| **服务器地址** | `https://auto-messenger.fly.dev/sse` |

4. 保存，Kelivo 会自动连接

### ⚠️ 使用前必须先"喂"上下文

MCP 服务器本身不存储 Kelivo 的聊天记录。你需要让 AI 在**每次对话时**调用 `save_context` 保存聊天内容，这样定时触发时 `get_context` 才能读到历史。

**在 Kelivo 的系统提示词（System Prompt）中加入：**

```
每次用户说话后，调用 save_context(role="user", content="用户的原话")。
每次你回复后，调用 save_context(role="assistant", content="你的回复")。
这样我才能记住对话上下文。
```

---

## ⏰ 设置 5 分钟定时发送

### Kelivo 定时 Prompt（关键！）

在 Kelivo 的定时任务中，设置每 5 分钟执行以下 prompt：

```
⚠️ 重要：你必须严格按以下步骤操作，不要跳过任何步骤。

步骤 1：调用 get_context(limit=20) 读取最近的对话记录。

步骤 2：基于以上对话上下文，生成 2-3 条自然的回复消息。
要求：
- 必须承接上一句对话内容，像正常人聊天一样
- 不要突然换话题，不要发无关内容
- 如果用户在问问题，就回答；如果在闲聊，就接着聊
- 不要重复之前说过的话
- 如果对话中断了（最后一条是你发的），就根据话题自然延伸

步骤 3：调用 send_batch(messages=[...]) 发送你生成的 2-3 条消息。

步骤 4：调用 save_context 保存你发的每条消息（role="assistant"）。
```

### 备用：Claude Code /loop

```bash
claude "/loop 5m 先调用 get_context 了解对话，然后基于上下文生成2-3条自然接话，用 send_batch 发送。"
```

---

## 🧱 国内网络问题

如果 `deploy.sh` 下载 flyctl 失败（`Operation timed out`），说明 GitHub 被墙。

### 快速解决（任选一个）：

**方案 1：开代理**
```bash
# 假设你的代理在 127.0.0.1:7890（Clash/V2Ray）
export https_proxy=http://127.0.0.1:7890
./deploy.sh
```

**方案 2：手动下载 flyctl**
1. 浏览器打开镜像站：`https://ghproxy.com/https://github.com/superfly/flyctl/releases/tag/v0.4.72`
2. 下载 `flyctl_0.4.72_macOS_x86_64.tar.gz`
3. 解压，把 `flyctl` 放到 `~/.fly/bin/` 下
4. `chmod +x ~/.fly/bin/flyctl`
5. `export PATH="$HOME/.fly/bin:$PATH"`
6. 重新运行 `./deploy.sh`（会跳过安装步骤）

**方案 3：备选部署平台**

如果 Fly.io 完全用不了，用 **Render.com**（浏览器操作，不需要 CLI）：

1. 先把代码推到一个你能访问的 Git 仓库（Gitee / 自建 GitLab / 代理推 GitHub）
2. 打开 [render.com](https://render.com)，注册账号
3. 点击 **New + → Web Service**
4. 连接你的 Git 仓库
5. 配置：
   - **Runtime**: Docker
   - **Region**: Singapore
6. 部署后你会得到一个 `https://xxx.onrender.com` 地址
7. Kelivo 中填：`https://xxx.onrender.com/sse`

> ⚠️ Render 免费版 15 分钟无请求会休眠，首次请求需 ~30s 唤醒。
> Fly.io 免费版不会休眠，推荐优先用 Fly.io。

---

## 🔧 本地测试

```bash
cd mcp-auto-messenger

# 安装依赖（国内用清华源加速）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动服务器
python server.py --port 8000

# 服务器运行在 http://localhost:8000
# SSE 端点: http://localhost:8000/sse
```

---

## 📊 免费额度

| 平台 | 免费额度 |
|------|----------|
| **Fly.io** | 3 个共享 VM + 30GB 带宽/月，**不休眠** ✅ |
| Render | 750h/月，15分钟无请求会休眠 ⚠️ |

**月费：$0** 🎉
