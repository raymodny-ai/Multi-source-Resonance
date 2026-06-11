"""全数据源状态检测 v2"""
import sys; sys.path.insert(0,'.')
import os, json, time
os.environ['PYTHONWARNINGS'] = 'ignore'

from config.settings import Config
import logging
logging.disable(logging.CRITICAL)  # 静音所有 logger

print('╔══════════════════════════════════════════╗')
print('║   多源共振系统 · 全数据源状态检测 v2      ║')
print('╚══════════════════════════════════════════╝')
print()

# ─── API Keys ───
print('━━━ API Key 配置 ━━━')
for k in ['TRADIER_API_KEY','TRADIER_ACCOUNT_ID','SQUEEZEMETRICS_API_KEY','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID']:
    v = getattr(Config, k, '')
    real = v and 'your_' not in v and 'placeholder' not in v.lower()
    icon = '🔑' if real else '⚠️'
    print(f'  {icon} {k}: {"真实" if real else "占位符/空"}')

print()
print('━━━ 数据源实时检测 ━━━')
results = []

# ─── 1. SqueezeMetrics ───
try:
    from data_fetchers.squeezemetrics_fetcher import SqueezeMetricsFetcher
    sqz = SqueezeMetricsFetcher()
    m = sqz.get_full_metrics()
    if m:
        results.append(('SqueezeMetrics', '✅', f"DIX={m['dix']:.1f}% GEX=${m['gex']/1e9:.2f}B SPX={m['price']:.0f}"))
    else:
        results.append(('SqueezeMetrics', '⚠️', 'CSV 返回空'))
except Exception as e:
    results.append(('SqueezeMetrics', '❌', str(e)[:60]))

# ─── 2. AXLFI ───
try:
    from data_fetchers.axlfi_fetcher import AxlfiFetcher
    axl = AxlfiFetcher()
    dp = axl.fetch_symbol_data('SPY')
    if dp and dp.get('latest'):
        l = dp['latest']
        pos = l.get('net_position', 0)
        results.append(('AXLFI暗盘', '✅', f"SPY ${pos/1e9:.1f}B 短比={l.get('short_pct',0):.1f}% {dp.get('total_records',0)}天"))
    else:
        results.append(('AXLFI暗盘', '⚠️', 'API 无响应'))
except Exception as e:
    results.append(('AXLFI暗盘', '❌', str(e)[:60]))

# ─── 3. Yahoo Finance ───
try:
    import yfinance as yf
    spy = yf.Ticker('SPY')
    info = spy.info
    price = info.get('regularMarketPrice') or info.get('currentPrice') or spy.history(period='1d')['Close'].iloc[-1]
    # VIX
    vix_data = yf.download('^VIX', period='1d', progress=False)
    vix_val = float(vix_data['Close'].iloc[-1]) if not vix_data.empty else 0
    results.append(('Yahoo Finance', '✅', f"SPY=${price:.2f} VIX={vix_val:.2f}"))
except Exception as e:
    results.append(('Yahoo Finance', '❌', str(e)[:60]))

# ─── 4. 做空数据 (yfinance → FINRA) ───
try:
    from data_fetchers.yahoo_finance_fetcher import YahooFinanceFetcher
    from data_fetchers.finra_fetcher import FINRAShortVolumeFetcher
    yf_fetcher = YahooFinanceFetcher(mock_mode=False)
    finra = FINRAShortVolumeFetcher()
    short_data = yf_fetcher.get_short_interest('SPY')
    if short_data and short_data.get('short_pct_float') is not None:
        short_ratio = short_data['short_pct_float']
        results.append(('做空数据(yf)', '✅', f"SPY 做空比={short_ratio:.1f}%"))
    else:
        # 降级到 FINRA
        spy_data = finra.fetch_short_volume_data('SPY')
        if spy_data:
            short_ratio = finra.calculate_off_exchange_short_ratio(spy_data)
            results.append(('做空数据(FINRA)', '⚠️', f"SPY 场外做空比={short_ratio:.1f}%"))
        else:
            results.append(('做空数据', '⚠️', 'yfinance/FINRA 均返回空'))
except Exception as e:
    results.append(('做空数据', '❌', str(e)[:60]))

# ─── 5. CCXT ───
try:
    from data_fetchers.ccxt_fetcher import CCXTFetcher
    ccxt_f = CCXTFetcher(mock_mode=False)
    fr = ccxt_f.get_funding_rate('BTC/USDT')
    oi = ccxt_f.get_open_interest('BTC/USDT')
    if fr is not None:
        results.append(('CCXT衍生品', '✅', f"BTC 费率={fr*100:.4f}% OI={'OK' if oi else 'N/A'}"))
    else:
        results.append(('CCXT衍生品', '⚠️', 'API 返回空'))
except Exception as e:
    results.append(('CCXT衍生品', '❌', str(e)[:60]))

# ─── 6. DBMF ───
try:
    from data_fetchers.dbmf_fetcher import DBMFFetcher
    dbmf = DBMFFetcher()
    val = dbmf.get_dbmf_intraday_price()
    if val:
        results.append(('DBMF管理期货', '✅', f"${val:.2f}"))
    else:
        results.append(('DBMF管理期货', '⚠️', 'API 返回空'))
except Exception as e:
    results.append(('DBMF管理期货', '❌', str(e)[:60]))

# ─── 7. Tradier ───
tradier_real = Config.TRADIER_API_KEY and 'your_' not in Config.TRADIER_API_KEY
if tradier_real:
    try:
        from data_fetchers.tradier_fetcher import TradierFetcher
        tr = TradierFetcher()
        chain = tr.get_option_chain('SPY', '2026-06-20')
        results.append(('Tradier期权链', '✅', f"已获取" if chain else '返回空'))
    except Exception as e:
        results.append(('Tradier期权链', '❌', str(e)[:60]))
else:
    results.append(('Tradier期权链', '⏭️', 'Key为占位符 · GEX已由SQZ替代'))

# ─── 8. DB ───
db_path = 'database/monitoring.db'
try:
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    # 每表行数
    counts = {}
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            counts[t] = cnt
        except:
            counts[t] = '?'
    conn.close()
    results.append(('SQLite', '✅', f"{len(tables)}表 | " + ', '.join(f'{t}({counts[t]})' for t in sorted(tables)[:6])))
except Exception as e:
    results.append(('SQLite', '❌', str(e)[:60]))

# ─── 9. Stockgrid ───
results.append(('Stockgrid', '💀', '已死→AXLFI替代'))

# ─── Print ───
print()
for name, status, detail in results:
    print(f'  {status} {name:<18} {detail}')

ok   = sum(1 for _,s,_ in results if '✅' in s)
warn = sum(1 for _,s,_ in results if '⚠️' in s)
fail = sum(1 for _,s,_ in results if '❌' in s)
skip = sum(1 for _,s,_ in results if '⏭️' in s)
dead = sum(1 for _,s,_ in results if '💀' in s)
print()
print(f'✅{ok} ⚠️{warn} ⏭️{skip} ❌{fail} 💀{dead}  / {len(results)} 数据源')
print()
live = ok + warn
print(f'🗂️ 有效数据链路 {live}/{len(results)-dead-skip}: ' + ', '.join(name for name,st,_ in results if '✅' in st or '⚠️' in st))
