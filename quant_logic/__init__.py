"""
多源共振监控系统 - 量化逻辑模块

该模块实现核心量化计算逻辑,包括:
- DIX/GEX指标计算
- 暗盘与GEX背离检测
- 流动性微观结构分析
- 统计显著性检验
- Gamma敞口(GEX)计算引擎
- VIX期限结构分析器
- 加密杠杆清洗判定引擎
- 暗盘"三驾马车"验证引擎

主要类:
    GEXCalculator: Gamma敞口计算引擎
    VIXAnalyzer: VIX期限结构分析器
    CryptoLeverageCleaner: 加密杠杆清洗判定引擎
    DarkPoolVerifier: 暗盘机构资金验证引擎
"""

# 导出核心类
from quant_logic.gex_calculator import GEXCalculator, calculate_single_option_gex
from quant_logic.vix_analyzer import VIXAnalyzer, quick_vix_analysis
from quant_logic.crypto_leverage_cleaner import CryptoLeverageCleaner, quick_leverage_check
from quant_logic.darkpool_verifier import DarkPoolVerifier, quick_darkpool_check
from quant_logic.darkpool_preprocessor import DarkPoolPreprocessor, quick_preprocess

__all__ = [
    'GEXCalculator',
    'calculate_single_option_gex',
    'VIXAnalyzer',
    'quick_vix_analysis',
    'CryptoLeverageCleaner',
    'quick_leverage_check',
    'DarkPoolVerifier',
    'quick_darkpool_check',
    'DarkPoolPreprocessor',
    'quick_preprocess',
]
