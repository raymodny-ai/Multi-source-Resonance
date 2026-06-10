"""
多源共振监控系统 - Push 实时流架构入口

新的系统入口文件，启动 StreamEngine (WebSocket + EventBus + RESTPollScheduler)。
替代原有的 main_scheduler.py (APScheduler 定时轮询模式)。

使用方式:
    py main_stream.py

    或在代码中:
    from main_stream import start
    start()
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_stream.stream_engine import StreamEngine, create_and_start_engine
from utils.logger import getLogger

logger = getLogger('main_stream')


def start():
    """启动 Push 架构实时监控系统"""
    logger.info("正在启动 Push 实时流架构...")
    engine = StreamEngine()
    engine.start()


if __name__ == "__main__":
    start()
