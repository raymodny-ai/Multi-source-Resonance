"""
多源共振监控系统 - GEXMetrix Gamma Dashboard 数据获取器

从 GEXMetrix API 获取期权市场结构数据 (GEX 行权价分布、关键价位等)。
API 凭证从 .env 文件读取 (GEXMETRIX_API_KEY, GEXMETRIX_SESSION_TOKEN, GEXMETRIX_USER_EMAIL)。

数据存储: data/gexmetrix/{symbol}/{timestamp}.json (原始快照)
摘要存储: database/monitoring.db → gex_snapshots 表

支持 46 个标的 (SPX, SPY, QQQ, IWM, NVDA, TSLA 等)。
"""

import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import Config
from utils.logger import getLogger
# 数据质量验证 (v2.3) - 可选依赖, 导入失败不阻塞 fetcher
try:
    from quant_logic.gex_data_quality import validate_after_fetch
    _QUALITY_VALIDATOR_AVAILABLE = True
except ImportError:
    _QUALITY_VALIDATOR_AVAILABLE = False

logger = getLogger('gexmetrix_fetcher')


class GEXMetrixFetcher:
    """GEXMetrix Gamma Dashboard 数据获取器

    从 GEXMetrix API 获取期权市场结构数据，包括：
    - 逐行权价 GEX 分布 (Call GEX / Put GEX)
    - Zero Gamma Level (做市商对冲方向分界线)
    - Call Wall / Put Wall (期权密集行权价)
    - Net GEX (净 Gamma 敞口)

    API 端点:
        GET /api/symbols           → 所有可用标的列表
        GET /api/files/{symbol}/latest → 标的最新快照文件名
        GET /api/data/{symbol}/{filename} → 快照完整数据 (JSON)

    典型快照体积: 100KB ~ 15MB (SPX 最大)
    """

    # 核心标的 (盘中高频拉取，与方案调度表一致)
    CORE_SYMBOLS = ['SPX', 'SPY', 'QQQ', 'VIX', 'IWM', 'NDX']
    # 指数类 (盘前拉取)
    INDEX_SYMBOLS = ['SPX', 'NDX', 'DJX', 'RUT']

    DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "gexmetrix"

    # ── 性能优化: 内存缓存 (TTL 5分钟) ──
    _parsed_cache: Dict[str, tuple] = {}  # symbol → (metrics, cached_at_timestamp)

    def __init__(self):
        cfg = Config()
        self._api_key = cfg.GEXMETRIX_API_KEY
        self._session_token = cfg.GEXMETRIX_SESSION_TOKEN
        self._user_email = cfg.GEXMETRIX_USER_EMAIL
        self._api_base = cfg.GEXMETRIX_API_BASE

        self.session = requests.Session()
        self.session.headers.update(self._headers())

        GEXMetrixFetcher.DATA_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "GEXMetrixFetcher 初始化: %d 核心标的, API=%s",
            len(self.CORE_SYMBOLS), self._api_base,
        )

    # ==================== API 凭证 ====================

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "X-Session-Token": self._session_token,
            "X-User-Email": self._user_email,
            "Origin": "https://www.gexmetrix.com",
            "Accept": "application/json",
        }

    def _get_json(self, path: str) -> dict:
        url = f"{self._api_base}{path}"
        resp = self.session.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ==================== API 方法 ====================

    def get_symbols(self) -> List[str]:
        """获取所有可用标的列表"""
        try:
            data = self._get_json("/api/symbols")
            return data.get("symbols", [])
        except RequestException as e:
            logger.error(f"获取标的列表失败: {e}")
            return []

    def get_latest_file(self, symbol: str) -> Optional[dict]:
        """获取标的最新快照文件名"""
        try:
            return self._get_json(f"/api/files/{symbol}/latest")
        except RequestException as e:
            logger.warning(f"  {symbol}: {e}")
            return None

    def get_snapshot_data(self, symbol: str, filename: str) -> Optional[dict]:
        """获取标的完整快照数据"""
        try:
            return self._get_json(f"/api/data/{symbol}/{filename}")
        except RequestException as e:
            logger.warning(f"  {symbol}/{filename}: {e}")
            return None

    # ==================== 存储方法 ====================

    def save_json(self, data: dict, path: Path) -> Path:
        """保存 JSON 到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def save_snapshot(self, symbol: str, data: dict) -> Path:
        """保存快照数据到 data/gexmetrix/{symbol}/{timestamp}.json"""
        symbol_dir = GEXMetrixFetcher.DATA_DIR / symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)

        inner = data.get("data")
        raw_ts = data.get("timestamp", "") or (
            inner.get("timestamp", "") if isinstance(inner, dict) else ""
        )
        if raw_ts:
            try:
                dt = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                filename = f"{dt.strftime('%Y%m%d_%H%M%S')}.json"
            except ValueError:
                filename = f"snapshot_{int(time.time())}.json"
        else:
            filename = f"snapshot_{int(time.time())}.json"

        filepath = symbol_dir / filename
        return self.save_json(data, filepath)

    def _enrich_with_quality(self, symbol: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """v2.3: 对单条快照跑数据质量验证, 失败时返回中性默认值

        Returns:
            dict (validate_snapshot 输出) 或默认 {'score': 0.5, 'valid': True, ...}
        """
        if not _QUALITY_VALIDATOR_AVAILABLE:
            return {
                'symbol': symbol, 'valid': True, 'score': 0.5,
                'lag_seconds': None, 'oi_coverage_pct': None,
                'iv_violations': 0, 'strike_density': 0,
                'zero_oi_pct': 0.0, 'issues': ['validator_unavailable'],
            }
        return validate_after_fetch(symbol, raw_data)

    def update_summary(self, success_list: List[dict]) -> Path:
        """更新全局 summary.json"""
        summary = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbols": {s["symbol"]: s for s in success_list},
        }
        path = GEXMetrixFetcher.DATA_DIR / "summary.json"
        return self.save_json(summary, path)

    def clean_old(self, symbol: str, keep: int = 50) -> None:
        """清理旧快照，每个标的保留最近 N 个"""
        symbol_dir = GEXMetrixFetcher.DATA_DIR / symbol.lower()
        if not symbol_dir.exists():
            return
        files = sorted(symbol_dir.glob("*.json"), reverse=True)
        for f in files[keep:]:
            f.unlink()
            logger.debug(f"清理旧快照: {f.name}")

    # ==================== 关键指标解析 ====================

    @classmethod
    def get_cached_metrics(cls, symbol: str, max_age_sec: int = 300) -> Optional[Dict[str, Any]]:
        """从内存缓存获取已解析的关键指标 (TTL 5分钟)

        避免重复解析大文件 (SPX 15MB, SPY 7MB, QQQ 6MB)，
        显著减少 I/O 和 CPU 开销。

        Args:
            symbol: 标的代码
            max_age_sec: 缓存有效期 (秒), 默认 300s

        Returns:
            缓存的 metrics dict 或 None (过期/未命中)
        """
        if symbol in cls._parsed_cache:
            metrics, cached_at = cls._parsed_cache[symbol]
            age = time.time() - cached_at
            if age < max_age_sec:
                return metrics
        return None

    @classmethod
    def cache_metrics(cls, symbol: str, metrics: Dict[str, Any]) -> None:
        """将解析后的关键指标存入内存缓存"""
        cls._parsed_cache[symbol] = (metrics, time.time())

    @classmethod
    def invalidate_cache(cls, symbol: Optional[str] = None) -> None:
        """清除缓存

        Args:
            symbol: 指定标的 (None 则清除全部)
        """
        if symbol:
            cls._parsed_cache.pop(symbol, None)
        else:
            cls._parsed_cache.clear()

    @staticmethod
    def parse_snapshot_key_metrics(data: dict) -> Dict[str, Any]:
        """从原始快照 JSON 中提取关键指标摘要

        解析 GEXMetrix API 返回的完整快照数据。
        GEXMetrix 原始数据含 options 数组（每笔有 gamma/delta/open_interest），
        需要汇总计算 GEX 值，不能直接读顶层字段。

        GEX = gamma × open_interest × 100 (每张合约 100 股)
        Call GEX > 0 → 做市商买入对冲（正 Gamma，压制波动）
        Put GEX < 0 → 做市商卖出对冲（负 Gamma，放大波动）
        """
        result = {
            "net_gex": None,
            "call_gex": None,
            "put_gex": None,
            "zero_gamma_level": None,
            "call_wall": None,
            "put_wall": None,
            "spot_price": None,
            "total_gamma": None,
        }

        try:
            inner = data.get("data", data)
            # GEXMetrix 实际结构: data.data.options = [{option, gamma, open_interest, ...}]
            payload = inner.get("data", inner) if isinstance(inner, dict) else inner

            # 现价
            result["spot_price"] = (
                payload.get("current_price")
                or payload.get("spot_price")
                or payload.get("price")
            )

            # 从 options 数组计算 GEX
            options = payload.get("options", [])  # GEXMetrix 格式
            if not options:
                # 也查查内层有没有 options
                options = inner.get("options", [])
                if not options:
                    options = data.get("options", [])

            if options and isinstance(options, list):
                call_gamma_sum = 0.0
                put_gamma_sum = 0.0
                max_call_gamma = 0.0
                max_put_gamma = 0.0
                max_call_strike = None
                max_put_strike = None

                # gamma = 该期权的 gamma 值，open_interest = 未平仓量
                # GEX = gamma × OI × 合约乘数 (通常 100)
                CONTRACT_MULTIPLIER = 100

                for opt in options:
                    if not isinstance(opt, dict):
                        continue
                    gamma = opt.get("gamma") or 0
                    oi = opt.get("open_interest") or 0
                    strike = opt.get("option", "")  # 如 "SPX260717C00200000"

                    if not gamma or not oi:
                        continue

                    gex = float(gamma) * float(oi) * CONTRACT_MULTIPLIER

                    # 判断 call/put: option 字符串如 SPX260717C00200000
                    # C = Call, P = Put
                    if isinstance(strike, str):
                        is_call = "C" in strike.split("C")[0] if len(strike) > 10 else False
                        # 简单判断: 期权符号倒数第3位之后有 C 或 P
                        # 格式: [根] + [日期] + [C/P] + [行权价填充]
                        try:
                            opt_type = strike[9] if len(strike) > 9 else ""
                            is_call = opt_type == "C"
                        except (IndexError, TypeError):
                            is_call = True  # fallback
                    else:
                        is_call = True

                    if is_call:
                        call_gamma_sum += gex
                        if gex > max_call_gamma:
                            max_call_gamma = gex
                            # 提取行权价：C 后面的数字
                            if isinstance(strike, str) and len(strike) > 10:
                                try:
                                    max_call_strike = float(strike[10:]) / 1000
                                except ValueError:
                                    pass
                    else:
                        put_gamma_sum += gex
                        if abs(gex) > max_put_gamma:
                            max_put_gamma = abs(gex)
                            if isinstance(strike, str) and len(strike) > 10:
                                try:
                                    max_put_strike = float(strike[10:]) / 1000
                                except ValueError:
                                    pass

                result["call_gex"] = call_gamma_sum
                result["put_gex"] = -abs(put_gamma_sum)
                result["net_gex"] = call_gamma_sum + result["put_gex"]
                result["total_gamma"] = call_gamma_sum + abs(put_gamma_sum)
                result["call_wall"] = max_call_strike
                result["put_wall"] = max_put_strike

            # 零 Gamma 水平：计算 put_gex ≈ call_gex 的价位
            # ponytail: 更精确的 zero_gamma 需要插值 OTM strike 之间的 gamma 曲线
            if result["spot_price"] and result["net_gex"] is not None:
                if result["net_gex"] > 0:
                    # 正 Gamma → zero gamma 在现价上方
                    result["zero_gamma_level"] = result["spot_price"] * 1.05
                elif result["net_gex"] < 0:
                    # 负 Gamma → zero gamma 在现价下方
                    result["zero_gamma_level"] = result["spot_price"] * 0.95
                else:
                    result["zero_gamma_level"] = result["spot_price"]

        except Exception as e:
            logger.error(f"解析关键指标失败: {e}", exc_info=True)

        return result

    # ==================== 批量采集 ====================

    def fetch_all(self) -> List[dict]:
        """拉取所有标的的最新快照 (全量采集)"""
        logger.info("[%s] 开始拉取 GEXMetrix 全部标的", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        logger.info("  数据目录: %s", GEXMetrixFetcher.DATA_DIR)

        symbols = self.get_symbols()
        logger.info("  共 %d 个标的", len(symbols))

        success_list = []
        fail_count = 0

        for i, symbol in enumerate(symbols, 1):
            logger.info("  [%d/%d] %s...", i, len(symbols), symbol)
            try:
                data = self.get_latest_file(symbol)
                if data and "data" in data:
                    fp = self.save_snapshot(symbol, data)
                    size = os.path.getsize(fp)
                    logger.info("    OK %s (%d KB)", fp.name, size // 1024)
                    success_list.append({
                        "symbol": symbol,
                        "filename": fp.name,
                        "timestamp": data.get("timestamp", ""),
                        "file_size": size,
                    })
                    self.clean_old(symbol)
                else:
                    logger.warning("    FAIL no data")
                    fail_count += 1
            except Exception as e:
                logger.error("    FAIL %s", e)
                fail_count += 1

            if i < len(symbols):
                time.sleep(0.25)

        if success_list:
            self.update_summary(success_list)

        logger.info("完成: %d OK / %d FAIL", len(success_list), fail_count)
        return success_list

    def fetch_core(self) -> List[dict]:
        """拉取核心标的 (盘中高频)"""
        logger.info("开始拉取 GEXMetrix 核心标的: %s", self.CORE_SYMBOLS)
        success_list = []
        for symbol in self.CORE_SYMBOLS:
            try:
                data = self.get_latest_file(symbol)
                if data and "data" in data:
                    fp = self.save_snapshot(symbol, data)
                    size = os.path.getsize(fp)
                    entry = {
                        "symbol": symbol,
                        "filename": fp.name,
                        "timestamp": data.get("timestamp", ""),
                        "file_size": size,
                    }
                    # v2.3: 数据质量验证 (优雅失败)
                    entry["quality"] = self._enrich_with_quality(symbol, data)
                    success_list.append(entry)
                    self.clean_old(symbol)
                else:
                    logger.warning("  %s: no data", symbol)
            except Exception as e:
                logger.warning("  %s: %s", symbol, e)
            time.sleep(0.25)
        if success_list:
            self.update_summary(success_list)
        return success_list

    def fetch_indices(self) -> List[dict]:
        """拉取指数类标的 (盘前)"""
        logger.info("开始拉取 GEXMetrix 指数标的: %s", self.INDEX_SYMBOLS)
        success_list = []
        for symbol in self.INDEX_SYMBOLS:
            try:
                data = self.get_latest_file(symbol)
                if data and "data" in data:
                    fp = self.save_snapshot(symbol, data)
                    size = os.path.getsize(fp)
                    entry = {
                        "symbol": symbol,
                        "filename": fp.name,
                        "timestamp": data.get("timestamp", ""),
                        "file_size": size,
                    }
                    # v2.3: 数据质量验证
                    entry["quality"] = self._enrich_with_quality(symbol, data)
                    success_list.append(entry)
                    self.clean_old(symbol)
                else:
                    logger.warning("  %s: no data", symbol)
            except Exception as e:
                logger.warning("  %s: %s", symbol, e)
            time.sleep(0.25)
        return success_list

    def fetch_single(self, symbol: str) -> bool:
        """拉取单个标的"""
        symbol = symbol.upper()
        logger.info("拉取 %s...", symbol)
        try:
            data = self.get_latest_file(symbol)
            if data and "data" in data:
                fp = self.save_snapshot(symbol, data)
                logger.info("  已保存: %s", fp)
                return True
            logger.warning("  失败: no data")
            return False
        except Exception as e:
            logger.error("  失败: %s", e)
            return False

    # ==================== 摘要查询 (从本地文件) ====================

    def get_summary(self) -> Optional[Dict[str, Any]]:
        """读取本地 summary.json"""
        summary_path = GEXMetrixFetcher.DATA_DIR / "summary.json"
        if not summary_path.exists():
            return None
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 summary.json 失败: {e}")
            return None

    def get_latest_snapshot_file(self, symbol: str) -> Optional[Path]:
        """获取标的最近快照文件路径"""
        symbol_dir = GEXMetrixFetcher.DATA_DIR / symbol.lower()
        if not symbol_dir.exists():
            return None
        files = sorted(symbol_dir.glob("*.json"), reverse=True)
        return files[0] if files else None

    def read_snapshot(self, symbol: str) -> Optional[dict]:
        """读取标的最新快照数据 (优先从缓存获取已解析指标)"""
        # 先查缓存
        cached = self.get_cached_metrics(symbol)
        if cached:
            return {"data": cached, "_cached": True}

        fp = self.get_latest_snapshot_file(symbol)
        if not fp:
            return None
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 对大文件自动缓存解析结果
            file_size = os.path.getsize(fp)
            if file_size > 1_000_000:  # >1MB 的文件缓存
                metrics = self.parse_snapshot_key_metrics(data)
                self.cache_metrics(symbol, metrics)
            return data
        except Exception as e:
            logger.error(f"读取快照失败 {fp}: {e}")
            return None

    def read_snapshot_by_filename(self, symbol: str, filename: str) -> Optional[dict]:
        """按文件名读取快照"""
        fp = GEXMetrixFetcher.DATA_DIR / symbol.lower() / filename
        if not fp.exists():
            return None
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取快照失败 {fp}: {e}")
            return None


def create_gexmetrix_fetcher() -> GEXMetrixFetcher:
    """创建 GEXMetrixFetcher 实例"""
    return GEXMetrixFetcher()
