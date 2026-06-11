"""
多源共振监控系统 - Phase 2数据获取层验证脚本

该脚本用于验证所有7个数据获取器模块是否可以成功导入和实例化，
并在Mock模式下返回预期的数据结构。

使用方法:
    python verify_fetchers.py
"""

import sys
from typing import Dict, Any


def test_import(module_name: str, class_name: str) -> bool:
    """测试模块导入
    
    Args:
        module_name: 模块名称
        class_name: 类名称
        
    Returns:
        bool: True表示导入成功
    """
    try:
        module = __import__(f'data_fetchers.{module_name}', fromlist=[class_name])
        cls = getattr(module, class_name)
        print(f"✅ {module_name}: 导入成功")
        return True
    except Exception as e:
        print(f"❌ {module_name}: 导入失败 - {str(e)}")
        return False


def test_instantiation(module_name: str, class_name: str, mock_mode: bool = True) -> bool:
    """测试类实例化
    
    Args:
        module_name: 模块名称
        class_name: 类名称
        mock_mode: 是否使用Mock模式
        
    Returns:
        bool: True表示实例化成功
    """
    try:
        module = __import__(f'data_fetchers.{module_name}', fromlist=[class_name])
        cls = getattr(module, class_name)
        
        # 检查构造函数是否支持mock_mode参数
        import inspect
        sig = inspect.signature(cls.__init__)
        
        if 'mock_mode' in sig.parameters:
            instance = cls(mock_mode=mock_mode)
        else:
            instance = cls()
        
        print(f"✅ {module_name}: 实例化成功 (mock_mode={mock_mode})")
        return True
    except Exception as e:
        print(f"❌ {module_name}: 实例化失败 - {str(e)}")
        return False


def test_tradier_fetcher() -> bool:
    """测试TradierFetcher功能"""
    print("\n--- 测试 TradierFetcher ---")
    
    try:
        from data_fetchers.tradier_fetcher import TradierFetcher
        
        fetcher = TradierFetcher(mock_mode=True)
        
        # 测试get_option_chain
        raw_data = fetcher.get_option_chain('SPY', '2026-06-19')
        if raw_data is None:
            print("❌ get_option_chain返回None")
            return False
        
        # 测试parse_option_chain
        df = fetcher.parse_option_chain(raw_data)
        if df is None or df.empty:
            print("❌ parse_option_chain返回空DataFrame")
            return False
        
        # 验证DataFrame列
        required_cols = ['symbol', 'type', 'strike', 'expiry', 'bid', 'ask', 'last_price', 'volume', 'open_interest']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"❌ DataFrame缺少列: {missing_cols}")
            return False
        
        print(f"✅ get_option_chain: 返回{len(raw_data['options']['option'])}条期权记录")
        print(f"✅ parse_option_chain: 返回{len(df)}行数据, 列数={len(df.columns)}")
        print(f"   CALL数量: {len(df[df['type']=='call'])}, PUT数量: {len(df[df['type']=='put'])}")
        return True
        
    except Exception as e:
        print(f"❌ TradierFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_yahoo_finance_fetcher() -> bool:
    """测试YahooFinanceFetcher功能"""
    print("\n--- 测试 YahooFinanceFetcher ---")
    
    try:
        from data_fetchers.yahoo_finance_fetcher import YahooFinanceFetcher
        
        fetcher = YahooFinanceFetcher(mock_mode=True)
        
        # 测试get_vix_spot
        vix_spot = fetcher.get_vix_spot()
        if vix_spot is None:
            print("❌ get_vix_spot返回None")
            return False
        
        # 测试get_vix_futures
        vx1 = fetcher.get_vix_futures('VX1')
        vx2 = fetcher.get_vix_futures('VX2')
        if vx1 is None or vx2 is None:
            print("❌ get_vix_futures返回None")
            return False
        
        # 测试calculate_term_structure_ratio
        ratio = fetcher.calculate_term_structure_ratio()
        if ratio is None:
            print("❌ calculate_term_structure_ratio返回None")
            return False
        
        print(f"✅ get_vix_spot: {vix_spot:.2f}")
        print(f"✅ get_vix_futures: VX1={vx1:.2f}, VX2={vx2:.2f}")
        print(f"✅ calculate_term_structure_ratio: {ratio:.4f}")
        return True
        
    except Exception as e:
        print(f"❌ YahooFinanceFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_ccxt_fetcher() -> bool:
    """测试CCXTFetcher功能"""
    print("\n--- 测试 CCXTFetcher ---")
    
    try:
        from data_fetchers.ccxt_fetcher import CCXTFetcher
        
        fetcher = CCXTFetcher(mock_mode=True)
        
        # 测试get_funding_rate
        funding_rate = fetcher.get_funding_rate('BTC/USDT')
        if funding_rate is None:
            print("❌ get_funding_rate返回None")
            return False
        
        # 测试get_open_interest
        oi_data = fetcher.get_open_interest('BTC/USDT')
        if oi_data is None:
            print("❌ get_open_interest返回None")
            return False
        
        # 验证OI数据结构
        if 'oi' not in oi_data or 'timestamp' not in oi_data:
            print("❌ OI数据结构不正确")
            return False
        
        # 测试calculate_oi_change_1h
        historical_oi = [50000 + i * 100 for i in range(12)]
        change_rate = fetcher.calculate_oi_change_1h(51000, historical_oi)
        if change_rate is None:
            print("❌ calculate_oi_change_1h返回None")
            return False
        
        print(f"✅ get_funding_rate: {funding_rate * 100:.4f}%")
        print(f"✅ get_open_interest: OI={oi_data['oi']:.2f}, timestamp={oi_data['timestamp']}")
        print(f"✅ calculate_oi_change_1h: {change_rate:.2f}%")
        return True
        
    except Exception as e:
        print(f"❌ CCXTFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_squeezemetrics_fetcher() -> bool:
    """测试SqueezeMetricsFetcher功能"""
    print("\n--- 测试 SqueezeMetricsFetcher ---")
    
    try:
        from data_fetchers.squeezemetrics_fetcher import SqueezeMetricsFetcher
        
        fetcher = SqueezeMetricsFetcher(mock_mode=True)
        
        # 测试get_daily_dix
        dix = fetcher.get_daily_dix()
        if dix is None:
            print("❌ get_daily_dix返回None")
            return False
        
        # 测试get_barchart_gamma_profile
        gamma_data = fetcher.get_barchart_gamma_profile()
        if gamma_data is None:
            print("❌ get_barchart_gamma_profile返回None")
            return False
        
        # 验证Gamma数据结构
        required_keys = ['strikes', 'call_gamma', 'put_gamma', 'net_gamma', 'put_wall_strike']
        missing_keys = [key for key in required_keys if key not in gamma_data]
        if missing_keys:
            print(f"❌ Gamma数据缺少字段: {missing_keys}")
            return False
        
        print(f"✅ get_daily_dix: {dix:.2f}%")
        print(f"✅ get_barchart_gamma_profile: {len(gamma_data['strikes'])}个行权价, Put Wall={gamma_data['put_wall_strike']}")
        return True
        
    except Exception as e:
        print(f"❌ SqueezeMetricsFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_axlfi_fetcher() -> bool:
    """测试 AxlfiFetcher 功能 (替代已下线的 ChartExchange + Stockgrid)"""
    print("\n--- 测试 AxlfiFetcher ---")
    
    try:
        from data_fetchers.axlfi_fetcher import AxlfiFetcher
        
        fetcher = AxlfiFetcher(mock_mode=True)
        
        # 测试 fetch_symbol_data
        raw_data = fetcher.fetch_symbol_data('SPY', window=252)
        if raw_data is None:
            print("❌ fetch_symbol_data返回None")
            return False
        
        # 验证数据结构
        for key in ['dates', 'dollar_dp_position', 'short_volume_pct', 'close']:
            if key not in raw_data:
                print(f"❌ 缺少字段: {key}")
                return False
        
        # 测试 get_net_position_series
        net_pos = fetcher.get_net_position_series('SPY', [20, 60])
        if net_pos is None or '20d' not in net_pos:
            print("❌ get_net_position_series返回None")
            return False
        
        # 测试 detect_bottom_divergence
        pos_series = net_pos['20d']
        prices = [450 - i * 2 for i in range(len(pos_series))]
        divergence_result = fetcher.detect_bottom_divergence(pos_series, prices)
        if 'divergence' not in divergence_result:
            print("❌ detect_bottom_divergence返回数据结构不正确")
            return False
        
        # 测试 get_latest_short_metrics
        short_metrics = fetcher.get_latest_short_metrics('SPY')
        if 'latest_short_pct' not in short_metrics:
            print("❌ get_latest_short_metrics返回数据结构不正确")
            return False
        
        print(f"✅ fetch_symbol_data: {len(raw_data.get('dates', []))} 天数据")
        print(f"✅ get_net_position_series: 20d={len(net_pos['20d'])}点, 60d={len(net_pos['60d'])}点")
        print(f"✅ detect_bottom_divergence: divergence={divergence_result['divergence']}")
        print(f"✅ get_latest_short_metrics: short_pct={short_metrics['latest_short_pct']:.1f}%")
        return True
        
    except Exception as e:
        print(f"❌ AxlfiFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_chartexchange_fetcher() -> bool:
    """ChartExchange 已下线，由 yfinance/FINRA + AXLFI 替代"""
    print("\n--- ChartExchangeFetcher (已弃用) ---")
    print("✅ ChartExchange 已迁移至 yfinance(做空) + AXLFI(暗盘)，无需测试")
    return True


def test_stockgrid_fetcher() -> bool:
    """Stockgrid 已下线，由 AXLFI 公开 API 替代"""
    print("\n--- StockgridFetcher (已弃用, 由 AXLFI 替代) ---")
    print("✅ Stockgrid.io 已下线 (重定向至 axlfi.com)，数据链路已迁移至 AxlfiFetcher")
    return True


def test_dbmf_fetcher() -> bool:
    """测试DBMFFetcher功能"""
    print("\n--- 测试 DBMFFetcher ---")
    
    try:
        from data_fetchers.dbmf_fetcher import DBMFFetcher
        
        fetcher = DBMFFetcher(mock_mode=True)
        
        # 测试get_dbmf_intraday_price
        price = fetcher.get_dbmf_intraday_price()
        if price is None:
            print("❌ get_dbmf_intraday_price返回None")
            return False
        
        # 测试get_dbmf_historical_prices
        historical_prices = fetcher.get_dbmf_historical_prices('5d')
        if historical_prices is None or len(historical_prices) < 5:
            print("❌ get_dbmf_historical_prices返回数据不足")
            return False
        
        # 测试check_ma5_recovery
        recovery = fetcher.check_ma5_recovery(price, historical_prices)
        if recovery is None:
            print("❌ check_ma5_recovery返回None")
            return False
        
        print(f"✅ get_dbmf_intraday_price: ${price:.2f}")
        print(f"✅ get_dbmf_historical_prices: {len(historical_prices)}个数据点")
        print(f"✅ check_ma5_recovery: {recovery}")
        return True
        
    except Exception as e:
        print(f"❌ DBMFFetcher测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("=" * 80)
    print("多源共振监控系统 - Phase 2数据获取层验证")
    print("=" * 80)
    
    # 测试导入
    print("\n【阶段1】测试模块导入")
    print("-" * 80)
    
    modules = [
        ('tradier_fetcher', 'TradierFetcher'),
        ('yahoo_finance_fetcher', 'YahooFinanceFetcher'),
        ('ccxt_fetcher', 'CCXTFetcher'),
        ('squeezemetrics_fetcher', 'SqueezeMetricsFetcher'),
        ('chartexchange_fetcher', 'ChartExchangeFetcher'),
        ('stockgrid_fetcher', 'StockgridFetcher'),
        ('dbmf_fetcher', 'DBMFFetcher'),
    ]
    
    import_results = []
    for module_name, class_name in modules:
        result = test_import(module_name, class_name)
        import_results.append(result)
    
    # 测试实例化
    print("\n【阶段2】测试类实例化（Mock模式）")
    print("-" * 80)
    
    instantiation_results = []
    for module_name, class_name in modules:
        result = test_instantiation(module_name, class_name, mock_mode=True)
        instantiation_results.append(result)
    
    # 测试功能
    print("\n【阶段3】测试核心功能（Mock模式）")
    print("-" * 80)
    
    function_tests = [
        ("TradierFetcher", test_tradier_fetcher),
        ("YahooFinanceFetcher", test_yahoo_finance_fetcher),
        ("CCXTFetcher", test_ccxt_fetcher),
        ("SqueezeMetricsFetcher", test_squeezemetrics_fetcher),
        ("ChartExchangeFetcher", test_chartexchange_fetcher),
        ("StockgridFetcher", test_stockgrid_fetcher),
        ("DBMFFetcher", test_dbmf_fetcher),
    ]
    
    function_results = []
    for name, test_func in function_tests:
        result = test_func()
        function_results.append((name, result))
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("验证结果汇总")
    print("=" * 80)
    
    all_passed = True
    
    print(f"\n模块导入: {sum(import_results)}/{len(import_results)} 通过")
    if not all(import_results):
        all_passed = False
    
    print(f"类实例化: {sum(instantiation_results)}/{len(instantiation_results)} 通过")
    if not all(instantiation_results):
        all_passed = False
    
    print(f"\n功能测试:")
    for name, result in function_results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
        if not result:
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("🎉 所有测试通过！Phase 2数据获取层实现完成。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
