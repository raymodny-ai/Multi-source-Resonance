#!/usr/bin/env python3
"""
Multi-source Resonance V2.0 — 盘后批处理流水线入口脚本

用法:
    # 运行今日完整流水线
    python run_pipeline_v2.py

    # 跳过 LLM 推理（仅输出 Layer 2 JSON）
    python run_pipeline_v2.py --skip-llm

    # 指定日期回测
    python run_pipeline_v2.py --backtest 2026-06-10

    # 批量回测
    python run_pipeline_v2.py --backtest-range 2026-06-01..2026-06-10

    # 调度模式（配合 cron / Task Scheduler）
    python run_pipeline_v2.py --daemon

依赖:
    pip install -r requirements.txt
    cp .env.example .env  # 配置 LLM API Key
"""

import sys
import asyncio
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Config, config
from utils.logger import getLogger

logger = getLogger('run_pipeline_v2')


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Multi-source Resonance V2.0 — 三层解耦批处理流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline_v2.py                           # 今日完整运行
  python run_pipeline_v2.py --skip-llm                 # 跳过 LLM
  python run_pipeline_v2.py --backtest 2026-06-10      # 单日回测
  python run_pipeline_v2.py --backtest-range 2026-06-01..2026-06-10  # 批量回测
        """,
    )

    parser.add_argument(
        '--skip-llm',
        action='store_true',
        help='跳过 LLM 推理阶段，仅输出 Layer 2 JSON 指标',
    )
    parser.add_argument(
        '--backtest',
        type=str,
        metavar='YYYY-MM-DD',
        help='对指定历史日期执行 Layer 3 推理回测',
    )
    parser.add_argument(
        '--backtest-range',
        type=str,
        metavar='YYYY-MM-DD..YYYY-MM-DD',
        help='对日期范围内的每个日期执行批量回测',
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help=f'报告输出目录 (默认: {Config.PIPELINE_OUTPUT_DIR})',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细日志输出',
    )

    return parser.parse_args()


async def run_single_day(args: argparse.Namespace) -> int:
    """运行单日流水线"""
    from pipeline_v2.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator(output_dir=args.output_dir)
    target_date = None

    if args.backtest:
        target_date = datetime.strptime(args.backtest, '%Y-%m-%d').date()
        ctx = await orchestrator.run_backtest(target_date)
    else:
        ctx = await orchestrator.run_full_pipeline(
            target_date=target_date,
            skip_llm=args.skip_llm,
        )

    return _print_results(ctx)


async def run_backtest_range(args: argparse.Namespace) -> int:
    """批量回测"""
    start_str, end_str = args.backtest_range.split('..')
    start_date = datetime.strptime(start_str.strip(), '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str.strip(), '%Y-%m-%d').date()

    from pipeline_v2.orchestrator import PipelineOrchestrator
    orchestrator = PipelineOrchestrator(output_dir=args.output_dir)

    current = start_date
    success_count = 0
    fail_count = 0

    logger.info(f"========== 批量回测: {start_date} → {end_date} ==========")
    print(f"\n📊 批量回测: {start_date} → {end_date} ({((end_date - start_date).days + 1)} 天)\n")

    while current <= end_date:
        is_weekday = current.weekday() < 5  # 仅交易日
        if is_weekday:
            try:
                ctx = await orchestrator.run_backtest(current)
                if ctx.has_errors:
                    fail_count += 1
                    print(f"  ❌ {current}: 失败 ({len(ctx.errors)} 错误)")
                else:
                    success_count += 1
                    score = ""
                    gateway = ctx.get_result('gateway')
                    if gateway:
                        env = gateway.get('envelope')
                        if env:
                            score = f" (Score: {env.snapshot.resonance_intensity_score})"
                    print(f"  ✅ {current}: 成功{score}")
            except Exception as e:
                fail_count += 1
                print(f"  ❌ {current}: 异常 - {e}")
        else:
            print(f"  ⏭️  {current}: 跳过 (非交易日)")

        current += timedelta(days=1)

    print(f"\n📊 批量回测完成: 成功={success_count}, 失败={fail_count}")
    return 0 if fail_count == 0 else 1


def _print_results(ctx) -> int:
    """打印运行结果摘要"""
    gateway = ctx.get_result('gateway')
    infer = ctx.get_result('infer')
    dispatch = ctx.get_result('dispatch')

    print("\n" + "=" * 60)
    print("Pipeline V2.0 — 运行结果")
    print("=" * 60)

    if ctx.has_errors:
        print(f"\n❌ 错误数: {len(ctx.errors)}")
        for err in ctx.errors:
            print(f"   - [{err['stage']}] {err['error_type']}: {err['message']}")

    if gateway:
        envelope = gateway.get('envelope')
        interception = gateway.get('interception')
        if envelope:
            print(f"\n📊 共振得分: {envelope.snapshot.resonance_intensity_score}/100 "
                  f"({envelope.snapshot.resonance_signal_state})")
            print(f"📋 数据质量: {envelope.snapshot.data_quality_flag}")
        if interception:
            print(f"🛡️  拦截状态: {interception.status.value}")

    if infer and not infer.get('blocked') and not infer.get('degraded'):
        response = infer.get('response')
        hallu = infer.get('hallucination_flags', [])
        if response:
            print(f"🤖 LLM: tokens={response.total_tokens}, latency={response.latency_ms}ms")
        if hallu:
            print(f"⚠️  幻觉检测: {len(hallu)} 个问题")

    if dispatch:
        print(f"📄 报告: {dispatch.get('markdown_path', 'N/A')}")
        print(f"📨 模式: {dispatch.get('mode', 'unknown')}")

    print(f"\n⏱️  总耗时: {ctx.elapsed_seconds:.1f}s")
    print("=" * 60 + "\n")

    return 0 if not ctx.has_errors else 1


async def main() -> int:
    """主入口"""
    args = parse_args()

    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    print(f"\n🚀 Multi-source Resonance V2.0 — Pipeline")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔧 LLM Provider: {Config.LLM_PROVIDER}")
    print(f"🤖 Model: {Config.OPENAI_MODEL if Config.LLM_PROVIDER == 'openai' else Config.ANTHROPIC_MODEL}")

    # 验证配置
    missing = Config.validate()
    if missing:
        print(f"\n⚠️  配置警告: {missing}")

    try:
        if args.backtest_range:
            return await run_backtest_range(args)
        else:
            return await run_single_day(args)
    except KeyboardInterrupt:
        print("\n\n⚠️  流水线被用户中断")
        return 130
    except Exception as e:
        logger.error(f"流水线异常退出: {e}", exc_info=True)
        print(f"\n❌ 流水线异常退出: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
