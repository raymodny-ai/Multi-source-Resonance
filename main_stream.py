"""
多源共振监控系统 - 入口文件 (每日定时批量采集模式)

⚠️ 盘中高频轮询已完全移除。系统现为每日单次批量采集模式：
  每天美东 22:00 统一拉取全部 6 数据源 (GEX/DIX, VIX, AXLFI暗盘,
  DBMF, 加密衍生品, 做空)，通过 EventBus 发布后由 SignalPipeline
  消费并触发共振评分和告警推送。

  手动采集仍可通过 api_server.py 前端触发：
    1. 启动 api_server.py (FastAPI + 前端)
    2. 在浏览器中打开 http://localhost:8524
    3. 进入「系统状态监控」页面
    4. 点击「手动采集全部数据」按钮

使用方式:
    py main_stream.py            # 启动每日定时批量采集 + WebSocket 实时流
    py api_server.py              # 启动 API + 前端 (含手动采集)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import getLogger

logger = getLogger('main_stream')


def start():
    """启动每日定时批量采集 + WebSocket 实时流。
    
    盘中高频轮询已移除，所有数据源统一在美东 22:00 批量拉取。
    Hyperliquid WebSocket 仍保持实时推送。
    """
    logger.info("=" * 54)
    logger.info("  每日定时批量采集模式 (美东 22:00)")
    logger.info("=" * 54)
    logger.info("  盘中高频轮询已移除。数据采集统一到每日 22:00 ET。")
    logger.info("  Hyperliquid WebSocket 实时流仍保持连接。")
    logger.info("")
    logger.info("  启动方式:")
    logger.info("    py main_stream.py       # 每日批量 + WebSocket")
    logger.info("    py api_server.py         # API + 前端 + 手动采集")
    logger.info("=" * 54)


if __name__ == "__main__":
    start()
