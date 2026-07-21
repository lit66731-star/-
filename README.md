# Auto Messenger MCP Server

一个可部署到云端的 MCP 服务器，配合 iOS 上的 **Kelivo** App 使用，实现 **AI 自动定时发送消息**。

## 功能

| 工具 | 说明 |
|------|------|
| `send_message` | 发送单条消息 |
| `send_batch` | 批量发送 2-3 条消息（核心功能） |
| `get_history` | 查看历史消息记录 |
| `clear_history` | 清空历史记录 |

## 工作流程

```
⏰ 每 5 分钟 → Kelivo 触发 Claude → 
🤖 Claude 生成 2-3 条消息内容 → 
📡 调用 MCP send_batch → 
📤 消息发送/显示
```

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

---

## ⏰ 设置 5 分钟定时发送

### 方法一：Kelivo 内置定时（如果有）

Kelivo 如有定时任务功能，设置每 5 分钟发送 prompt：

```
请生成 2-3 条有趣的消息并调用 send_batch 发送。
消息要求：
- 每条消息不同主题，避免重复
- 可以是新闻摘要、冷知识、名言、笑话等
- 查看 get_history 避免发送重复内容
```

### 方法二：Claude Code /loop（如果你在用 Claude Code）

```bash
claude "/loop 5m 请生成2-3条消息，调用 send_batch 发送。先调用 get_history 查看历史避免重复。"
```

### 方法三：外部 Cron 服务（免费）

用 [cron-job.org](https://cron-job.org)（免费）定时 ping 你的服务器，触发 Kelivo 动作。

---

## 🔧 本地测试

```bash
cd mcp-auto-messenger

# 安装依赖
pip install -r requirements.txt

# 启动服务器
python server.py --port 8000

# 服务器运行在 http://localhost:8000
# SSE 端点: http://localhost:8000/sse
```

---

## 📊 免费额度

| 项目 | 限额 |
|------|------|
| Fly.io | 3 个共享 VM（256MB RAM 每个），够用 |
| 带宽 | 免费 30GB/月 |
| Cron-job.org | 免费，每分钟可触发一次 |

**月费：$0** 🎉
