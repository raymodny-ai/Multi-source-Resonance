#!/usr/bin/env python3
"""一次性脚本: 重解析所有 data/gexmetrix/*/*.json 历史快照,
               把缺失的关键字段 (net_gex / call_wall / put_wall / zero_gamma_level /
               spot_price / total_gamma / call_gex / put_gex) 回填到 gex_snapshots 表。

原因: v2.5 之前的 parse_snapshot_key_metrics 因 data.{data} 嵌套 bug 全返回 None,
      fetcher 把 (filename, quality_score, file_size) 写入 gex_snapshots 但关键指标全为 NULL。
      本脚本运行 v2.6 修复版 fetcher 重算,UPDATE 已存在 snapshot 行。

幂等: 多次运行结果一致 (UPDATE, 不写新行)。

用法:
    cd Multi-source-Resonance
    .venv/bin/python scripts/reparse_gex_snapshots.py            # 全量 (73 文件)
    .venv/bin/python scripts/reparse_gex_snapshots.py --dry-run  # 只读不动
"""
import sys
import os
import json
import sqlite3
import argparse
import logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('reparse')

from data_fetchers.gexmetrix_fetcher import GEXMetrixFetcher


def _normalize_ts(snap_ts: str) -> str:
    """geo ts (eg '20260710_154415') → ISO 兼容 db 存储"""
    # API returns sym + filename; data['data']['timestamp'] is ISO with TZ
    return snap_ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--symbols', nargs='*', default=None,
                    help='Subset of symbols to process (default: all)')
    args = ap.parse_args()

    db_path = PROJECT_ROOT / 'database' / 'monitoring.db'
    gexmetrix_dir = PROJECT_ROOT / 'data' / 'gexmetrix'
    if not gexmetrix_dir.exists():
        log.error(f'data/gexmetrix 不存在: {gexmetrix_dir}')
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    symbols = args.symbols or [p.name.upper() for p in gexmetrix_dir.iterdir() if p.is_dir()]
    log.info(f'处理 {len(symbols)} 个标的: {symbols}')

    total_files = 0
    total_updated = 0
    total_strikes_inserted = 0
    skipped_no_snapshot = 0
    parse_errors = 0

    for sym in symbols:
        sym_dir = gexmetrix_dir / sym.lower()
        if not sym_dir.exists():
            continue
        json_files = sorted(sym_dir.glob('*.json'))
        if not json_files:
            continue
        log.info(f'[{sym}] {len(json_files)} 个文件')

        for jf in json_files:
            total_files += 1
            try:
                with open(jf) as f:
                    data = json.load(f)
            except Exception as e:
                log.warning(f'  {jf.name} load fail: {e}')
                parse_errors += 1
                continue

            fn = jf.name

            # 找 gex_snapshots 行 (按 filename 匹配)
            cur.execute(
                'SELECT id, timestamp FROM gex_snapshots WHERE symbol=? AND filename=?',
                (sym, fn),
            )
            row = cur.fetchone()
            if not row:
                skipped_no_snapshot += 1
                continue
            snap_id = row[0]

            # 解析 (修复后版本)
            try:
                metrics = GEXMetrixFetcher.parse_snapshot_key_metrics(data)
            except Exception as e:
                log.warning(f'  {sym}/{fn} metrics parse fail: {e}')
                parse_errors += 1
                continue

            if all(v is None for v in metrics.values()):
                log.debug(f'  {sym}/{fn}: 解析仍全 None (可能 strikes=0)')
                continue

            # 7 关键字段 (除 spot_price / zero_gamma 已归入)
            upd = (
                metrics.get('net_gex'),
                metrics.get('call_gex'),
                metrics.get('put_gex'),
                metrics.get('zero_gamma_level'),
                metrics.get('call_wall'),
                metrics.get('put_wall'),
                metrics.get('spot_price'),
                metrics.get('total_gamma'),
            )
            if args.dry_run:
                log.info(f'  [DRY] {sym}/{fn} -> '
                         f'net_gex={metrics.get("net_gex")}, '
                         f'pw={metrics.get("put_wall")}, '
                         f'cw={metrics.get("call_wall")}, '
                         f'spot={metrics.get("spot_price")}')
                total_updated += 1
                continue

            cur.execute("""
                UPDATE gex_snapshots SET
                    net_gex=?, call_gex=?, put_gex=?,
                    zero_gamma_level=?, call_wall=?, put_wall=?,
                    spot_price=?, total_gamma=?
                WHERE id=?
            """, (*upd, snap_id))

            # 补 strikes (老 snapshot 可能 0 行;本脚本同连接,避免锁竞争)
            cur.execute('SELECT count(*) FROM gex_strikes WHERE snapshot_id=?', (snap_id,))
            existing_strikes = cur.fetchone()[0]
            if existing_strikes == 0:
                try:
                    strikes = GEXMetrixFetcher.parse_strikes(data)
                    if strikes:
                        rows = [
                            (snap_id, sym, row[1],
                             float(s["strike"]), float(s["call_gex"]), float(s["put_gex"]),
                             int(s["call_oi"]), int(s["put_oi"]),
                             int(s.get("call_vol", 0)), int(s.get("put_vol", 0)),
                             float(s.get("net_gex", s["call_gex"] + s["put_gex"])))
                            for s in strikes
                        ]
                        cur.executemany("""
                            INSERT INTO gex_strikes
                            (snapshot_id, symbol, timestamp, strike, call_gex, put_gex,
                             call_oi, put_oi, call_vol, put_vol, net_gex)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, rows)
                        total_strikes_inserted += len(rows)
                except Exception as e:
                    log.warning(f'  {sym}/{fn} strikes parse fail: {e}')

            # 每 5 条提交一次 + 释放锁
            if total_updated % 5 == 0:
                conn.commit()

            total_updated += 1
            if total_updated % 20 == 0:
                log.info(f'  progress: {total_updated}/{total_files}')

    if not args.dry_run:
        conn.commit()
    conn.close()

    log.info(f'=== Done ===')
    log.info(f'files seen     : {total_files}')
    log.info(f'snapshots upd  : {total_updated}')
    log.info(f'strikes added  : {total_strikes_inserted}')
    log.info(f'skip no-row    : {skipped_no_snapshot}')
    log.info(f'parse errors   : {parse_errors}')


if __name__ == '__main__':
    main()
