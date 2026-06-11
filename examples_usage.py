"""
多源共振监控系统 - Phase 2 数据获取层使用示例

本文件展示如何使用7个数据获取器模块，包括Mock模式和真实API模式。
"""

# ==================== 示例1: Tradier期权链数据获取 ====================
def example_tradier_fetcher():
    """Tradier期权链数据获取示例"""
    from data_fetchers import create_tradier_fetcher
    
    # Mock模式（测试用）
    fetcher = create_tradier_fetcher(mock_mode=True)
    
    # 获取期权链原始数据
    raw_data = fetcher.get_option_chain('SPY', '2026-06-19')
    if raw_data:
        print(f"获取到 {len(raw_data['options']['option'])} 条期权记录")
    
    # 解析为标准DataFrame
    df = fetcher.parse_option_chain(raw_data)
    if df is not None and not df.empty:
        print(f"DataFrame形状: {df.shape}")
        print(f"CALL数量: {len(df[df['type']=='call'])}")
        print(f"PUT数量: {len(df[df['type']=='put'])}")
        print(f"\n前5行数据:\n{df[['symbol', 'type', 'strike', 'volume']].head()}")


# ==================== 示例2: Yahoo Finance VIX期货 ====================
def example_yahoo_finance_fetcher():
    """Yahoo Finance VIX期货数据获取示例"""
    from data_fetchers import create_yahoo_finance_fetcher
    
    fetcher = create_yahoo_finance_fetcher(mock_mode=True)
    
    # 获取VIX现货价格
    vix_spot = fetcher.get_vix_spot()
    if vix_spot:
        print(f"VIX现货价格: {vix_spot:.2f}")
    
    # 获取VIX期货价格
    vx1 = fetcher.get_vix_futures('VX1')
    vx2 = fetcher.get_vix_futures('VX2')
    if vx1 and vx2:
        print(f"VX1近月期货: {vx1:.2f}")
        print(f"VX2次月期货: {vx2:.2f}")
    
    # 计算期限结构比率
    ratio = fetcher.calculate_term_structure_ratio()
    if ratio:
        state = "Backwardation" if ratio > 1.0 else "Contango"
        print(f"期限结构比率: {ratio:.4f} ({state})")


# ==================== 示例3: CCXT加密数据获取 ====================
def example_ccxt_fetcher():
    """CCXT加密数据获取示例"""
    from data_fetchers import create_ccxt_fetcher
    
    fetcher = create_ccxt_fetcher(mock_mode=True)
    
    # 获取资金费率
    funding_rate = fetcher.get_funding_rate('BTC/USDT')
    if funding_rate is not None:
        print(f"BTC资金费率: {funding_rate * 100:.4f}%")
        if funding_rate < -0.0001:
            print("⚠️ 检测到负费率，市场看跌情绪浓厚")
    
    # 获取持仓量
    oi_data = fetcher.get_open_interest('BTC/USDT')
    if oi_data:
        print(f"BTC持仓量: {oi_data['oi']:.2f}")
        print(f"时间戳: {oi_data['timestamp']}")
    
    # 计算OI变化率
    historical_oi = [50000 + i * 100 for i in range(12)]
    change_rate = fetcher.calculate_oi_change_1h(51000, historical_oi)
    if change_rate is not None:
        print(f"1小时OI变化率: {change_rate:.2f}%")
        if change_rate < -15:
            print("⚠️ OI断崖式下跌，疑似大规模清算")


# ==================== 示例4: SqueezeMetrics DIX获取 ====================
def example_squeezemetrics_fetcher():
    """SqueezeMetrics DIX数据获取示例"""
    from data_fetchers import create_squeezemetrics_fetcher
    
    fetcher = create_squeezemetrics_fetcher(mock_mode=True)
    
    # 获取DIX指标
    dix = fetcher.get_daily_dix()
    if dix is not None:
        print(f"DIX指标: {dix:.2f}%")
        if dix > 45.0:
            print("⚠️ DIX超过阈值，机构暗盘吸筹信号触发")
    
    # 获取Gamma分布
    gamma_data = fetcher.get_barchart_gamma_profile()
    if gamma_data:
        print(f"行权价数量: {len(gamma_data['strikes'])}")
        print(f"Put Wall位置: {gamma_data['put_wall_strike']}")
        total_gamma = sum(gamma_data['net_gamma'])
        print(f"总Gamma敞口: ${total_gamma:,.0f}")


# ==================== 示例5: AXLFI暗盘净头寸 (替代 ChartExchange + Stockgrid) ====================
def example_axlfi_fetcher():
    """AXLFI 暗盘净头寸 + 做空数据获取示例
    
    替代已下线的 ChartExchange (卖空比) 和 Stockgrid (暗盘净头寸).
    axlfi.com 提供公开 REST API，无需 Playwright 爬虫。
    """
    from data_fetchers.axlfi_fetcher import create_axlfi_fetcher
    
    fetcher = create_axlfi_fetcher(mock_mode=True)
    
    # 获取暗盘净头寸历史 (252天)
    data = fetcher.fetch_symbol_data('SPY', window=252)
    if data:
        print(f"数据日期: {data['as_of_date']}")
        print(f"净头寸序列: {len(data.get('dollar_dp_position', []))} 天")
        if data.get('dollar_dp_position'):
            latest_dp = data['dollar_dp_position'][-1]
            print(f"最新净头寸: ${latest_dp:,.0f}")
    
    # 获取净头寸序列 (兼容旧接口)
    net_pos = fetcher.get_net_position_series('SPY', [20, 60])
    if net_pos:
        print(f"20日净头寸: {len(net_pos.get('20d', []))} 点")
        print(f"60日净头寸: {len(net_pos.get('60d', []))} 点")
    
    # 底背离检测
    if net_pos and net_pos.get('20d'):
        pos_series = net_pos['20d']
        prices = [450 - i * 2 for i in range(len(pos_series))]  # 模拟下跌价格
        result = fetcher.detect_bottom_divergence(pos_series, prices)
        print(f"底背离检测: divergence={result['divergence']}, golden_cross={result.get('golden_cross', False)}")
        print(f"20日斜率: {result['slope_20d']:.4e}, 60日斜率: {result['slope_60d']:.4e}")
    
    # 获取卖空指标
    short = fetcher.get_latest_short_metrics('SPY')
    if short:
        print(f"最新卖空占比: {short.get('latest_short_pct', 0):.1f}%")
        if short.get('latest_short_pct', 0) > 45:
            print("⚠️ 卖空比例>45%，机构被动吸筹信号!")
    
    # 排行榜
    leaderboard = fetcher.fetch_leaderboard(limit=5)
    if leaderboard:
        print(f"\n全市场暗盘 TOP5:")
        for i, row in enumerate(leaderboard[:5]):
            ticker = row.get('ticker', 'N/A')
            pos = row.get('dollar_dp_position', 0)
            print(f"  #{i+1} {ticker}: ${pos:,.0f}")


# ==================== 示例6: DBMF ETF动量监控 ====================
def example_dbmf_fetcher():
    """DBMF ETF动量监控示例"""
    from data_fetchers import create_dbmf_fetcher
    
    fetcher = create_dbmf_fetcher(mock_mode=True)
    
    # 获取实时价格
    price = fetcher.get_dbmf_intraday_price()
    if price:
        print(f"DBMF当前价格: ${price:.2f}")
    
    # 获取历史价格
    historical_prices = fetcher.get_dbmf_historical_prices('5d')
    if historical_prices:
        print(f"历史价格数据点: {len(historical_prices)}")
        
        # 检测MA5恢复
        recovery = fetcher.check_ma5_recovery(price, historical_prices)
        if recovery is not None:
            if recovery:
                print("✅ DBMF收复MA5且涨幅>2%，量化空头动能枯竭")
            else:
                print("❌ DBMF未收复MA5或涨幅不足2%")


# ==================== 综合示例: 多源数据聚合 ====================
def example_multi_source_aggregation():
    """多源数据聚合示例（Mock模式）"""
    from data_fetchers import (
        create_tradier_fetcher,
        create_yahoo_finance_fetcher,
        create_ccxt_fetcher,
        create_squeezemetrics_fetcher,
        create_chartexchange_fetcher,
        create_dbmf_fetcher
    )
    
    print("=" * 80)
    print("多源共振监控系统 - 数据聚合演示")
    print("=" * 80)
    
    # 1. 美股Gamma状态
    print("\n【1】美股微观结构")
    tradier = create_tradier_fetcher(mock_mode=True)
    yahoo = create_yahoo_finance_fetcher(mock_mode=True)
    
    raw_options = tradier.get_option_chain('SPY', '2026-06-19')
    options_df = tradier.parse_option_chain(raw_options)
    if options_df is not None:
        total_volume = options_df['volume'].sum()
        print(f"  SPY期权总成交量: {total_volume:,}")
    
    vix_ratio = yahoo.calculate_term_structure_ratio()
    if vix_ratio:
        state = "Backwardation ⚠️" if vix_ratio > 1.0 else "Contango ✅"
        print(f"  VIX期限结构: {vix_ratio:.3f} ({state})")
    
    # 2. 机构暗盘追踪
    print("\n【2】机构暗盘追踪")
    squeezemetrics = create_squeezemetrics_fetcher(mock_mode=True)
    chartexchange = create_chartexchange_fetcher(mock_mode=True)
    
    dix = squeezemetrics.get_daily_dix()
    if dix:
        status = "吸筹信号 🟢" if dix > 45.0 else "正常"
        print(f"  DIX指标: {dix:.2f}% ({status})")
    
    short_data = chartexchange.fetch_short_volume_data('SPY')
    short_ratio = chartexchange.calculate_off_exchange_short_ratio(short_data)
    if short_ratio:
        status = "做市商买入 🟢" if short_ratio > 45.0 else "正常"
        print(f"  场外卖空比: {short_ratio:.2f}% ({status})")
    
    # 3. 加密金丝雀
    print("\n【3】加密杠杆清洗")
    ccxt = create_ccxt_fetcher(mock_mode=True)
    
    funding_rate = ccxt.get_funding_rate('BTC/USDT')
    if funding_rate is not None:
        status = "看跌情绪" if funding_rate < 0 else "看涨情绪"
        print(f"  BTC资金费率: {funding_rate * 100:.4f}% ({status})")
    
    oi_data = ccxt.get_open_interest('BTC/USDT')
    if oi_data:
        print(f"  BTC持仓量: {oi_data['oi']:,.2f}")
    
    # 4. 量化趋势
    print("\n【4】量化趋势监控")
    dbmf = create_dbmf_fetcher(mock_mode=True)
    
    dbmf_price = dbmf.get_dbmf_intraday_price()
    if dbmf_price:
        print(f"  DBMF价格: ${dbmf_price:.2f}")
    
    print("\n" + "=" * 80)
    print("数据聚合完成！")
    print("=" * 80)


# ==================== 主函数 ====================
if __name__ == '__main__':
    
    print("运行所有示例...\n")
    
    # 同步示例
    print("【示例1】Tradier期权链")
    print("-" * 80)
    example_tradier_fetcher()
    print()
    
    print("【示例2】Yahoo Finance VIX")
    print("-" * 80)
    example_yahoo_finance_fetcher()
    print()
    
    print("【示例3】CCXT加密数据")
    print("-" * 80)
    example_ccxt_fetcher()
    print()
    
    print("【示例4】SqueezeMetrics DIX")
    print("-" * 80)
    example_squeezemetrics_fetcher()
    print()
    
    print("【示例5】AXLFI暗盘净头寸+做空 (替代ChartExchange+Stockgrid)")
    print("-" * 80)
    example_axlfi_fetcher()
    print()
    
    print("【示例6】DBMF ETF动量")
    print("-" * 80)
    example_dbmf_fetcher()
    print()
    
    print("【综合示例】多源数据聚合")
    print("-" * 80)
    example_multi_source_aggregation()
