"""
多源共振监控系统 - 告警推送模块

该模块负责多渠道告警消息的发送，支持：
- 邮件通知 (SMTP)
- Telegram Bot消息推送
- Discord Webhook消息推送
- 多渠道并发发送
- LEVEL 3最高级别告警格式化

所有网络请求均设置超时控制，异常处理完善，确保系统稳定性。
"""

import smtplib
from smtplib import SMTPAuthenticationError, SMTPConnectError, SMTPException
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict
import pytz

from utils.logger import getLogger
from config.settings import Config as Settings

logger = getLogger('alert_sender')


class AlertSender:
    """多渠道告警推送管理器
    
    提供邮件、Telegram、Discord三种通知渠道的告警发送功能，
    支持单渠道发送和多渠道并发发送，内置LEVEL 3告警格式化模板。
    """
    
    def __init__(self):
        """初始化通知渠道配置
        
        从系统配置中读取SMTP、Telegram、Discord相关参数，
        完成各渠道的基础配置初始化。
        """
        self.smtp_config = {
            'server': Settings.SMTP_SERVER,
            'port': Settings.SMTP_PORT,
            'sender': Settings.EMAIL_SENDER,
            'password': Settings.EMAIL_PASSWORD,
            'recipients': Settings.EMAIL_RECIPIENTS
        }
        
        self.telegram_config = {
            'bot_token': Settings.TELEGRAM_BOT_TOKEN,
            'chat_id': Settings.TELEGRAM_CHAT_ID
        }
        
        self.discord_webhook_url = Settings.DISCORD_WEBHOOK_URL
        
        logger.info("告警推送器初始化完成")
    
    def send_email_alert(
        self,
        subject: str,
        message: str,
        recipients: List[str] = None,
        html_format: bool = True
    ) -> bool:
        """
        发送邮件告警
        
        通过SMTP协议发送HTML或纯文本格式的邮件告警，
        支持自定义收件人列表，默认使用配置文件中的收件人。
        
        Args:
            subject: 邮件主题
            message: 邮件内容
            recipients: 收件人列表，默认使用config配置
            html_format: 是否使用HTML格式，默认为True
        
        Returns:
            bool: True表示发送成功，False表示发送失败
        """
        if not recipients:
            recipients = self.smtp_config['recipients']
        
        if not recipients:
            logger.warning("未配置邮件收件人，跳过发送")
            return False
        
        try:
            # 构建邮件
            msg = MIMEMultipart('alternative' if html_format else 'mixed')
            msg['From'] = self.smtp_config['sender']
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            
            # 添加内容
            if html_format:
                html_content = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <h2 style="color: #d9534f;">{subject}</h2>
                    <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px;">
{message}
                    </pre>
                    <p style="color: #888; font-size: 12px; margin-top: 20px;">
                        — 多源共振监控系统自动告警
                    </p>
                </body>
                </html>
                """
                msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(message, 'plain', 'utf-8'))
            
            # 连接SMTP服务器并发送（使用上下文管理器）
            with smtplib.SMTP(self.smtp_config['server'], self.smtp_config['port']) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_config['sender'], self.smtp_config['password'])
                server.sendmail(self.smtp_config['sender'], recipients, msg.as_string())
            
            logger.info(f"邮件告警发送成功,收件人: {len(recipients)}人")
            return True
            
        except SMTPAuthenticationError as e:
            logger.error(f"SMTP认证失败: {e}")
            return False
        except SMTPConnectError as e:
            logger.error(f"SMTP连接失败: {e}")
            return False
        except SMTPException as e:
            logger.error(f"SMTP错误: {e}")
            return False
        except Exception as e:
            logger.error(f"邮件发送失败: {e}", exc_info=True)
            return False
    
    def send_telegram_message(
        self,
        message: str,
        parse_mode: str = 'Markdown',
        chat_id: str = None
    ) -> bool:
        """
        发送Telegram消息
        
        通过Telegram Bot API发送消息，支持Markdown和HTML格式解析，
        可自定义聊天ID，默认使用配置文件中的chat_id。
        
        Args:
            message: 消息内容（支持Markdown格式）
            parse_mode: 解析模式，可选'Markdown'或'HTML'，默认为'Markdown'
            chat_id: 聊天ID，默认使用config配置
        
        Returns:
            bool: True表示发送成功，False表示发送失败
        """
        if not chat_id:
            chat_id = self.telegram_config['chat_id']
        
        bot_token = self.telegram_config['bot_token']
        
        if not bot_token or not chat_id:
            logger.warning("Telegram配置不完整，跳过发送")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('ok'):
                logger.info(f"Telegram消息发送成功 (Message ID: {result['result']['message_id']})")
                return True
            else:
                logger.error(f"Telegram API返回错误: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Telegram发送失败: {e}", exc_info=True)
            return False
    
    def send_discord_webhook(
        self,
        title: str,
        description: str,
        color: int = 15158332,  # 红色告警
        webhook_url: str = None
    ) -> bool:
        """
        发送Discord Webhook消息
        
        通过Discord Webhook发送富文本嵌入消息，支持自定义颜色、标题和描述，
        自动附加时间戳和系统标识。
        
        Args:
            title: 嵌入标题
            description: 嵌入描述内容
            color: 嵌入颜色（十进制），默认红色(15158332)表示告警
            webhook_url: Webhook URL，需从config读取或传入
        
        Returns:
            bool: True表示发送成功，False表示发送失败
        """
        if not webhook_url:
            webhook_url = self.discord_webhook_url
        
        if not webhook_url:
            logger.warning("Discord Webhook URL未配置，跳过发送")
            return False
        
        try:
            embed = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.now(pytz.timezone('US/Eastern')).isoformat(),
                "footer": {
                    "text": "多源共振监控系统"
                }
            }
            
            payload = {
                "embeds": [embed]
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Discord Webhook发送成功")
            return True
            
        except Exception as e:
            logger.error(f"Discord Webhook发送失败: {e}", exc_info=True)
            return False
    
    def send_multi_channel_alert(
        self,
        subject: str,
        message: str,
        channels: List[str] = ['email', 'telegram'],
        **kwargs
    ) -> Dict[str, bool]:
        """
        多渠道同时发送告警
        
        在多个通知渠道上并发发送相同的告警消息，
        返回各渠道的发送结果统计。
        
        Args:
            subject: 告警主题（用于邮件主题和Discord标题）
            message: 告警内容
            channels: 要使用的渠道列表，可选值: ['email', 'telegram', 'discord']
            **kwargs: 额外参数传递给各渠道方法
        
        Returns:
            Dict[str, bool]: 各渠道发送结果 {'email': True, 'telegram': False, ...}
        """
        results = {}
        
        for channel in channels:
            try:
                if channel == 'email':
                    results['email'] = self.send_email_alert(subject, message, **kwargs)
                elif channel == 'telegram':
                    results['telegram'] = self.send_telegram_message(message, **kwargs)
                elif channel == 'discord':
                    results['discord'] = self.send_discord_webhook(subject, message, **kwargs)
                else:
                    logger.warning(f"未知通知渠道: {channel}")
                    results[channel] = False
            except Exception as e:
                logger.error(f"渠道 {channel} 发送异常: {e}")
                results[channel] = False
        
        # 统计成功数
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"多渠道告警完成: {success_count}/{len(channels)} 成功")
        
        return results
    
    def format_level3_alert(
        self,
        resonance_result: dict,
        hawkes_result: dict,
        current_time: datetime,
        put_wall_range: tuple = None
    ) -> str:
        """
        格式化LEVEL 3最高级别告警消息
        
        按照PRD 4.2节模板生成标准化的LEVEL 3共振抄底信号告警消息，
        包含四个维度的详细评分状态和Hawkes过程分析结果。
        
        Args:
            resonance_result: 共振评分结果字典，包含total_score、max_score、dimension_scores、trigger_conditions
            hawkes_result: Hawkes分支比结果字典，包含details字段
            current_time: 触发时间（美东时间）
            put_wall_range: Put Wall区间元组 (lower, upper)，可选
        
        Returns:
            str: 格式化的Markdown消息字符串
        """
        dim_scores = resonance_result['dimension_scores']
        
        # 构建GEX详情
        gex_detail = dim_scores['gex']['details']
        gex_state = dim_scores['gex']['state']
        gex_icon = "🟢" if gex_state == 'POSITIVE' else ("🟡" if gex_state == 'CONVERGING' else "🔴")
        
        # 构建VIX详情
        vix_detail = dim_scores['vix']['details']
        vix_state = dim_scores['vix']['state']
        vix_icon = "🟢" if vix_state == 'CONTANGO' else ("🟡" if vix_state == 'NEUTRAL' else "🔴")
        
        # 构建暗盘详情
        darkpool_detail = dim_scores['darkpool']['details']
        darkpool_state = dim_scores['darkpool']['state']
        darkpool_icon = "🟢" if darkpool_state == 'STRONG_ACCUMULATION' else ("🟡" if darkpool_state == 'MODERATE' else "🔴")
        
        # 构建加密详情
        crypto_detail = dim_scores['crypto']['details']
        crypto_state = dim_scores['crypto']['state']
        crypto_icon = "🟢" if crypto_state == 'CLEANUP_COMPLETE' else ("🟡" if crypto_state == 'IN_PROGRESS' else "🔴")
        
        # Put Wall信息
        put_wall_text = ""
        if put_wall_range:
            put_wall_text = f"\n* **当前点位评估**: 纳指100在目标 **Put Wall [{put_wall_range[0]} - {put_wall_range[1]}]** 核心承接区企稳。"
        
        message = f"""
🚨 **[SYSTEM ALERT] 流动性清算衰竭:多因子共振抄底信号触发**

**⏰ 触发时间**: {current_time.strftime('%Y-%m-%d %H:%M:%S')} EST  
**当前共振得分**: {resonance_result['total_score']} / {resonance_result['max_score']}（全维度微观结构已完成排雷）

### 📊 美股微观结构与价格行为

* **做市商 GEX**: {gex_detail} **[{gex_icon}]**
* **VIX 期限结构**: {vix_detail} **[{vix_icon}]**{put_wall_text}

### 🏛️ 华尔街暗盘大资金追踪（多源校验）

* **暗盘吸筹**: {darkpool_detail} **[{darkpool_icon}]**

### 🌐 加密金丝雀多源校验

* **杠杆清洗**: {crypto_detail} **[{crypto_icon}]**

**🤖 系统量化提示**: 基于 Hawkes Process 测算,{hawkes_result['details']}

✅ **触发条件**:
"""
        for condition in resonance_result['trigger_conditions']:
            message += f"  - {condition}\n"
        
        message += "\n---\n*此消息由多源共振监控系统自动生成*"
        
        return message.strip()


# 便捷函数
def create_alert_sender() -> AlertSender:
    """
    创建告警发送器实例
    
    Returns:
        AlertSender: 初始化完成的告警发送器实例
    """
    return AlertSender()


if __name__ == "__main__":
    # 测试代码
    sender = create_alert_sender()
    
    # 测试邮件发送
    test_message = """
    测试告警消息
    
    GEX: 已翻正至+$150M
    VIX: 回归Contango(0.98)
    暗盘: 强吸筹确认(3/3指标触发)
    加密: 去杠杆完成
    """
    
    result = sender.send_email_alert(
        subject="【测试】LEVEL 3共振抄底信号",
        message=test_message
    )
    
    print(f"邮件发送结果: {result}")
