# =============================================================================
# 多源共振监控系统 - Windows 一键部署脚本
# =============================================================================
# 用法:
#   .\deploy\setup.ps1                  # 交互式安装
#   .\deploy\setup.ps1 -Docker          # Docker 部署
#   .\deploy\setup.ps1 -BareMetal       # 裸机部署
#   .\deploy\setup.ps1 -Uninstall       # 卸载
#
# 前置条件 (裸机部署):
#   - Python 3.12+ (https://python.org)
#   - Node.js 22+   (https://nodejs.org)
#   - Git           (https://git-scm.com)
# =============================================================================

param(
    [switch]$Docker,
    [switch]$BareMetal,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$APP_NAME = "multi-resonance"
$INSTALL_DIR = Join-Path $env:ProgramFiles $APP_NAME
$VENV_DIR = Join-Path $INSTALL_DIR "venv"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_DIR = Split-Path -Parent $SCRIPT_DIR

# 颜色函数
function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }
function Write-Step  { Write-Host ""; Write-Host "━━━ $args ━━━" -ForegroundColor Cyan }

# =============================================================================
# 预检
# =============================================================================
function Preflight {
    Write-Step "预检系统环境"

    $os = Get-CimInstance Win32_OperatingSystem
    Write-Info "操作系统: $($os.Caption)"
    Write-Info "总内存: $([math]::Round($os.TotalVisibleMemorySize/1MB, 1)) GB"

    # 检查管理员权限
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Warn "建议以管理员身份运行以获得最佳体验"
    }
}

# =============================================================================
# 选择部署模式
# =============================================================================
function Choose-Mode {
    if ($Docker -or $BareMetal) { return }

    Write-Host ""
    Write-Host "请选择部署模式:"
    Write-Host "  1) Docker 部署 (推荐, 隔离环境, 一键启动)"
    Write-Host "  2) 裸机部署 (直接安装, 需要 Python 3.12 + Node.js 22)"
    Write-Host ""
    $choice = Read-Host "输入 1 或 2 [默认 1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" { $script:Docker = $true }
        "2" { $script:BareMetal = $true }
        default { Write-Error "无效选择"; exit 1 }
    }
}

# =============================================================================
# Docker 部署
# =============================================================================
function Install-Docker {
    Write-Step "Docker 部署"

    # 检查 Docker
    $dockerVersion = (docker --version 2>$null)
    if (-not $dockerVersion) {
        Write-Error "Docker 未安装, 请从 https://www.docker.com/products/docker-desktop 安装"
        exit 1
    }
    Write-Info "Docker 版本: $dockerVersion"

    # 检查 Docker Compose
    $composeVersion = (docker compose version 2>$null)
    if (-not $composeVersion) {
        Write-Error "Docker Compose 未安装 (Docker Desktop 已内置)"
        exit 1
    }
    Write-Info "Docker Compose 版本: $composeVersion"

    # 创建 .env
    $envPath = Join-Path $PROJECT_DIR ".env"
    if (-not (Test-Path $envPath)) {
        Write-Info "创建默认 .env 配置文件..."
        Copy-Item (Join-Path $PROJECT_DIR "config\.env.example") $envPath
        Write-Warn "请编辑 $envPath 填入真实 API Key"
    }

    # 构建并启动
    Set-Location $PROJECT_DIR
    Write-Info "构建 Docker 镜像..."
    docker compose build --pull

    Write-Info "启动服务..."
    docker compose up -d app

    # 等待健康检查
    Write-Info "等待服务就绪..."
    for ($i = 1; $i -le 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8524/api/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-Info "服务已就绪 ✓"
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    Write-Info "部署完成! 访问 http://localhost:8524"
    Write-Info "默认账号: admin / admin"
}

# =============================================================================
# 裸机部署
# =============================================================================
function Install-BareMetal {
    Write-Step "裸机部署"

    # 检查 Python
    $pythonVersion = (python --version 2>$null)
    if (-not $pythonVersion) {
        Write-Error "Python 未安装, 请从 https://python.org 下载 Python 3.12+"
        exit 1
    }
    Write-Info "Python 版本: $pythonVersion"

    # 检查 Node.js
    $nodeVersion = (node --version 2>$null)
    if (-not $nodeVersion) {
        Write-Warn "Node.js 未安装, 将跳过前端构建"
    } else {
        Write-Info "Node.js 版本: $nodeVersion"
    }

    # 创建安装目录
    if (-not (Test-Path $INSTALL_DIR)) {
        New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    }
    Write-Info "复制应用到 $INSTALL_DIR..."
    Copy-Item -Path "$PROJECT_DIR\*" -Destination $INSTALL_DIR -Recurse -Force -Exclude ".git","node_modules","__pycache__","*.db"

    # 创建虚拟环境
    Write-Info "创建 Python 虚拟环境..."
    python -m venv $VENV_DIR
    & "$VENV_DIR\Scripts\python" -m pip install --upgrade pip
    & "$VENV_DIR\Scripts\pip" install -r "$INSTALL_DIR\requirements.txt"

    # 创建 .env
    $envPath = Join-Path $INSTALL_DIR ".env"
    if (-not (Test-Path $envPath)) {
        Copy-Item (Join-Path $INSTALL_DIR "config\.env.example") $envPath
        Write-Warn "请编辑 $envPath 填入真实 API Key"
    }

    # 创建运行时目录
    $dirs = @("logs", "database", "data")
    foreach ($d in $dirs) {
        $path = Join-Path $INSTALL_DIR $d
        if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
    }

    # 构建前端
    if ($nodeVersion) {
        Write-Info "构建前端..."
        Set-Location (Join-Path $INSTALL_DIR "frontend")
        npm ci --legacy-peer-deps 2>$null
        if ($LASTEXITCODE -ne 0) { npm install --legacy-peer-deps }
        npm run build
        Set-Location $INSTALL_DIR
    }

    # 创建 Windows 计划任务 (替代 Linux systemd)
    Write-Info "创建 Windows 计划任务..."
    $taskName = "MultiSourceResonance"
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction -Execute "$VENV_DIR\Scripts\python" -Argument "api_server.py" -WorkingDirectory $INSTALL_DIR
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName

    Start-Sleep -Seconds 3
    Write-Info "部署完成! 访问 http://localhost:8524"
    Write-Info "默认账号: admin / admin"
    Write-Info "计划任务: taskschd.msc → MultiSourceResonance"
}

# =============================================================================
# 卸载
# =============================================================================
function Uninstall-App {
    Write-Step "卸载 $APP_NAME"

    # 停止 Docker
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Set-Location $PROJECT_DIR
        docker compose down -v 2>$null
        Write-Info "Docker 容器已停止"
    }

    # 删除计划任务
    $taskName = "MultiSourceResonance"
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Info "计划任务已删除"
    }

    # 删除安装目录
    $confirm = Read-Host "删除数据目录 $INSTALL_DIR? [y/N]"
    if ($confirm -eq "y" -or $confirm -eq "Y") {
        Remove-Item -Path $INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        Write-Info "数据目录已删除"
    }

    Write-Info "卸载完成"
}

# =============================================================================
# 主流程
# =============================================================================
function Main {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════╗"
    Write-Host "║  多源共振监控系统 - 一键部署脚本 (Windows)  ║"
    Write-Host "╚══════════════════════════════════════════════╝"
    Write-Host ""

    if ($Uninstall) {
        Uninstall-App
        return
    }

    Preflight
    Choose-Mode

    if ($Docker) { Install-Docker }
    elseif ($BareMetal) { Install-BareMetal }
    else { Write-Error "未知部署模式"; exit 1 }

    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════╗"
    Write-Host "║  部署完成!                                  ║"
    Write-Host "║  Dashboard: http://localhost:8524           ║"
    Write-Host "║  API Docs:  http://localhost:8524/docs      ║"
    Write-Host "║  默认账号:  admin / admin                   ║"
    Write-Host "╚══════════════════════════════════════════════╝"
    Write-Host ""
}

Main
