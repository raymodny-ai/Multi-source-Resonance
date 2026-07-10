#!/usr/bin/env python3
"""
MSR 每日定时批量采集脚本 (方案 C: 独立 cron 入口)

目的: 每天美东 22:00 自动调 RESTPollScheduler.run_once_manual_collect()
      拉取全部 7 数据源 (GEXMetrix / VIX / AXLFI / DBMF / 加密 / 做空 / SqueezeMetrics)

用法:
    .venv/bin/python scripts/daily_collect.py
    或 (被 OpenClaw cron 调):
    bash scripts/daily_collect.sh

设计:
    - 不依赖 main_stream.py (空壳) 或 api_server.py (手动模式)
    - 独立实例化 EventBus + RESTPollScheduler
    - 完成后立即退出 (非守护), cron 失败有 failureAlert 接管
    - 采集结果打 stdout, 失败 exit 1 让 cron 触发告警
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

# 把项目根加 sys.path (脚本在 scripts/ 下)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.logger import getLogger  # noqa: E402

logger = getLogger("daily_collect")


async def main() -> int:
    started = time.time()
    started_iso = datetime.now(timezone.utc).astimezone().isoformat()
    logger.info("=" * 60)
    logger.info("  MSR 每日批量采集 STARTED  %s", started_iso)
    logger.info("=" * 60)

    try:
        # 1) 延迟 import: 失败时给出明确报错 (而不是堆栈)
        from data_stream.event_bus import EventBus
        from data_stream.rest_poll_scheduler import RESTPollScheduler

        # 2) 启动 EventBus
        bus = EventBus()
        await bus.start()

        try:
            # 3) 启动 RESTPollScheduler (不启动自动轮询, 只手动跑一次)
            sched = RESTPollScheduler(bus)
            # 不调 sched.start() —— 那是后台循环, 我们只要 run_once

            # 4) 执行一次完整采集
            result = await sched.run_once_manual_collect()
        finally:
            # 5) 关闭 EventBus (即使采集失败也清干净)
            await bus.shutdown()

    except Exception as e:
        logger.error("❌ 采集流程异常: %s", e, exc_info=True)
        return 1

    # 6) 输出汇总 (cron 看这一行判定 ok/err)
    elapsed = round(time.time() - started, 2)
    sources = result.get("sources", [])
    n_ok = result.get("success_count", sum(1 for r in sources if r.get("status") == "success"))
    n_err = len(sources) - n_ok

    logger.info("=" * 60)
    logger.info("  MSR 每日批量采集 FINISHED  耗时 %.1fs", elapsed)
    logger.info("  成功 %d / 失败 %d / 总 %d", n_ok, n_err, len(sources))
    logger.info("=" * 60)

    # 7) 关键结果 JSON 单行输出 (方便 cron / log 解析)
    summary = {
        "started_at": started_iso,
        "elapsed_sec": elapsed,
        "total": len(sources),
        "success": n_ok,
        "error": n_err,
        "sources": [
            {
                "name": r.get("name"),
                "source_tag": r.get("source_tag"),
                "status": r.get("status"),
                "elapsed_sec": r.get("elapsed_sec"),
                "error": (r.get("error") or "")[:200] if r.get("status") == "error" else None,
            }
            for r in sources
        ],
    }
    print("===DAILY_COLLECT_RESULT===", json.dumps(summary, ensure_ascii=False), "===END===")

    # 8) 任一 source 失败 → exit 1 (cron 触发 failureAlert)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)