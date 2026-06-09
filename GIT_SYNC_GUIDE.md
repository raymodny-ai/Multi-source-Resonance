# Git同步指南 - 多源共振监控系统

## 📋 前置要求

### 1. 安装Git
如果您的系统尚未安装Git,请先下载并安装:
- **Windows**: https://git-scm.com/download/win
- 安装时勾选 "Add Git to PATH"

### 2. 验证安装
```bash
git --version
# 预期输出: git version 2.x.x
```

---

## 🚀 快速同步步骤

### Step 1: 初始化Git仓库

```bash
# 进入项目目录
cd "d:\Financial Project\Multi-source Resonance"

# 初始化Git仓库
git init
```

### Step 2: 配置Git用户信息

```bash
# 设置用户名(替换为您的GitHub用户名)
git config user.name "raymodny-ai"

# 设置邮箱(替换为您的GitHub注册邮箱)
git config user.email "your-email@example.com"
```

### Step 3: 添加所有文件

```bash
# 添加所有文件到暂存区
git add .

# 查看即将提交的文件列表
git status
```

**注意**: 以下文件应被`.gitignore`排除(已配置):
- `*.pyc`, `__pycache__/` - Python编译文件
- `.env` - 环境变量(含API密钥)
- `database/*.db` - SQLite数据库文件
- `logs/*.log` - 日志文件
- `data/` - 临时数据目录

### Step 4: 首次提交

```bash
# 提交代码
git commit -m "Initial commit: Multi-source Resonance Monitoring System v1.1.0

Features:
- 7 data fetchers (Tradier, Yahoo, CCXT, SqueezeMetrics, ChartExchange, Stockgrid, DBMF)
- 4 quant logic engines (GEX, VIX, Crypto Leverage, Dark Pool Verifier)
- Signal engine with resonance scoring (LEVEL 1/2/3 alerts)
- Async scheduler with ThreadPoolExecutor
- Database persistence (SQLite WAL mode)
- Multi-channel notifications (Email/Telegram/Discord)
- Fallback manager with circuit breaker

Fixes applied:
- C1-C5: Critical issues (async/await, division by zero, state persistence)
- W1-W8: Warning issues (exception handling, type hints, config defaults)
- I1-I5: Info optimizations (docstrings, constants extraction)

Code stats: ~11,000 lines, 24 core modules, 127+ tests"
```

### Step 5: 添加远程仓库

```bash
# 添加GitHub远程仓库
git remote add origin https://github.com/raymodny-ai/Multi-source-Resonance.git

# 验证远程仓库配置
git remote -v
# 预期输出:
# origin  https://github.com/raymodny-ai/Multi-source-Resonance.git (fetch)
# origin  https://github.com/raymodny-ai/Multi-source-Resonance.git (push)
```

### Step 6: 推送到GitHub

```bash
# 推送到main分支(首次推送需设置上游分支)
git push -u origin main

# 如果GitHub仓库为空,可能需要强制推送
git push -u origin main --force
```

**身份验证**:
- 首次推送时会提示输入GitHub用户名和密码
- **密码使用Personal Access Token(PAT)**而非账户密码
- 获取PAT: GitHub → Settings → Developer settings → Personal access tokens → Generate new token
- 权限勾选: `repo` (完整仓库访问)

---

## 🔧 常见问题排查

### Q1: 推送失败 - "remote origin already exists"
**原因**: 远程仓库已存在  
**解决**:
```bash
# 查看现有远程仓库
git remote -v

# 如需更换远程URL
git remote set-url origin https://github.com/raymodny-ai/Multi-source-Resonance.git
```

### Q2: 推送失败 - "Authentication failed"
**原因**: 认证信息错误  
**解决**:
```bash
# 清除缓存的凭据
git credential-manager uninstall  # Windows
# 或
git config --global --unset credential.helper

# 重新推送(会提示重新输入)
git push -u origin main
```

### Q3: 推送失败 - "Updates were rejected because the remote contains work"
**原因**: 远程仓库已有内容  
**解决**:
```bash
# 方案A: 拉取远程内容合并(推荐)
git pull origin main --allow-unrelated-histories
git push -u origin main

# 方案B: 强制覆盖远程仓库(谨慎使用!)
git push -u origin main --force
```

### Q4: 大文件推送失败
**原因**: 某些文件超过GitHub单文件限制(100MB)  
**解决**:
```bash
# 检查大文件
git rev-list --objects | sort -k 2 -n -r | head -10

# 从Git追踪中移除大文件(但保留在本地)
git rm --cached database/monitoring.db
git rm --cached logs/*.log

# 重新提交
git commit -m "Remove large files from Git tracking"
git push
```

### Q5: .env文件被误提交
**风险**: API密钥泄露  
**紧急处理**:
```bash
# 1. 从Git历史中彻底删除.env
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch config/.env' \
  --prune-empty --tag-name-filter cat -- --all

# 2. 强制推送覆盖远程历史
git push origin --force --all

# 3. 立即撤销泄露的API密钥!
```

**预防**: 确保`.gitignore`包含`.env`

---

## ✅ 验证同步成功

### 1. 检查GitHub仓库
访问: https://github.com/raymodny-ai/Multi-source-Resonance

确认以下内容已上传:
- ✅ 所有Python源代码文件
- ✅ requirements.txt
- ✅ config/settings.py (不含敏感信息)
- ✅ README.md / PROJECT_SUMMARY.md
- ✅ tests/ 测试文件
- ✅ database/schema.sql

### 2. 克隆验证
```bash
# 在新目录测试克隆
cd ..
git clone https://github.com/raymodny-ai/Multi-source-Resonance.git test-clone
cd test-clone

# 验证文件完整性
ls -la
python -c "from config.settings import Config; print('OK')"
```

### 3. 检查Commit历史
```bash
git log --oneline
# 预期看到Initial commit及后续修复记录
```

---

## 🔄 后续更新流程

### 日常开发后同步
```bash
# 1. 查看修改
git status

# 2. 添加修改的文件
git add .

# 3. 提交
git commit -m "Fix: [简要描述修改内容]"

# 4. 推送
git push
```

### 查看远程状态
```bash
# 查看远程分支
git branch -r

# 拉取最新代码
git pull origin main
```

---

## 🛡️ 安全建议

### 1. 永远不要提交的文件
- ❌ `config/.env` (API密钥)
- ❌ `database/*.db` (敏感数据)
- ❌ `logs/*.log` (可能含调试信息)
- ❌ `*.pyc`, `__pycache__/` (编译文件)

### 2. 使用.git/info/exclude本地排除
如果某些文件只想在本地忽略:
```bash
# 编辑 .git/info/exclude
echo "temp_data/" >> .git/info/exclude
```

### 3. 定期更新Personal Access Token
- PAT有效期建议设为90天
- 过期前生成新Token并更新Git凭据

---

## 📞 需要帮助?

如果遇到问题:
1. 检查Git版本: `git --version` (建议≥2.30)
2. 查看详细错误: `git push -v origin main`
3. GitHub官方文档: https://docs.github.com/en/get-started

---

**最后更新**: 2026-06-09  
**适用版本**: Multi-source Resonance v1.1.0
