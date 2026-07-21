#!/bin/bash
# ============================================================
#  Auto Messenger MCP Server — 一键部署脚本（国内优化版）
#  自动尝试多个下载源，适配国内网络环境
# ============================================================
set +e  # Don't exit on error — we handle errors ourselves

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

FLY_VERSION="v0.4.72"
FLY_FILENAME="flyctl_0.4.72_macOS_x86_64.tar.gz"
FLY_INSTALL_DIR="$HOME/.fly"
FLY_BIN="$FLY_INSTALL_DIR/bin/flyctl"

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Auto Messenger MCP Server - 部署脚本${NC}"
echo -e "${GREEN}  (国内网络优化版)${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# ═══════════════════════════════════════════════════════════
# Step 1: Install flyctl (try multiple sources)
# ═══════════════════════════════════════════════════════════

if command -v flyctl &>/dev/null; then
    echo -e "${GREEN}[1/4] ✅ flyctl 已安装 ($(flyctl version 2>&1 | head -1))${NC}"
elif [ -f "$FLY_BIN" ]; then
    echo -e "${GREEN}[1/4] ✅ 找到已下载的 flyctl${NC}"
    export PATH="$FLY_INSTALL_DIR/bin:$PATH"
else
    echo -e "${YELLOW}[1/4] 安装 Fly.io CLI...${NC}"
    echo ""

    # ── Method 0: Homebrew (if available) ──
    if command -v brew &>/dev/null; then
        echo -e "${BLUE}  尝试: Homebrew...${NC}"
        if brew install flyctl 2>/dev/null; then
            echo -e "${GREEN}  ✅ Homebrew 安装成功${NC}"
        fi
    fi

    # ── Method 1: Official install script (via possible proxy) ──
    if ! command -v flyctl &>/dev/null; then
        echo -e "${BLUE}  尝试: 官方脚本...${NC}"
        curl -L --connect-timeout 10 --max-time 60 \
            https://fly.io/install.sh 2>/dev/null | sh 2>/dev/null
        export PATH="$HOME/.fly/bin:$PATH"
    fi

    # ── Method 2: GitHub proxy mirrors (for users in China) ──
    if ! command -v flyctl &>/dev/null && [ ! -f "$FLY_BIN" ]; then
        MIRRORS=(
            "https://ghproxy.com/https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}"
            "https://mirror.ghproxy.com/https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}"
            "https://gh.ddlc.top/https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}"
            "https://github.moeyy.xyz/https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}"
            "https://gh.con.sh/https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}"
        )

        for mirror in "${MIRRORS[@]}"; do
            echo -e "${BLUE}  尝试镜像: ${mirror:0:50}...${NC}"
            if curl -L --connect-timeout 10 --max-time 120 \
                -o /tmp/flyctl.tar.gz "$mirror" 2>/dev/null; then
                if file /tmp/flyctl.tar.gz 2>/dev/null | grep -q "gzip"; then
                    echo -e "${GREEN}  ✅ 下载成功，解压中...${NC}"
                    mkdir -p "$FLY_INSTALL_DIR/bin"
                    tar -xzf /tmp/flyctl.tar.gz -C "$FLY_INSTALL_DIR/bin/" 2>/dev/null
                    chmod +x "$FLY_INSTALL_DIR/bin/flyctl" 2>/dev/null
                    rm -f /tmp/flyctl.tar.gz
                    export PATH="$FLY_INSTALL_DIR/bin:$PATH"
                    break
                else
                    rm -f /tmp/flyctl.tar.gz
                fi
            fi
        done
    fi

    # ── Method 3: Direct GitHub (last resort, may need VPN) ──
    if ! command -v flyctl &>/dev/null && [ ! -f "$FLY_BIN" ]; then
        echo -e "${BLUE}  尝试: GitHub 直连...${NC}"
        curl -L --connect-timeout 10 --max-time 120 \
            -o /tmp/flyctl.tar.gz \
            "https://github.com/superfly/flyctl/releases/download/${FLY_VERSION}/${FLY_FILENAME}" 2>/dev/null
        if [ -f /tmp/flyctl.tar.gz ] && file /tmp/flyctl.tar.gz 2>/dev/null | grep -q "gzip"; then
            mkdir -p "$FLY_INSTALL_DIR/bin"
            tar -xzf /tmp/flyctl.tar.gz -C "$FLY_INSTALL_DIR/bin/" 2>/dev/null
            chmod +x "$FLY_INSTALL_DIR/bin/flyctl" 2>/dev/null
            rm -f /tmp/flyctl.tar.gz
            export PATH="$FLY_INSTALL_DIR/bin:$PATH"
        fi
    fi

    # ── Check result ──
    if command -v flyctl &>/dev/null || [ -f "$FLY_BIN" ]; then
        export PATH="$FLY_INSTALL_DIR/bin:$PATH"
        echo -e "${GREEN}  ✅ flyctl 安装完成${NC}"
    else
        echo ""
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${RED}  ❌ flyctl 安装失败（网络问题）${NC}"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo -e "  请尝试以下任一方法后重新运行本脚本："
        echo ""
        echo -e "  ${YELLOW}方法A: 开启 VPN/代理后重试${NC}"
        echo -e "    export https_proxy=http://127.0.0.1:7890"
        echo -e "    ./deploy.sh"
        echo ""
        echo -e "  ${YELLOW}方法B: 手动下载 flyctl${NC}"
        echo -e "    浏览器打开: https://ghproxy.com/https://github.com/superfly/flyctl/releases/tag/${FLY_VERSION}"
        echo -e "    下载 macOS 版本，解压后放到: ${FLY_INSTALL_DIR}/bin/"
        echo -e "    chmod +x ${FLY_INSTALL_DIR}/bin/flyctl"
        echo -e "    export PATH=\"${FLY_INSTALL_DIR}/bin:\$PATH\""
        echo -e "    ./deploy.sh"
        echo ""
        echo -e "  ${YELLOW}方法C: 使用替代部署方案${NC}"
        echo -e "    见 README.md 的「备选部署方案」章节"
        echo ""
        exit 1
    fi
fi

# ═══════════════════════════════════════════════════════════
# Step 2: Login to Fly.io
# ═══════════════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[2/4] 登录 Fly.io（会打开浏览器）...${NC}"
echo -e "  如果浏览器打不开，手动访问: ${BLUE}https://fly.io/auth${NC}"
flyctl auth login
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 登录失败${NC}"
    exit 1
fi
echo -e "${GREEN}  ✅ 登录成功${NC}"

# ═══════════════════════════════════════════════════════════
# Step 3: Launch & Deploy
# ═══════════════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[3/4] 创建应用并部署...${NC}"
echo -e "  📍 区域建议: ${BLUE}hkg${NC} (香港) / ${BLUE}nrt${NC} (东京) / ${BLUE}sin${NC} (新加坡)"
echo -e "  ❓ 其他问题全部回车用默认值"
echo ""

# Create fly.toml if it doesn't exist
if [ ! -f fly.toml ]; then
    flyctl launch --generate-name --region hkg
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ 创建应用失败${NC}"
        exit 1
    fi
fi

# Deploy
flyctl deploy
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 部署失败，请检查网络后重试${NC}"
    exit 1
fi
echo -e "${GREEN}  ✅ 部署完成${NC}"

# ═══════════════════════════════════════════════════════════
# Step 4: Show connection info
# ═══════════════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[4/4] 获取服务器地址...${NC}"

# Get app name from fly.toml
APP_NAME=$(grep '^app' fly.toml 2>/dev/null | sed 's/.*= *"\(.*\)"/\1/' | head -1)
if [ -z "$APP_NAME" ]; then
    APP_NAME=$(flyctl status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['Name'])" 2>/dev/null)
fi
if [ -z "$APP_NAME" ]; then
    APP_NAME="YOUR_APP_NAME"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  🎉 部署成功！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  📱 ${YELLOW}Kelivo 配置（填到你 iPhone 上）：${NC}"
echo ""
echo -e "  ┌────────────────┬──────────────────────────────────────┐"
echo -e "  │ 传输类型       │ ${GREEN}SSE${NC}                                │"
echo -e "  │ 服务器地址     │ ${GREEN}https://${APP_NAME}.fly.dev/sse${NC}       │"
echo -e "  └────────────────┴──────────────────────────────────────┘"
echo ""
echo -e "  🔗 服务器状态页: ${BLUE}https://${APP_NAME}.fly.dev${NC}"
echo ""
echo -e "  ${YELLOW}── 后续操作 ──${NC}"
echo ""
echo -e "  1. 在 Kelivo 的 System Prompt 中加入："
echo -e "     ${BLUE}每次对话后调用 save_context 保存聊天记录。${NC}"
echo -e "     ${BLUE}定时生成消息前先调用 get_context 了解上下文。${NC}"
echo ""
echo -e "  2. Kelivo 定时 prompt（每5分钟）："
echo -e "     ${BLUE}先调用 get_context(limit=20)，基于上下文生成2-3条自然接话，${NC}"
echo -e "     ${BLUE}用 send_batch 发送，确保不脱离对话主题。${NC}"
echo ""
echo -e "  ${YELLOW}── 可选：配置 Webhook ──${NC}"
echo -e "  flyctl secrets set WEBHOOK_URL=\"https://your-discord-webhook\""
echo -e "  flyctl deploy"
echo ""
