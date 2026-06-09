"""
多源共振监控系统 - 通知模块

该模块负责信号触发时的通知发送，支持：
- 邮件通知 (SMTP)
- Telegram Bot消息
- Discord Webhook消息
- LEVEL 3告警格式化
- 多渠道并发发送
"""

from notification.alert_sender import AlertSender, create_alert_sender

__all__ = ['AlertSender', 'create_alert_sender']
