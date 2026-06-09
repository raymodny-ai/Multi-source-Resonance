# 多源共振暗盘与流动性微观结构监控系统

## 项目概述

这是一个基于多源数据共振的金融监控系统，用于实时监控股票市场的暗盘活动、DIX/GEX指标以及流动性微观结构变化。系统通过综合分析多个数据源，自动识别潜在的交易信号并发送通知。

## Phase 1 - 基础架构 (已完成 ✓)

### 目录结构

```
Multi-source Resonance/
├── config/                  # 配置管理
│   ├── __init__.py
│   ├── settings.py         # 系统配置类
│   └── .env.example        # 环境变量模板
├── data_fetchers/          # 数据抓取模块
│   └── __init__.py
├── quant_logic/            # 量化逻辑模块
│   └── __init__.py
├── signal_engine/          # 信号引擎模块
│   └── __init__.py
├── notification/           # 通知模块
│   └── __init__.py
├── utils/                  # 工具模块
│   ├── __init__.py
│   ├── logger.py          # 日志管理
│   └── exceptions.py      # 自定义异常
├── tests/                  # 测试模块
│   └── __init__.py
├── database/               # 数据库模块
│   └── __init__.py
├── logs/                   # 日志文件目录
├── requirements.txt        # Python依赖
├── verify_setup.py        # 验证脚本
└── README.md              # 本文件
```

### 核心组件

#### 1. 配置管理系统 (`config/settings.py`)

- 使用 `dotenv` 加载环境变量
- 集中管理API密钥、阈值参数、抓取频率等配置
- 提供类型安全的配置访问接口
- 包含配置验证功能

**主要配置项：**
- API密钥: Tradier, SqueezeMetrics
- 通知配置: SMTP邮件, Telegram Bot
- 抓取频率: 盘中15分钟, 盘后20:30
- 阈值参数: DIX_THRESHOLD=45.0, SHORT_VOLUME_THRESHOLD=45.0
- 监控标的: SPY, QQQ, IWM, AAPL, MSFT, NVDA, TSLA, AMD

#### 2. 日志框架 (`utils/logger.py`)

- 分级日志输出 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- 同时输出到控制台和文件
- 按日期分割日志文件 (`logs/app_YYYYMMDD.log`)
- 错误日志单独记录 (`logs/error_YYYYMMDD.log`)
- 支持动态修改日志级别

**使用示例：**
```python
from utils.logger import getLogger

logger = getLogger('data_fetchers')
logger.info('开始获取数据...')
logger.error('数据获取失败', exc_info=True)
```

#### 3. 自定义异常 (`utils/exceptions.py`)

定义统一的异常层次结构：

- `DataFetchError`: 数据获取失败
- `CalculationError`: 量化计算错误
- `SignalTriggerError`: 信号触发异常
- `DatabaseError`: 数据库操作错误
- `ConfigurationError`: 配置错误
- `NotificationError`: 通知发送错误

每个异常包含 `error_code` 和 `details` 属性，便于错误追踪和处理。

**使用示例：**
```python
from utils.exceptions import DataFetchError

try:
    data = fetch_market_data()
except DataFetchError as e:
    logger.error(f"错误 {e.error_code}: {e.details}")
```

### 快速开始

#### 1. 环境要求

- Python >= 3.10
- Windows / Linux / macOS

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 配置环境变量

```bash
# 复制环境变量模板
cp config/.env.example config/.env

# 编辑 config/.env 文件，填入您的API密钥和配置
```

**必要配置项：**
- `TRADIER_API_KEY`: Tradier API密钥
- `SQUEEZEMETRICS_API_KEY`: SqueezeMetrics API密钥
- `EMAIL_SENDER`: 发件人邮箱
- `EMAIL_PASSWORD`: 邮箱应用密码
- `EMAIL_RECIPIENTS`: 收件人列表（逗号分隔）

#### 4. 验证安装

```bash
python verify_setup.py
```

预期输出应显示所有检查项通过。

### 开发指南

#### 添加新模块

1. 在相应目录下创建Python文件
2. 使用 `getLogger(__name__)` 创建logger
3. 使用自定义异常类处理错误
4. 从 `config.settings` 读取配置

**示例：**
```python
"""data_fetchers/tradier_client.py"""
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import config

logger = getLogger(__name__)

class TradierClient:
    def __init__(self):
        self.api_key = config.TRADIER_API_KEY
        self.base_url = config.TRADIER_BASE_URL
    
    def fetch_options_chain(self, symbol: str):
        try:
            # 实现数据获取逻辑
            pass
        except Exception as e:
            raise DataFetchError(
                f"无法获取{symbol}的期权链",
                error_code="TRADIER_OPTIONS_FETCH_FAILED",
                details={"symbol": symbol, "error": str(e)}
            )
```

#### 日志最佳实践

- 使用适当的日志级别
- 在关键操作前后记录日志
- 捕获异常时记录详细上下文
- 避免在循环中记录过多DEBUG日志

```python
logger.debug('详细调试信息')      # 开发时使用
logger.info('正常操作流程')       # 记录关键步骤
logger.warning('潜在问题警告')     # 非致命问题
logger.error('错误发生')           # 错误但可恢复
logger.critical('严重错误')        # 系统级错误
```

#### 异常处理最佳实践

- 使用具体的异常类而非通用Exception
- 提供有意义的错误代码
- 在details中包含足够的上下文信息
- 在合适的层级捕获和处理异常

```python
try:
    result = calculate_dix(data)
except CalculationError as e:
    logger.error(f"DIX计算失败: {e.error_code}", extra=e.details)
    # 决定是重试、降级还是上报
```

### 下一步开发计划

**Phase 2 - 数据抓取层**
- [ ] 实现Tradier API客户端
- [ ] 实现SqueezeMetrics API客户端
- [ ] 添加数据缓存机制
- [ ] 实现重试逻辑

**Phase 3 - 量化逻辑层**
- [ ] 实现DIX/GEX指标计算
- [ ] 实现背离检测算法
- [ ] 实现统计显著性检验

**Phase 4 - 信号引擎**
- [ ] 实现多因子信号综合
- [ ] 实现信号强度评分
- [ ] 实现信号去重与过滤

**Phase 5 - 通知系统**
- [ ] 实现邮件通知
- [ ] 实现Telegram通知
- [ ] 实现通知模板

**Phase 6 - 调度与持久化**
- [ ] 实现APScheduler定时任务
- [ ] 实现SQLite数据存储
- [ ] 实现历史数据分析

### 技术栈

- **数据处理**: pandas, numpy, scipy
- **HTTP客户端**: aiohttp, requests
- **网页抓取**: playwright
- **重试机制**: tenacity
- **数据验证**: pydantic
- **任务调度**: APScheduler
- **环境管理**: python-dotenv

### 贡献指南

1. 遵循PEP 8编码规范
2. 为所有公共函数添加docstring
3. 使用类型提示
4. 编写单元测试
5. 提交前运行验证脚本

### 许可证

本项目仅供学习和研究使用。

### 联系方式

如有问题或建议，请提交Issue或Pull Request。

---

**当前版本**: Phase 1 - 基础架构  
**最后更新**: 2026-06-09  
**状态**: ✅ 基础架构已完成
