"""
多源共振监控系统 - 信号触发与状态机

该模块实现信号触发状态机，防止重复告警，包括：
- 冷却期机制 (同一信号在指定时间内不重复触发)
- 状态转换管理 (IDLE → MONITORING → ALERT_TRIGGERED → COOLDOWN)
- 告警历史记录
- 告警消息格式化 (符合PRD 4.2节模板)

所有时间使用EST (美东时间) 时区。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
from pathlib import Path

import pytz

from config.settings import Config

logger = logging.getLogger(__name__)


class SignalStateMachine:
    """信号触发状态机，防止重复告警(支持持久化)
    
    该类维护信号触发的状态流转，确保同一级别的告警在冷却期内不会重复发送。
    状态转换规则:
        IDLE → MONITORING: 检测到初步信号
        MONITORING → ALERT_TRIGGERED: 达到预警阈值
        ALERT_TRIGGERED → COOLDOWN: 告警发送后进入冷却
        COOLDOWN → IDLE: 冷却期结束
    
    Attributes:
        cooldown_minutes: 冷却时间 (分钟)，默认30分钟
        last_alert_time: 上次告警时间
        current_state: 当前状态 ('IDLE', 'MONITORING', 'ALERT_TRIGGERED', 'COOLDOWN')
        alert_history: 历史告警记录列表
    """
    
    STATE_FILE = './data/signal_state.json'
    
    def __init__(self, cooldown_minutes: int = 30):
        """初始化状态机
        
        Args:
            cooldown_minutes: 冷却时间 (分钟)，同一信号在此期间不重复触发
                             默认30分钟，可根据市场波动性调整
        
        Examples:
            >>> sm = SignalStateMachine(cooldown_minutes=30)
            >>> print(sm.current_state)  # 'IDLE'
        """
        self.cooldown_minutes = cooldown_minutes
        self.current_state: str = 'IDLE'
        self.alert_history: List[Dict[str, any]] = []
        
        # 从文件恢复状态
        self.last_alert_time = self._load_state()
        
        logger.info(
            f"SignalStateMachine 初始化完成 (冷却时间: {cooldown_minutes}分钟, "
            f"last_alert_time={self.last_alert_time})"
        )
    
    def _load_state(self) -> Optional[datetime]:
        """从文件加载状态"""
        try:
            state_file = Path(self.STATE_FILE)
            if state_file.exists():
                with open(state_file, 'r') as f:
                    data = json.load(f)
                
                last_alert_str = data.get('last_alert_time')
                if last_alert_str:
                    # 解析ISO格式时间字符串
                    last_alert_time = datetime.fromisoformat(last_alert_str)
                    
                    # 转换为EST时区
                    est = pytz.timezone('US/Eastern')
                    if last_alert_time.tzinfo is None:
                        last_alert_time = est.localize(last_alert_time)
                    else:
                        last_alert_time = last_alert_time.astimezone(est)
                    
                    logger.info(f"Restored last_alert_time: {last_alert_time}")
                    return last_alert_time
        except Exception as e:
            logger.warning(f"Failed to load signal state: {e}")
        
        return None
    
    def _save_state(self):
        """保存状态到文件"""
        try:
            state_file = Path(self.STATE_FILE)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'last_alert_time': self.last_alert_time.isoformat() if self.last_alert_time else None,
                'current_state': self.current_state,
                'alert_count': len(self.alert_history)
            }
            
            with open(state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save signal state: {e}")
    
    def check_and_trigger(
        self,
        resonance_result: Dict[str, any],
        current_time: datetime
    ) -> Dict[str, any]:
        """检查是否触发告警并返回结果
        
        该方法根据共振评分结果和当前时间，判断是否应该发送告警。
        如果处于冷却期，则跳过告警并返回剩余冷却时间。
        
        Args:
            resonance_result: ResonanceScorer计算的共振结果，必须包含:
                - alert_level (str): 预警级别
                - total_score (float): 总分
                - max_score (float): 满分
            current_time: 当前时间 (建议使用EST时区)
        
        Returns:
            dict: 包含以下字段:
                - should_alert (bool): 是否应该发送告警
                - alert_level (str): 告警级别
                - reason (str): 触发原因或跳过原因
                - cooldown_remaining (int): 剩余冷却时间 (分钟)
        
        Examples:
            >>> from signal_engine.resonance_scorer import ResonanceScorer
            >>> scorer = ResonanceScorer()
            >>> sm = SignalStateMachine(cooldown_minutes=30)
            >>> 
            >>> # 模拟共振结果
            >>> gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
            >>> vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
            >>> crypto = scorer.calculate_crypto_score(True, True, True, True)
            >>> darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
            >>> result = scorer.calculate_total_score(gex, vix, crypto, darkpool)
            >>> 
            >>> # 检查是否触发
            >>> now = datetime.now(pytz.timezone('US/Eastern'))
            >>> trigger = sm.check_and_trigger(result, now)
            >>> print(trigger['should_alert'])  # True (首次触发)
            >>> print(trigger['alert_level'])   # 'LEVEL_3'
        """
        try:
            alert_level = resonance_result.get('alert_level', 'NO_SIGNAL')
            
            # 无信号状态
            if alert_level == 'NO_SIGNAL':
                previous_state = self.current_state
                self.current_state = 'IDLE'
                
                if previous_state != 'IDLE':
                    logger.info("信号消失，状态机重置为IDLE")
                
                return {
                    'should_alert': False,
                    'alert_level': 'NO_SIGNAL',
                    'reason': '共振分数低于阈值,无需告警',
                    'cooldown_remaining': 0
                }
            
            # 检查冷却时间
            if self.last_alert_time:
                elapsed = (current_time - self.last_alert_time).total_seconds() / 60
                
                if elapsed < self.cooldown_minutes:
                    remaining = int(self.cooldown_minutes - elapsed)
                    self.current_state = 'COOLDOWN'
                    
                    logger.debug(
                        f"处于冷却期: 已过去{elapsed:.1f}分钟, "
                        f"剩余{remaining}分钟"
                    )
                    
                    return {
                        'should_alert': False,
                        'alert_level': alert_level,
                        'reason': f'处于冷却期,剩余{remaining}分钟',
                        'cooldown_remaining': remaining
                    }
            
            # 触发告警
            self.last_alert_time = current_time
            self.current_state = 'ALERT_TRIGGERED'
            
            # 记录历史
            alert_record = {
                'time': current_time,
                'level': alert_level,
                'score': resonance_result.get('total_score', 0.0),
                'max_score': resonance_result.get('max_score', 5.0)
            }
            self.alert_history.append(alert_record)
            
            # 保存状态
            self._save_state()
            
            logger.warning(
                f"🚨 告警触发! 级别: {alert_level}, "
                f"分数: {alert_record['score']}/{alert_record['max_score']}"
            )
            
            return {
                'should_alert': True,
                'alert_level': alert_level,
                'reason': (
                    f"共振分数{resonance_result['total_score']}/"
                    f"{resonance_result['max_score']},达到{alert_level}"
                ),
                'cooldown_remaining': 0
            }
            
        except Exception as e:
            logger.error(f"状态机检查异常: {str(e)}", exc_info=True)
            return {
                'should_alert': False,
                'alert_level': 'ERROR',
                'reason': f'状态机异常: {str(e)}',
                'cooldown_remaining': 0
            }
    
    def get_state_summary(self) -> Dict[str, any]:
        """获取状态机摘要
        
        返回当前状态机的完整状态信息，用于监控和调试。
        
        Returns:
            dict: 包含以下字段:
                - current_state (str): 当前状态
                - last_alert_time (datetime or None): 上次告警时间
                - total_alerts (int): 累计告警次数
                - recent_alerts (list): 最近5次告警记录
        
        Examples:
            >>> sm = SignalStateMachine()
            >>> summary = sm.get_state_summary()
            >>> print(summary['current_state'])  # 'IDLE'
            >>> print(summary['total_alerts'])   # 0
        """
        return {
            'current_state': self.current_state,
            'last_alert_time': self.last_alert_time,
            'total_alerts': len(self.alert_history),
            'recent_alerts': self.alert_history[-5:]  # 最近5次
        }
    
    def reset(self):
        """重置状态机
        
        清除所有状态和历史记录，恢复到初始IDLE状态。
        适用于系统重启或手动重置场景。
        
        Examples:
            >>> sm = SignalStateMachine()
            >>> sm.reset()
            >>> print(sm.current_state)  # 'IDLE'
            >>> print(sm.alert_history)  # []
        """
        self.last_alert_time = None
        self.current_state = 'IDLE'
        self.alert_history.clear()
        
        # 清除持久化文件
        try:
            state_file = Path(self.STATE_FILE)
            if state_file.exists():
                state_file.unlink()
                logger.info("Signal state file cleared")
        except Exception as e:
            logger.error(f"Failed to clear state file: {e}")
        
        logger.info("状态机已重置")
    
    def is_in_cooldown(self, current_time: datetime) -> bool:
        """检查当前是否处于冷却期
        
        Args:
            current_time: 当前时间
        
        Returns:
            bool: True表示处于冷却期，False表示可以触发新告警
        """
        if not self.last_alert_time:
            return False
        
        elapsed = (current_time - self.last_alert_time).total_seconds() / 60
        return elapsed < self.cooldown_minutes
    
    def get_cooldown_remaining(self, current_time: datetime) -> int:
        """获取剩余冷却时间
        
        Args:
            current_time: 当前时间
        
        Returns:
            int: 剩余冷却时间 (分钟)，如果不处于冷却期则返回0
        """
        if not self.last_alert_time:
            return 0
        
        elapsed = (current_time - self.last_alert_time).total_seconds() / 60
        
        if elapsed >= self.cooldown_minutes:
            return 0
        
        return int(self.cooldown_minutes - elapsed)


def format_alert_message(
    resonance_result: Dict[str, any],
    hawkes_result: Dict[str, any],
    current_time: datetime
) -> str:
    """格式化告警消息 (按PRD 4.2节模板)
    
    生成符合产品需求文档规范的告警文本，包含所有维度的详细信息
    和Hawkes Process测算结果。
    
    Args:
        resonance_result: 共振评分结果 (来自 ResonanceScorer.calculate_total_score)
        hawkes_result: Hawkes分支比结果 (来自 ResonanceScorer.estimate_hawkes_branching_ratio)
        current_time: 触发时间 (建议使用EST时区)
    
    Returns:
        str: 格式化的告警文本，可直接发送至邮件/Telegram等通知渠道
    
    Examples:
        >>> from signal_engine.resonance_scorer import ResonanceScorer
        >>> scorer = ResonanceScorer()
        >>> 
        >>> # 计算各维度评分
        >>> gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
        >>> vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
        >>> crypto = scorer.calculate_crypto_score(True, True, True, True)
        >>> darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
        >>> resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
        >>> 
        >>> # 计算Hawkes分支比
        >>> prices = [-0.5, -0.8, -1.2, -0.3, -0.6]
        >>> volumes = [1e6, 1.5e6, 2e6, 1.2e6, 1.8e6]
        >>> hawkes = scorer.estimate_hawkes_branching_ratio(prices, volumes)
        >>> 
        >>> # 格式化告警
        >>> now = datetime.now(pytz.timezone('US/Eastern'))
        >>> message = format_alert_message(resonance, hawkes, now)
        >>> print(message)
    """
    try:
        # 提取各维度详情
        dimension_scores = resonance_result.get('dimension_scores', {})
        gex_details = dimension_scores.get('gex', {}).get('details', 'N/A')
        vix_details = dimension_scores.get('vix', {}).get('details', 'N/A')
        darkpool_details = dimension_scores.get('darkpool', {}).get('details', 'N/A')
        crypto_details = dimension_scores.get('crypto', {}).get('details', 'N/A')
        
        # 构建告警消息
        msg = f"""
🚨 [SYSTEM ALERT] 流动性清算衰竭:多因子共振抄底信号触发
⏰ 触发时间:{current_time.strftime('%Y-%m-%d %H:%M:%S')} EST
当前共振得分:{resonance_result['total_score']} / {resonance_result['max_score']}({resonance_result['resonance_pct']}%)

📊 美股微观结构与价格行为
• 做市商GEX:{gex_details}
• VIX期限结构:{vix_details}

🏛️ 华尔街暗盘大资金追踪
• 暗盘吸筹:{darkpool_details}

🌐 加密金丝雀多源校验
• 杠杆清洗:{crypto_details}

🤖 系统量化提示
基于Hawkes Process测算,{hawkes_result['details']}

✅ 触发条件:
"""
        
        # 添加触发条件列表
        for condition in resonance_result.get('trigger_conditions', []):
            msg += f"  - {condition}\n"
        
        return msg.strip()
        
    except Exception as e:
        logger.error(f"告警消息格式化异常: {str(e)}", exc_info=True)
        return f"[ERROR] 告警消息生成失败: {str(e)}"


def convert_to_est(dt: datetime) -> datetime:
    """将任意时区的datetime转换为EST (美东时间)
    
    Args:
        dt: 输入的时间对象 (可以是任意时区)
    
    Returns:
        datetime: 转换后的EST时间
    
    Examples:
        >>> from datetime import datetime
        >>> utc_now = datetime.now(pytz.UTC)
        >>> est_time = convert_to_est(utc_now)
        >>> print(est_time.tzinfo)  # US/Eastern
    """
    eastern = pytz.timezone('US/Eastern')
    
    # 如果输入时间没有时区信息，假设为UTC
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    
    return dt.astimezone(eastern)
