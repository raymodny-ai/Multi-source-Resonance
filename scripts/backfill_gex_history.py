#!/usr/bin/env python3
"""
方案A — GEX 历史数据回填 (3 个月 ≈ 63 交易日)

数据源: SqueezeMetrics DIX.csv (免费公开, 2011-至今 3800+ 行)
目标表: gex_history (供 /api/gex/history + /api/dashboard/gex-curve 使用)
策略:   INSERT OR REPLACE (按日期去重, 幂等)

字段映射:
  timestamp        → 美东当日 16:00 (盘中收盘)
  gex_local        → SqueezeMetrics 总 GEX (USD)
  gex_calibrated   → gex_local × alpha_factor (默认 1.0)
  alpha_factor     → 读 system_config 表, fallback 1.0
  put_wall_level   → NULL (SqueezeMetrics CSV 不提供逐 strike 分布)
  flip_zone_lower  → NULL
  flip_zone_upper  → NULL

Usage:
    cd Multi-source-Resonance
    .venv/bin/python3 scripts/backfill_gex_history.py                # 90 日历天
    .venv/bin/python3 scripts/backfill_gex_history.py --days 120     # 自定义
    .venv/bin/python3 scripts/backfill_gex_history.py --dry-run      # 只看,不入库
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import StringIO

import pandas as pd
import requests

# 把项目根加进 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DataFetchConfig
from database.db_manager import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('backfill_gex_history')


def fetch_squeezemetrics_history(days: int) -> pd.DataFrame:
    """从 SqueezeMetrics 拉最近 N 天的 DIX+GEX+SPX 价格"""
    url = DataFetchConfig.SQUEEZEMETRICS_CSV_URL
    log.info(f"下载 SqueezeMetrics CSV: {url}")
    resp = requests.get(url, timeout=30, headers={
        'User-Agent': 'Mozilla/5.0 (Multi-source-Resonance backfill)'
    })
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    log.info(f"原始数据: {len(df)} 行 ({df['date'].min()} → {df['date'].max()})")
    # 取最近 N 天
    df = df.tail(days)
    return df


def get_alpha_factor(db: DatabaseManager) -> float:
    """读 system_config.alpha_factor, fallback 1.0"""
    try:
        val = db.get_config_value('alpha_factor', '1.0')
        return float(val) if val else 1.0
    except Exception as e:
        log.warning(f"读 alpha_factor 失败, 用 1.0: {e}")
        return 1.0


def backfill(days: int = 90, dry_run: bool = False) -> dict:
    """主回填流程

    Returns:
        {
            'fetched_rows': N,
            'inserted_rows': M,
            'skipped_holidays': K,
            'date_range': (start, end),
            'alpha_factor': X,
        }
    """
    # 1. 拉数据
    df = fetch_squeezemetrics_history(days)
    if df.empty:
        log.error("SqueezeMetrics CSV 空数据, 终止")
        return {'error': 'empty_csv'}

    # 2. 读 alpha
    db = DatabaseManager()
    alpha = get_alpha_factor(db)
    log.info(f"alpha_factor = {alpha}")

    # 3. 按日插
    # 美东 16:00 对应北京时间次日 04:00 (夏令时), 这里简化为美东 16:00
    # 数据库存的 timestamp 是 ISO 格式, 后面 api_server 会原样返回
    inserted = 0
    skipped_holiday = 0
    total = len(df)
    log.info(f"准备回填 {total} 天, dry_run={dry_run}")

    for idx, row in df.iterrows():
        date_str = str(row['date'])  # 'YYYY-MM-DD'
        try:
            # 美东 16:00 当日 → 用 naive ISO 字符串, 跟现存数据一致
            ts = f"{date_str}T16:00:00"
            gex_local = float(row['gex'])
            gex_calibrated = gex_local * alpha
            spot_price = float(row['price'])
            # 跳过 GEX 缺失/异常的日期 (SqueezeMetrics 偶有 NaN)
            if pd.isna(gex_local) or gex_local == 0:
                log.debug(f"  跳过 {date_str} (GEX=NaN/0)")
                skipped_holiday += 1
                continue

            if dry_run:
                log.info(f"  [DRY] {date_str} GEX=${gex_local/1e9:.2f}B spot={spot_price:.2f}")
            else:
                ok = db.insert_gex_record(
                    timestamp=datetime.fromisoformat(ts),
                    gex_local=gex_local,
                    gex_calibrated=gex_calibrated,
                    alpha_factor=alpha,
                    put_wall_level=None,
                    flip_zone_lower=None,
                    flip_zone_upper=None,
                )
                if ok:
                    inserted += 1

        except Exception as e:
            log.warning(f"  {date_str} 失败: {e}")
            skipped_holiday += 1

    log.info(f"完成: 插入 {inserted} 条, 跳过 {skipped_holiday} 条")

    return {
        'fetched_rows': total,
        'inserted_rows': inserted,
        'skipped_holidays': skipped_holiday,
        'date_range': (str(df['date'].iloc[0]), str(df['date'].iloc[-1])),
        'alpha_factor': alpha,
    }


def main():
    parser = argparse.ArgumentParser(description='方案A — GEX 历史数据回填')
    parser.add_argument('--days', type=int, default=90, help='回填天数 (默认 90 日历天 ≈ 63 交易日)')
    parser.add_argument('--dry-run', action='store_true', help='只看,不入库')
    args = parser.parse_args()

    log.info(f"=== backfill_gex_history.py 启动 (days={args.days}, dry_run={args.dry_run}) ===")
    result = backfill(days=args.days, dry_run=args.dry_run)
    log.info(f"=== 完成: {result} ===")


if __name__ == '__main__':
    main()
