#!/usr/bin/env bash
set -euo pipefail

# 724code 一键安装脚本
# curl -fsSL https://raw.githubusercontent.com/dapingzui/724code/main/install.sh | bash

REPO="https://github.com/dapingzui/724code.git"
INSTALL_DIR="${724CODE_DIR:-$HOME/724code}"
SERVICE_NAME="724code"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "  724code 安装脚本"
echo "  Control Claude Code from Telegram"
echo ""

# ========== 检查必备工具 ==========

check_command() {
    if command -v "$1" &>/dev/null; then
        info "$1 已安装: $(command -v "$1")"
        return 0
    else
        return 1
    fi
}

# Python
if check_command python3; then
    PYTHON=python3
elif check_command python; then
    PYTHON=python
else
    error "Python 3 未安装。请先安装: https://www.python.org/downloads/"
fi

# 检查 Python 版本 >= 3.11
PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python >= 3.11 required, found $PY_VERSION"
fi
info "Python $PY_VERSION"

# Git
check_command git || error "Git 未安装。请先安装: https://git-scm.com/downloads"

# Claude Code
if check_command claude; then
    :
else
    warn "Claude Code CLI 未安装"
    warn "安装: npm install -g @anthropic-ai/claude-code"
    warn "安装后需要运行 claude 登录"
    echo ""
    read -p "是否继续安装 724code？(y/N) " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 0
fi

# GitHub CLI (可选)
if check_command gh; then
    # 检查是否已登录
    if gh auth status &>/dev/null 2>&1; then
        info "gh 已登录"
    else
        warn "gh 已安装但未登录（/clone, /repos, /newproject GitHub 功能需要登录）"
        warn "登录: gh auth login"
    fi
else
    warn "GitHub CLI 未安装（可选，/clone /repos /newproject 需要）"
    warn "安装: https://cli.github.com/"
fi

# ========== 克隆/更新仓库 ==========

echo ""
if [ -d "$INSTALL_DIR/.git" ]; then
    info "已存在 $INSTALL_DIR，更新中..."
    cd "$INSTALL_DIR"
    git pull --ff-only || warn "git pull 失败，使用现有版本"
else
    info "克隆到 $INSTALL_DIR..."
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ========== 安装 Python 依赖 ==========

info "安装 Python 依赖..."
$PYTHON -m pip install -r requirements.txt --quiet 2>/dev/null || \
    $PYTHON -m pip install -r requirements.txt

# ========== 配置文件 ==========

if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    warn "已创建 config.yaml，请编辑填入你的配置:"
    echo ""
    echo "  必填项:"
    echo "    1. Telegram Bot Token （从 @BotFather 获取）"
    echo "    2. 你的 Telegram User ID （从 @userinfobot 获取）"
    echo "    3. workspace_root （项目存放根目录）"
    echo ""
    echo "  可选项:"
    echo "    4. proxy.url （如果需要代理访问 Telegram/Claude API）"
    echo "    5. git.user_name / git.user_email"
    echo ""
    echo "  编辑配置: nano $INSTALL_DIR/config.yaml"
    echo ""
else
    info "config.yaml 已存在，保留现有配置"
fi

# ========== systemd 服务 ==========

if command -v systemctl &>/dev/null; then
    echo ""
    read -p "是否安装 systemd 服务（开机自启）？(y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

        sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=724code - Telegram Claude Code Controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON $INSTALL_DIR/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        info "systemd 服务已安装"

        if [ -f "$INSTALL_DIR/config.yaml" ]; then
            # 检查是否还是默认 token
            if grep -q "YOUR_TELEGRAM_BOT_TOKEN" "$INSTALL_DIR/config.yaml" 2>/dev/null; then
                warn "请先编辑 config.yaml 填入实际配置，然后运行:"
                echo "  sudo systemctl enable --now $SERVICE_NAME"
            else
                sudo systemctl enable --now "$SERVICE_NAME"
                info "服务已启动"
                echo ""
                echo "  查看日志: sudo journalctl -u $SERVICE_NAME -f"
                echo "  停止服务: sudo systemctl stop $SERVICE_NAME"
                echo "  重启服务: sudo systemctl restart $SERVICE_NAME"
            fi
        fi
    fi
fi

# ========== 完成 ==========

echo ""
echo "========================================"
info "724code 安装完成!"
echo ""
echo "  目录: $INSTALL_DIR"
echo "  配置: $INSTALL_DIR/config.yaml"
echo ""
echo "  手动启动: cd $INSTALL_DIR && $PYTHON main.py"
echo "  编辑配置: nano $INSTALL_DIR/config.yaml"
echo ""
echo "  文档: https://github.com/dapingzui/724code"
echo "========================================"
