#!/bin/bash
# ============================================================
#  Auto Messenger MCP Server — 一键部署脚本
#  部署到 Fly.io（免费），适配 iOS Kelivo App
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Auto Messenger MCP Server - 部署脚本${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# ── Step 1: Check / Install flyctl ──────────────────────
if ! command -v flyctl &>/dev/null; then
    echo -e "${YELLOW}[1/4] 安装 Fly.io CLI...${NC}"
    if command -v brew &>/dev/null; then
        brew install flyctl
    else
        curl -L https://fly.io/install.sh | sh
        # Add to PATH for this session
        export PATH="$HOME/.fly/bin:$PATH"
    fi
    echo -e "${GREEN}  ✅ flyctl 安装完成${NC}"
else
    echo -e "${GREEN}[1/4] ✅ flyctl 已安装${NC}"
fi

# ── Step 2: Login ───────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/4] 登录 Fly.io（会打开浏览器）...${NC}"
flyctl auth login
echo -e "${GREEN}  ✅ 登录成功${NC}"

# ── Step 3: Launch & Deploy ─────────────────────────────
echo ""
echo -e "${YELLOW}[3/4] 创建应用并部署...${NC}"
echo "  提示：选择离你最近的区域（hkg=香港, nrt=东京, sin=新加坡）"
echo "  其他问题全部回车用默认值即可"
echo ""

# Check if fly.toml exists (first time)
if [ ! -f fly.toml ]; then
    flyctl launch --generate-name
fi

flyctl deploy
echo -e "${GREEN}  ✅ 部署完成${NC}"

# ── Step 4: Get URL ─────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/4] 获取服务器地址...${NC}"
APP_NAME=$(flyctl status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['Name'])" 2>/dev/null || echo "auto-messenger")
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  🎉 部署成功！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  SSE 端点地址（填入 Kelivo）："
echo -e "  ${YELLOW}https://${APP_NAME}.fly.dev/sse${NC}"
echo ""
echo -e "  Kelivo 配置："
echo -e "  ┌────────────┬─────────────────────────────────┐"
echo -e "  │ 传输类型   │ SSE                             │"
echo -e "  │ 服务器地址 │ ${YELLOW}https://${APP_NAME}.fly.dev/sse${NC} │"
echo -e "  └────────────┴─────────────────────────────────┘"
echo ""
echo -e "  （可选）配置 Webhook 发到外部平台："
echo -e "  ${YELLOW}flyctl secrets set WEBHOOK_URL=\"https://your-webhook-url\"${NC}"
echo -e "  ${YELLOW}flyctl deploy  # 重新部署使配置生效${NC}"
echo ""
echo -e "  Prometheus 地址（你可以在浏览器打开查看状态）："
echo -e "  https://${APP_NAME}.fly.dev"
echo ""
