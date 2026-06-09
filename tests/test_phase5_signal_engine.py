"""
多源共振监控系统 - Phase 5 信号引擎测试用例

该模块测试 ResonanceScorer 和 SignalStateMachine 的核心功能，包括：
- 各维度评分逻辑正确性
- 总分计算与预警分级
- Hawkes Process 分支比测算
- 状态机冷却机制
- 告警消息格式化
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pytz

from signal_engine.resonance_scorer import ResonanceScorer
from signal_engine.signal_trigger import SignalStateMachine, format_alert_message


class TestResonanceScorer(unittest.TestCase):
    """测试共振矩阵评分系统"""
    
    def setUp(self):
        """每个测试前初始化评分器"""
        self.scorer = ResonanceScorer()
    
    # ==================== GEX 维度测试 ====================
    
    def test_gex_score_positive(self):
        """测试GEX翻正情况 (1.5分)"""
        result = self.scorer.calculate_gex_score(
            gex_local=-5e6,
            gex_calibrated=2e6,
            flip_zone_crossed=True,
            gex_trend='IMPROVING'
        )
        
        self.assertEqual(result['score'], 1.5)
        self.assertEqual(result['state'], 'POSITIVE')
        self.assertIn('翻正', result['details'])
    
    def test_gex_score_converging(self):
        """测试GEX收敛情况 (0.75分)"""
        result = self.scorer.calculate_gex_score(
            gex_local=-3e6,
            gex_calibrated=-2e6,
            flip_zone_crossed=False,
            gex_trend='IMPROVING'
        )
        
        self.assertEqual(result['score'], 0.75)
        self.assertEqual(result['state'], 'CONVERGING')
        self.assertIn('收敛', result['details'])
    
    def test_gex_score_negative(self):
        """测试GEX恶化情况 (0分)"""
        result = self.scorer.calculate_gex_score(
            gex_local=-8e6,
            gex_calibrated=-10e6,
            flip_zone_crossed=False,
            gex_trend='DETERIORATING'
        )
        
        self.assertEqual(result['score'], 0.0)
        self.assertEqual(result['state'], 'NEGATIVE')
    
    # ==================== VIX 维度测试 ====================
    
    def test_vix_score_backwardation(self):
        """测试VIX Backwardation情况 (0.5分)"""
        result = self.scorer.calculate_vix_score(
            term_structure_ratio=1.20,
            slope_direction='UP',
            panic_premium=15.5
        )
        
        self.assertEqual(result['score'], 0.5)
        self.assertEqual(result['state'], 'BACKWARDATION')
        self.assertIn('Backwardation', result['details'])
    
    def test_vix_score_contango(self):
        """测试VIX Contango情况 (1.0分)"""
        result = self.scorer.calculate_vix_score(
            term_structure_ratio=0.95,
            slope_direction='DOWN',
            panic_premium=2.3
        )
        
        self.assertEqual(result['score'], 1.0)
        self.assertEqual(result['state'], 'CONTANGO')
        self.assertIn('Contango', result['details'])
    
    def test_vix_score_neutral(self):
        """测试VIX中性情况 (0分)"""
        result = self.scorer.calculate_vix_score(
            term_structure_ratio=1.05,
            slope_direction='UP',
            panic_premium=5.0
        )
        
        self.assertEqual(result['score'], 0.0)
        self.assertEqual(result['state'], 'NEUTRAL')
    
    # ==================== 加密维度测试 ====================
    
    def test_crypto_score_cleanup_complete(self):
        """测试加密去杠杆完成 (1.0分)"""
        result = self.scorer.calculate_crypto_score(
            oi_crash=True,
            funding_positive=True,
            elr_safe=True,
            leverage_cleanup_confirmed=True
        )
        
        self.assertEqual(result['score'], 1.0)
        self.assertEqual(result['state'], 'CLEANUP_COMPLETE')
        self.assertIn('去杠杆完成', result['details'])
    
    def test_crypto_score_in_progress(self):
        """测试加密清算进行中 (0.5分)"""
        result = self.scorer.calculate_crypto_score(
            oi_crash=True,
            funding_positive=False,
            elr_safe=False,
            leverage_cleanup_confirmed=False
        )
        
        self.assertEqual(result['score'], 0.5)
        self.assertEqual(result['state'], 'IN_PROGRESS')
    
    def test_crypto_score_high_leverage(self):
        """测试高杠杆状态 (0分)"""
        result = self.scorer.calculate_crypto_score(
            oi_crash=False,
            funding_positive=False,
            elr_safe=False,
            leverage_cleanup_confirmed=False
        )
        
        self.assertEqual(result['score'], 0.0)
        self.assertEqual(result['state'], 'HIGH_LEVERAGE')
    
    # ==================== 暗盘维度测试 ====================
    
    def test_darkpool_score_strong(self):
        """测试暗盘强吸筹 (1.5分)"""
        result = self.scorer.calculate_darkpool_score(
            dix_flag=True,
            short_ratio_flag=True,
            stockgrid_flag=False,
            dbmf_recovery=True,
            aggregated_signal=True
        )
        
        self.assertEqual(result['score'], 1.5)
        self.assertEqual(result['state'], 'STRONG_ACCUMULATION')
        self.assertIn('强吸筹', result['details'])
    
    def test_darkpool_score_moderate(self):
        """测试暗盘中度吸筹 (0.75分)"""
        result = self.scorer.calculate_darkpool_score(
            dix_flag=True,
            short_ratio_flag=True,
            stockgrid_flag=False,
            dbmf_recovery=False,
            aggregated_signal=True
        )
        
        self.assertEqual(result['score'], 0.75)
        self.assertEqual(result['state'], 'MODERATE')
    
    def test_darkpool_score_weak(self):
        """测试暗盘信号微弱 (0分)"""
        result = self.scorer.calculate_darkpool_score(
            dix_flag=False,
            short_ratio_flag=False,
            stockgrid_flag=False,
            dbmf_recovery=False,
            aggregated_signal=False
        )
        
        self.assertEqual(result['score'], 0.0)
        self.assertEqual(result['state'], 'WEAK')
    
    # ==================== 总分与预警分级测试 ====================
    
    def test_total_score_level_3(self):
        """测试LEVEL 3预警 (总分 >= 3.5)"""
        gex = {'score': 1.5, 'state': 'POSITIVE', 'details': 'test'}
        vix = {'score': 1.0, 'state': 'CONTANGO', 'details': 'test'}
        crypto = {'score': 1.0, 'state': 'CLEANUP_COMPLETE', 'details': 'test'}
        darkpool = {'score': 1.5, 'state': 'STRONG_ACCUMULATION', 'details': 'test'}
        
        result = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        self.assertEqual(result['total_score'], 5.0)
        self.assertEqual(result['alert_level'], 'LEVEL_3')
        self.assertEqual(result['resonance_pct'], 100.0)
        self.assertEqual(len(result['trigger_conditions']), 4)
    
    def test_total_score_level_2(self):
        """测试LEVEL 2预警 (3.0 <= 总分 < 3.5)"""
        gex = {'score': 1.5, 'state': 'POSITIVE', 'details': 'test'}
        vix = {'score': 0.5, 'state': 'BACKWARDATION', 'details': 'test'}
        crypto = {'score': 0.5, 'state': 'IN_PROGRESS', 'details': 'test'}
        darkpool = {'score': 0.75, 'state': 'MODERATE', 'details': 'test'}
        
        result = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        self.assertAlmostEqual(result['total_score'], 3.25, places=2)
        self.assertEqual(result['alert_level'], 'LEVEL_2')
    
    def test_total_score_level_1(self):
        """测试LEVEL 1预警 (2.0 <= 总分 < 3.0)"""
        gex = {'score': 0.75, 'state': 'CONVERGING', 'details': 'test'}
        vix = {'score': 0.5, 'state': 'BACKWARDATION', 'details': 'test'}
        crypto = {'score': 0.5, 'state': 'IN_PROGRESS', 'details': 'test'}
        darkpool = {'score': 0.75, 'state': 'MODERATE', 'details': 'test'}
        
        result = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        self.assertAlmostEqual(result['total_score'], 2.5, places=2)
        self.assertEqual(result['alert_level'], 'LEVEL_1')
    
    def test_total_score_no_signal(self):
        """测试无信号 (总分 < 2.0)"""
        gex = {'score': 0.0, 'state': 'NEGATIVE', 'details': 'test'}
        vix = {'score': 0.0, 'state': 'NEUTRAL', 'details': 'test'}
        crypto = {'score': 0.0, 'state': 'HIGH_LEVERAGE', 'details': 'test'}
        darkpool = {'score': 0.0, 'state': 'WEAK', 'details': 'test'}
        
        result = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        self.assertEqual(result['total_score'], 0.0)
        self.assertEqual(result['alert_level'], 'NO_SIGNAL')
        self.assertEqual(len(result['trigger_conditions']), 0)
    
    # ==================== Hawkes Process 测试 ====================
    
    def test_hawkes_insufficient_data(self):
        """测试数据不足情况"""
        result = self.scorer.estimate_hawkes_branching_ratio(
            recent_price_changes=[-0.5, -0.8],
            recent_volumes=[1e6, 1.5e6]
        )
        
        self.assertEqual(result['state'], 'INSUFFICIENT_DATA')
        self.assertEqual(result['branching_ratio'], 0.5)
    
    def test_hawkes_subcritical(self):
        """测试亚临界状态 (分支比 < 0.7)"""
        # 价格下跌与成交量相关性较低
        prices = [-0.5, -0.3, -0.2, -0.4, -0.1, -0.3, -0.2, -0.5, -0.1, -0.2]
        volumes = [1e6, 1.1e6, 1.05e6, 1.2e6, 1.0e6, 1.15e6, 1.08e6, 1.25e6, 1.02e6, 1.1e6]
        
        result = self.scorer.estimate_hawkes_branching_ratio(prices, volumes)
        
        self.assertIn(result['state'], ['SUBCRITICAL', 'CRITICAL'])
        self.assertGreaterEqual(result['branching_ratio'], 0.0)
        self.assertLessEqual(result['branching_ratio'], 1.0)
    
    def test_hawkes_with_real_data(self):
        """测试真实场景数据"""
        # 模拟恐慌抛售: 价格大幅下跌伴随成交量激增
        prices = [-1.5, -2.0, -1.8, -2.5, -1.2, -1.9, -2.3, -1.7, -2.1, -1.6]
        volumes = [2e6, 3e6, 2.8e6, 3.5e6, 2.2e6, 3.2e6, 3.8e6, 2.9e6, 3.3e6, 2.7e6]
        
        result = self.scorer.estimate_hawkes_branching_ratio(prices, volumes)
        
        self.assertIn(result['state'], ['SUBCRITICAL', 'CRITICAL', 'SUPERCRITICAL'])
        self.assertGreater(result['self_excitation_intensity'], 0.0)


class TestSignalStateMachine(unittest.TestCase):
    """测试信号触发状态机"""
    
    def setUp(self):
        """每个测试前初始化状态机"""
        self.sm = SignalStateMachine(cooldown_minutes=30)
        self.eastern = pytz.timezone('US/Eastern')
    
    def create_resonance_result(self, alert_level='LEVEL_3', total_score=4.5):
        """创建模拟共振结果"""
        return {
            'alert_level': alert_level,
            'total_score': total_score,
            'max_score': 5.0,
            'resonance_pct': 90.0,
            'dimension_scores': {},
            'trigger_conditions': ['test condition']
        }
    
    def test_initial_state(self):
        """测试初始状态为IDLE"""
        self.assertEqual(self.sm.current_state, 'IDLE')
        self.assertIsNone(self.sm.last_alert_time)
        self.assertEqual(len(self.sm.alert_history), 0)
    
    def test_first_alert_trigger(self):
        """测试首次告警触发"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        trigger = self.sm.check_and_trigger(result, now)
        
        self.assertTrue(trigger['should_alert'])
        self.assertEqual(trigger['alert_level'], 'LEVEL_3')
        self.assertEqual(self.sm.current_state, 'ALERT_TRIGGERED')
        self.assertEqual(len(self.sm.alert_history), 1)
    
    def test_cooldown_mechanism(self):
        """测试冷却机制"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 第一次触发
        trigger1 = self.sm.check_and_trigger(result, now)
        self.assertTrue(trigger1['should_alert'])
        
        # 5分钟后再次检查 (应处于冷却期)
        later = now + timedelta(minutes=5)
        trigger2 = self.sm.check_and_trigger(result, later)
        
        self.assertFalse(trigger2['should_alert'])
        self.assertIn('冷却期', trigger2['reason'])
        self.assertGreater(trigger2['cooldown_remaining'], 0)
    
    def test_cooldown_expiry(self):
        """测试冷却期结束"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 第一次触发
        self.sm.check_and_trigger(result, now)
        
        # 35分钟后 (超过30分钟冷却期)
        later = now + timedelta(minutes=35)
        trigger = self.sm.check_and_trigger(result, later)
        
        self.assertTrue(trigger['should_alert'])
        self.assertEqual(trigger['cooldown_remaining'], 0)
    
    def test_no_signal_state(self):
        """测试无信号状态"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result(alert_level='NO_SIGNAL', total_score=0.0)
        
        trigger = self.sm.check_and_trigger(result, now)
        
        self.assertFalse(trigger['should_alert'])
        self.assertEqual(trigger['alert_level'], 'NO_SIGNAL')
        self.assertEqual(self.sm.current_state, 'IDLE')
    
    def test_state_summary(self):
        """测试状态摘要"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 触发一次告警
        self.sm.check_and_trigger(result, now)
        
        summary = self.sm.get_state_summary()
        
        self.assertEqual(summary['current_state'], 'ALERT_TRIGGERED')
        self.assertEqual(summary['total_alerts'], 1)
        self.assertEqual(len(summary['recent_alerts']), 1)
    
    def test_reset(self):
        """测试重置功能"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 触发告警
        self.sm.check_and_trigger(result, now)
        
        # 重置
        self.sm.reset()
        
        self.assertEqual(self.sm.current_state, 'IDLE')
        self.assertIsNone(self.sm.last_alert_time)
        self.assertEqual(len(self.sm.alert_history), 0)
    
    def test_is_in_cooldown(self):
        """测试冷却期检查"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 未触发时不应在冷却期
        self.assertFalse(self.sm.is_in_cooldown(now))
        
        # 触发后应在冷却期
        self.sm.check_and_trigger(result, now)
        self.assertTrue(self.sm.is_in_cooldown(now + timedelta(minutes=5)))
        
        # 冷却期结束后不应在冷却期
        self.assertFalse(self.sm.is_in_cooldown(now + timedelta(minutes=35)))
    
    def test_get_cooldown_remaining(self):
        """测试获取剩余冷却时间"""
        now = datetime.now(self.eastern)
        result = self.create_resonance_result()
        
        # 未触发时剩余时间为0
        self.assertEqual(self.sm.get_cooldown_remaining(now), 0)
        
        # 触发后应有剩余时间
        self.sm.check_and_trigger(result, now)
        remaining = self.sm.get_cooldown_remaining(now + timedelta(minutes=10))
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 30)


class TestFormatAlertMessage(unittest.TestCase):
    """测试告警消息格式化"""
    
    def setUp(self):
        """每个测试前初始化评分器"""
        self.scorer = ResonanceScorer()
        self.eastern = pytz.timezone('US/Eastern')
    
    def test_format_basic_message(self):
        """测试基本告警消息格式"""
        # 准备共振结果
        gex = self.scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
        vix = self.scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
        crypto = self.scorer.calculate_crypto_score(True, True, True, True)
        darkpool = self.scorer.calculate_darkpool_score(True, True, False, True, True)
        resonance = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        # 准备Hawkes结果
        prices = [-0.5, -0.8, -1.2, -0.3, -0.6]
        volumes = [1e6, 1.5e6, 2e6, 1.2e6, 1.8e6]
        hawkes = self.scorer.estimate_hawkes_branching_ratio(prices, volumes)
        
        # 格式化消息
        now = datetime.now(self.eastern)
        message = format_alert_message(resonance, hawkes, now)
        
        # 验证消息内容
        self.assertIn('🚨 [SYSTEM ALERT]', message)
        self.assertIn('流动性清算衰竭', message)
        self.assertIn('多因子共振抄底信号触发', message)
        self.assertIn('做市商GEX:', message)
        self.assertIn('VIX期限结构:', message)
        self.assertIn('暗盘吸筹:', message)
        self.assertIn('杠杆清洗:', message)
        self.assertIn('Hawkes Process', message)
        self.assertIn('✅ 触发条件:', message)
    
    def test_format_message_with_all_dimensions(self):
        """测试包含所有维度的完整消息"""
        gex = self.scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
        vix = self.scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
        crypto = self.scorer.calculate_crypto_score(True, True, True, True)
        darkpool = self.scorer.calculate_darkpool_score(True, True, False, True, True)
        resonance = self.scorer.calculate_total_score(gex, vix, crypto, darkpool)
        
        hawkes = {
            'branching_ratio': 0.65,
            'state': 'SUBCRITICAL',
            'self_excitation_intensity': 65.0,
            'details': '分支比0.65<0.7,自激抛售进入亚临界衰竭区间'
        }
        
        now = datetime.now(self.eastern)
        message = format_alert_message(resonance, hawkes, now)
        
        # 验证所有维度都有显示
        self.assertIn('GEX已翻正', message)
        self.assertIn('VIX回归Contango', message)
        self.assertIn('去杠杆完成', message)
        self.assertIn('暗盘强吸筹确认', message)
        self.assertIn('亚临界衰竭', message)
    
    def test_format_error_handling(self):
        """测试异常情况下的错误处理"""
        invalid_resonance = {}
        invalid_hawkes = {}
        now = datetime.now(self.eastern)
        
        message = format_alert_message(invalid_resonance, invalid_hawkes, now)
        
        # 应返回错误消息而非崩溃
        self.assertIn('ERROR', message)


if __name__ == '__main__':
    # 配置日志以便查看测试输出
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行测试
    unittest.main(verbosity=2)
