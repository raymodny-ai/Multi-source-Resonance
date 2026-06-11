"""
多源共振监控系统 - 入口文件 (手动采集模式)

⚠️ 自动采集已完全禁用。系统现为纯手动采集模式：
  1. 启动 api_server.py (FastAPI + 前端)
  2. 在浏览器中打开 http://localhost:8524
  3. 进入「系统状态监控」页面
  4. 点击「手动采集全部数据」按钮触发一次性全量数据拉取

使用方式:
    py api_server.py          # 启动 API + 前端
    # 然后在浏览器中手动触发采集
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import getLogger

logger = getLogger('main_stream')


def start():
    """自动采集已禁用。请使用 api_server.py + 前端手动触发。"""
    logger.info("=" * 54)
    logger.info("  ⚠ 自动数据采集已完全关闭 (手动采集模式)")
    logger.info("=" * 54)
    logger.info("  请启动 api_server.py 并在前端手动触发采集:")
    logger.info("    py api_server.py")
    logger.info("    浏览器打开 http://localhost:8524 → 系统状态监控 → 手动采集")
    logger.info("=" * 54)


if __name__ == "__main__":
    start()
