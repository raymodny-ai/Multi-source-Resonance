# Phase 6 通知与展示层 - 快速参考

## 🚀 快速开始

### 1. 导入模块

```python
from notification import AlertSender, create_alert_sender
```

### 2. 创建实例

```python
# 方式1: 直接实例化
sender = AlertSender()

# 方式2: 使用便捷函数
sender = create_alert_sender()
```

### 3. 发送告警

#### 单渠道发送

```python
# 邮件
sender.send_email_alert(
    subject="共振信号触发",
    message="详细内容...",
    html_format=True
)

# Telegram
sender.send_telegram_message(
    message="**加粗** 和 *斜体*",
    parse_mode='Markdown'
)

# Discord
sender.send_discord_webhook(
    title="告警标题",
    description="告警内容",
    color=15158332  # 红色
)
```

#### 多渠道发送

```python
results = sender.send_multi_channel_alert(
    subject="LEVEL 3共振抄底信号",
    message="详细消息内容",
    channels=['email', 'telegram', 'discord']
)

# 检查结果
print(results)  # {'email': True, 'telegram': True, 'discord': False}
```

#### LEVEL 3格式化告警

```python
from datetime import datetime

message = sender.format_level3_alert(
    resonance_result=resonance_data,
    hawkes_result=hawkes_data,
    current_time=datetime.now(),
    put_wall_range=(5800, 5850)  # 可选
)

# 发送格式化消息
sender.send_multi_channel_alert(
    subject="🚨 LEVEL 3共振抄底信号",
    message=message,
    channels=['email', 'telegram']
)
```

## 📋 API参考

### AlertSender类

#### `__init__()`
初始化通知渠道配置,从config.settings读取所有配置。

#### `send_email_alert(subject, message, recipients=None, html_format=True)`
- **参数**:
  - `subject` (str): 邮件主题
  - `message` (str): 邮件内容
  - `recipients` (List[str], optional): 收件人列表
  - `html_format` (bool): 是否使用HTML格式
- **返回**: bool - 发送成功返回True

#### `send_telegram_message(message, parse_mode='Markdown', chat_id=None)`
- **参数**:
  - `message` (str): 消息内容(支持Markdown)
  - `parse_mode` (str): 解析模式('Markdown'或'HTML')
  - `chat_id` (str, optional): 聊天ID
- **返回**: bool - 发送成功返回True

#### `send_discord_webhook(title, description, color=15158332, webhook_url=None)`
- **参数**:
  - `title` (str): 嵌入标题
  - `description` (str): 嵌入描述
  - `color` (int): 嵌入颜色(十进制)
  - `webhook_url` (str, optional): Webhook URL
- **返回**: bool - 发送成功返回True

#### `send_multi_channel_alert(subject, message, channels=['email', 'telegram'], **kwargs)`
- **参数**:
  - `subject` (str): 告警主题
  - `message` (str): 告警内容
  - `channels` (List[str]): 渠道列表 ['email', 'telegram', 'discord']
  - `**kwargs`: 额外参数传递给各渠道
- **返回**: Dict[str, bool] - 各渠道发送结果

#### `format_level3_alert(resonance_result, hawkes_result, current_time, put_wall_range=None)`
- **参数**:
  - `resonance_result` (dict): 共振评分结果
  - `hawkes_result` (dict): Hawkes分支比结果
  - `current_time` (datetime): 触发时间
  - `put_wall_range` (tuple, optional): Put Wall区间 (lower, upper)
- **返回**: str - 格式化的Markdown消息

### 便捷函数

#### `create_alert_sender()`
创建并返回AlertSender实例。

## ⚙️ 环境变量配置

### .env文件示例

```bash
# SMTP邮件配置
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENTS=user1@example.com,user2@example.com

# Telegram Bot配置
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

# Discord Webhook配置
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456789/abcdefg...
```

### 配置获取指南

#### Gmail应用专用密码
1. 启用Google账户2步验证
2. 访问 https://myaccount.google.com/apppasswords
3. 生成16位应用专用密码
4. 填入EMAIL_PASSWORD

#### Telegram Bot Token和Chat ID
1. 在Telegram搜索 @BotFather
2. 发送 `/newbot` 创建Bot
3. 获取Bot Token
4. 向Bot发送消息
5. 访问 `https://api.telegram.org/bot<TOKEN>/getUpdates` 获取chat_id

#### Discord Webhook URL
1. 右键点击Discord频道 → "编辑频道"
2. 选择"整合" → "Webhooks"
3. 点击"新建Webhook"
4. 复制Webhook URL

## 🔧 集成示例

### 在主调度器中使用

```python
from main_scheduler import DataFetcherScheduler
from notification import AlertSender
from signal_engine.signal_trigger import SignalTrigger

class EnhancedScheduler(DataFetcherScheduler):
    def __init__(self):
        super().__init__()
        self.alert_sender = AlertSender()
        self.signal_trigger = SignalTrigger()
    
    def check_and_alert(self):
        """检查信号并发送告警"""
        # 获取最新数据
        data = self.fetch_all_data()
        
        # 计算共振评分
        resonance = self.signal_trigger.calculate_resonance(data)
        
        # 检查是否触发LEVEL 3信号
        if resonance['total_score'] >= 90:
            # 格式化告警消息
            message = self.alert_sender.format_level3_alert(
                resonance_result=resonance,
                hawkes_result=self.get_hawkes_result(),
                current_time=datetime.now(),
                put_wall_range=self.get_put_wall_range()
            )
            
            # 多渠道发送
            results = self.alert_sender.send_multi_channel_alert(
                subject=f"🚨 LEVEL 3共振抄底信号 (得分: {resonance['total_score']})",
                message=message,
                channels=['email', 'telegram', 'discord']
            )
            
            logger.info(f"告警发送结果: {results}")
```

## 🎨 LEVEL 3告警模板预览

```markdown
🚨 **[SYSTEM ALERT] 流动性清算衰竭:多因子共振抄底信号触发**

**⏰ 触发时间**: 2026-06-09 12:00:00 EST  
**当前共振得分**: 95 / 100（全维度微观结构已完成排雷）

### 📊 美股微观结构与价格行为

* **做市商 GEX**: 已翻正至+$150M **[🟢]**
* **VIX 期限结构**: 回归Contango(0.98) **[🟢]**
* **当前点位评估**: 纳指100在目标 **Put Wall [5800 - 5850]** 核心承接区企稳。

### 🏛️ 华尔街暗盘大资金追踪（多源校验）

* **暗盘吸筹**: 强吸筹确认(3/3指标触发) **[🟢]**

### 🌐 加密金丝雀多源校验

* **杠杆清洗**: 去杠杆完成 **[🟢]**

**🤖 系统量化提示**: 基于 Hawkes Process 测算,分支比μ=0.85，自激效应显著

✅ **触发条件**:
  - GEX > $100M
  - VIX < 1.0
  - 暗盘吸筹强度 > 45
  - 加密杠杆率 < 2%

---
*此消息由多源共振监控系统自动生成*
```

## 🧪 测试验证

运行测试脚本:

```bash
py test_phase6_notification.py
```

预期输出:
```
[PASS] 模块导入
[PASS] 实例化
[PASS] 配置加载
[PASS] LEVEL 3告警格式化

测试结果: 4 通过, 0 失败

[PASS] Phase 6 所有测试通过!
```

## ❗ 注意事项

1. **异常处理**: 所有发送方法捕获异常并返回False,不会抛出异常
2. **超时控制**: Telegram和Discord请求timeout=10秒
3. **日志记录**: 关键操作记录INFO/ERROR日志
4. **配置验证**: 缺少必要配置时会记录WARNING并跳过发送
5. **编码兼容**: Windows控制台可能不支持emoji,建议在实际通知渠道中查看完整效果

## 📞 故障排查

### 邮件发送失败
- 检查SMTP服务器和端口是否正确
- 确认使用的是应用专用密码而非登录密码
- 检查防火墙是否阻止587端口

### Telegram发送失败
- 验证Bot Token是否正确
- 确认已向Bot发送过消息(激活chat_id)
- 检查网络连接是否正常

### Discord发送失败
- 验证Webhook URL是否有效
- 检查Webhook是否被删除或禁用
- 确认Discord服务器权限设置

## 🔗 相关文档

- [Phase 6 完成报告](PHASE6_COMPLETION_REPORT.md)
- [配置文件参考](config/settings.py)
- [环境变量模板](config/.env.example)
