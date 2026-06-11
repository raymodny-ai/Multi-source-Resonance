#!/usr/bin/env bash
# =============================================================================
# 多源共振监控系统 - Linux 一键部署脚本
# =============================================================================
# 用法:
#   chmod +x deploy/setup.sh
#   sudo ./deploy/setup.sh                # 交互式安装
#   sudo ./deploy/setup.sh --docker       # Docker 部署
#   sudo ./deploy/setup.sh --baremetal    # 裸机部署
#   sudo ./deploy/setup.sh --uninstall    # 卸载
# =============================================================================

set -euo pipefail

# 颜色输出
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${BLUE}━━━ $* ━━━${NC}"; }

# 默认配置
APP_NAME="multi-resonance"
INSTALL_DIR="/opt/${APP_NAME}"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_USER="appuser"
PYTHON_BIN="python3.12"
DEPLOY_MODE=""

# =============================================================================
# 参数解析
# =============================================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)    DEPLOY_MODE="docker"; shift ;;
        --baremetal) DEPLOY_MODE="baremetal"; shift ;;
        --uninstall) uninstall; exit 0 ;;
        --help|-h)
            echo "用法: $0 [--docker|--baremetal|--uninstall]"
            exit 0 ;;
        *) log_error "未知参数: $1"; exit 1 ;;
    esac
done

# =============================================================================
# 预检
# =============================================================================
preflight() {
    log_step "预检系统环境"

    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 root 权限运行 (sudo ./deploy/setup.sh)"
        exit 1
    fi

    # 检测操作系统
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        log_info "操作系统: ${PRETTY_NAME:-Unknown}"
    fi

    # 检测架构
    log_info "CPU 架构: $(uname -m)"
    log_info "可用内存: $(free -h | awk '/^Mem:/ {print $2}')"
}

# =============================================================================
# 交互式选择部署模式
# =============================================================================
choose_mode() {
    if [[ -n "$DEPLOY_MODE" ]]; then return; fi

    echo ""
    echo "请选择部署模式:"
    echo "  1) Docker 部署 (推荐, 隔离环境, 一键启动)"
    echo "  2) 裸机部署 (直接安装, 需要 Python 3.12 + Node.js 22)"
    echo ""
    read -rp "输入 1 或 2 [默认 1]: " choice
    choice="${choice:-1}"

    case "$choice" in
        1) DEPLOY_MODE="docker" ;;
        2) DEPLOY_MODE="baremetal" ;;
        *) log_error "无效选择"; exit 1 ;;
    esac
}

# =============================================================================
# Docker 部署
# =============================================================================
install_docker() {
    log_step "Docker 部署"

    # 检查 Docker
    if ! command -v docker &>/dev/null; then
        log_warn "Docker 未安装, 正在安装..."
        curl -fsSL https://get.docker.com | bash
        systemctl enable docker
        systemctl start docker
    fi
    log_info "Docker 版本: $(docker --version)"

    # 检查 Docker Compose
    if ! docker compose version &>/dev/null; then
        log_warn "Docker Compose 未安装, 正在安装..."
        apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    fi
    log_info "Docker Compose 版本: $(docker compose version)"

    # 创建 .env (如果不存在)
    if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
        log_info "创建默认 .env 配置文件..."
        cp config/.env.example "${INSTALL_DIR}/.env"
        log_warn "请编辑 ${INSTALL_DIR}/.env 填入真实 API Key"
    fi

    # 构建并启动
    log_info "构建 Docker 镜像..."
    docker compose build --pull

    log_info "启动服务..."
    docker compose up -d app

    # 等待健康检查
    log_info "等待服务就绪..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8524/api/health >/dev/null 2>&1; then
            log_info "服务已就绪 ✓"
            break
        fi
        sleep 2
    done

    log_info "部署完成! 访问 http://localhost:8524"
    log_info "默认账号: admin / admin"
}

# =============================================================================
# 裸机部署
# =============================================================================
install_baremetal() {
    log_step "裸机部署"

    # 安装系统依赖
    log_info "安装系统依赖..."
    apt-get update -qq
    apt-get install -y -qq \
        "${PYTHON_BIN}" "${PYTHON_BIN}-venv" "${PYTHON_BIN}-dev" \
        curl ca-certificates nginx

    # 创建服务用户
    if ! id -u "${SERVICE_USER}" &>/dev/null; then
        useradd --system --create-home --shell /bin/bash "${SERVICE_USER}"
        log_info "创建用户: ${SERVICE_USER}"
    fi

    # 复制应用
    log_info "复制应用到 ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}"
    cp -r "$(dirname "$0")/.."/* "${INSTALL_DIR}/"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

    # 创建虚拟环境
    log_info "创建 Python 虚拟环境..."
    sudo -u "${SERVICE_USER}" "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    sudo -u "${SERVICE_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip
    sudo -u "${SERVICE_USER}" "${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

    # 创建 .env
    if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
        cp "${INSTALL_DIR}/config/.env.example" "${INSTALL_DIR}/.env"
        log_warn "请编辑 ${INSTALL_DIR}/.env 填入真实 API Key"
    fi

    # 创建运行时目录
    mkdir -p "${INSTALL_DIR}/logs" "${INSTALL_DIR}/database" "${INSTALL_DIR}/data"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/logs" "${INSTALL_DIR}/database" "${INSTALL_DIR}/data"

    # 构建前端
    log_info "构建前端..."
    if command -v node &>/dev/null; then
        cd "${INSTALL_DIR}/frontend"
        npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps
        npm run build
        cd "${INSTALL_DIR}"
    else
        log_warn "Node.js 未安装, 跳过前端构建 (需要 Node.js 22+)"
    fi

    # 安装 systemd 服务
    log_info "安装 systemd 服务..."
    cp "${INSTALL_DIR}/deploy/multi-resonance.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "${APP_NAME}"

    # 安装 Nginx 配置
    if [[ -f /etc/nginx/conf.d ]]; then
        cp "${INSTALL_DIR}/deploy/nginx.conf" "/etc/nginx/conf.d/${APP_NAME}.conf"
        sed -i 's|server app:8524;|server 127.0.0.1:8524;|' "/etc/nginx/conf.d/${APP_NAME}.conf"
        nginx -t && systemctl reload nginx
        log_info "Nginx 配置完成"
    fi

    # 启动
    log_info "启动服务..."
    systemctl start "${APP_NAME}"

    sleep 3
    if systemctl is-active --quiet "${APP_NAME}"; then
        log_info "服务已启动 ✓"
    else
        log_error "服务启动失败, 查看日志: journalctl -u ${APP_NAME} -n 50"
    fi

    log_info "部署完成! 访问 http://localhost:8524 (直接) 或 http://localhost (Nginx)"
    log_info "默认账号: admin / admin"
}

# =============================================================================
# 卸载
# =============================================================================
uninstall() {
    log_step "卸载 ${APP_NAME}"

    if systemctl is-active --quiet "${APP_NAME}" 2>/dev/null; then
        systemctl stop "${APP_NAME}"
        systemctl disable "${APP_NAME}"
        rm -f "/etc/systemd/system/${APP_NAME}.service"
        systemctl daemon-reload
        log_info "systemd 服务已移除"
    fi

    if command -v docker &>/dev/null; then
        docker compose down -v 2>/dev/null || true
        log_info "Docker 容器已停止"
    fi

    rm -f /etc/nginx/conf.d/multi-resonance.conf 2>/dev/null || true
    systemctl reload nginx 2>/dev/null || true

    read -rp "删除数据目录 ${INSTALL_DIR}? [y/N]: " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "${INSTALL_DIR}"
        log_info "数据目录已删除"
    fi

    log_info "卸载完成"
}

# =============================================================================
# 主流程
# =============================================================================
main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  多源共振监控系统 - 一键部署脚本            ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    preflight
    choose_mode

    case "$DEPLOY_MODE" in
        docker)    install_docker ;;
        baremetal) install_baremetal ;;
        *)         log_error "未知部署模式"; exit 1 ;;
    esac

    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  部署完成!                                  ║"
    echo "║  Dashboard: http://localhost:8524           ║"
    echo "║  API Docs:  http://localhost:8524/docs      ║"
    echo "║  默认账号:  admin / admin                   ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
}

main "$@"
