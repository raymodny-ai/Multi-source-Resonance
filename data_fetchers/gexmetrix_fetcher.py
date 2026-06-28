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


    @staticmethod
    def _parse_occ_symbol(symbol: str) -> Optional[Dict[str, Any]]:
        """解析 OCC 期权符号 (如 SPY260626C00708000) → {date, cp, strike}

        OCC 格式: [underlying][YYMMDD][C/P][strike*1000 8位]
        例: SPY260626C00708000 → SPY, 2026-06-26, Call, strike=708.0
        """
        import re
        m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", symbol)
        if not m:
            return None
        underlying, date, cp, strike_raw = m.groups()
        try:
            return {
                "underlying": underlying,
                "date": f"20{date[:2]}-{date[2:4]}-{date[4:6]}",
                "cp": cp,
                "strike": int(strike_raw) / 1000.0,
            }
        except (ValueError, IndexError):
            return None

    @staticmethod
    def parse_strikes(
        data: dict,
        min_oi: Optional[int] = None,
        multiplier: int = 100,
        apply_liquidity_gate: bool = True,
    ) -> List[Dict[str, Any]]:
        """B: 从 GEXMetrix 快照 options[] 提取逐 strike 真实 GEX/OI 分布

        Args:
            data: GEXMetrix API 返回的完整快照 (三层嵌套 data.data.data.options)
            min_oi: 最小 OI 阈值,过滤深度虚值 (默认 None → 使用 Config.Thresholds.OI_GATE_THRESHOLD=500)
            multiplier: 合约乘数 (SPY/QQQ/IWM=100, SPX 指数期权=100)
            apply_liquidity_gate: V2.5 P1 - 是否应用双重流动性门控

        Returns:
            按 strike 聚合的列表: [{strike, call_gex, put_gex, call_oi, put_oi, call_vol, put_vol}, ...]
        """
        from collections import defaultdict
        try:
            inner = data.get("data", data)
            deep = inner.get("data", inner) if isinstance(inner, dict) else inner
            if not isinstance(deep, dict):
                return []
            options = deep.get("options", [])
            spot = (
                deep.get("current_price")
                or deep.get("spot_price")
                or deep.get("close")
                or 0
            )
            spot = float(spot) if spot else 0
            if not options or not spot:
                return []

            # V2.5 P1: 使用 Config 阈值代替硬编码
            if min_oi is None:
                min_oi = Config.Thresholds.OI_GATE_THRESHOLD

            # 按 strike 聚合 (call/put 分别)
            agg: Dict[float, Dict[str, float]] = defaultdict(
                lambda: {"call_gex": 0, "put_gex": 0, "call_oi": 0, "put_oi": 0, "call_vol": 0, "put_vol": 0}
            )

            for o in options:
                if not isinstance(o, dict):
                    continue
                occ = GEXMetrixFetcher._parse_occ_symbol(o.get("option", ""))
                if occ is None:
                    continue
                strike = occ["strike"]
                cp = occ["cp"]
                gamma = float(o.get("gamma") or 0)
                oi = int(o.get("open_interest") or 0)
                vol = int(o.get("volume") or 0)

                # V2.5 P1: 双重流动性门控 (OI 门控)
                if oi < min_oi:
                    continue
                # 过滤 gamma=0 的废数据
                if gamma == 0:
                    continue

                # V2.5 P1: 额外对 volume 过滤 (零交易量僵尸合约)
                if apply_liquidity_gate and vol == 0:
                    continue

                # GEX = gamma * OI * multiplier * spot^2 * 0.01
                # (单位是美元, dealer 立场)
                gex_value = gamma * oi * multiplier * spot * spot * 0.01

                if cp == "C":
                    agg[strike]["call_gex"] += gex_value
                    agg[strike]["call_oi"] += oi
                    agg[strike]["call_vol"] += vol
                else:
                    agg[strike]["put_gex"] += gex_value  # Put GEX 累加正数,前端渲染时取负
                    agg[strike]["put_oi"] += oi
                    agg[strike]["put_vol"] += vol

            # 排序输出
            result = []
            for strike in sorted(agg.keys()):
                a = agg[strike]
                result.append({
                    "strike": strike,
                    "call_gex": round(a["call_gex"], 2),
                    "put_gex": round(-a["put_gex"], 2),  # 负方向,前端习惯
                    "call_oi": int(a["call_oi"]),
                    "put_oi": int(a["put_oi"]),
                    "call_vol": int(a["call_vol"]),
                    "put_vol": int(a["put_vol"]),
                    "net_gex": round(a["call_gex"] - a["put_gex"], 2),
                })
            return result

        except Exception as e:
            logger.error(f"parse_strikes 失败: {e}", exc_info=True)
            return []

    def extract_and_store_strikes(self, symbol: str, data: dict, db) -> int:
        """B: 解析 + 存储逐 strike 数据到 gex_strikes 表

        调用方:
            fetcher = GEXMetrixFetcher()
            data = fetcher.get_latest_file(symbol)
            n = fetcher.extract_and_store_strikes(symbol, data, db)

        Returns:
            插入行数 (0 = 失败或无数据)
        """
        try:
            strikes = self.parse_strikes(data, min_oi=100)
            if not strikes:
                return 0
            # 找最新 snapshot_id
            existing = db.get_gex_snapshot_latest(symbol)
            if not existing:
                logger.warning(f"  {symbol}: 无对应 gex_snapshots 记录, 跳过 strikes 存储")
                return 0
            return db.insert_gex_strikes(
                snapshot_id=existing["id"],
                symbol=symbol,
                timestamp=existing.get("timestamp", ""),
                strikes=strikes,
            )
        except Exception as e:
            logger.error(f"extract_and_store_strikes 失败 ({symbol}): {e}", exc_info=True)
            return 0


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

        解析 GEXMetrix API 返回的完整快照数据，提取以下字段：
        - net_gex: 净 Gamma Exposure (Call GEX - Put GEX)
        - call_gex: Call 端 Gamma 总值
        - put_gex: Put 端 Gamma 总值
        - zero_gamma_level: 零 Gamma 价位 (做市商对冲方向分界线)
        - call_wall: Call Wall 行权价 (最大 Call GEX 所在价位)
        - put_wall: Put Wall 行权价 (最大 Put GEX 所在价位)
        - spot_price: 现货价格
        - total_gamma: 总 Gamma (|call_gex| + |put_gex|)

        Args:
            data: GEXMetrix API 返回的完整快照 dict

        Returns:
            包含 key metrics 的字典，缺失字段为 None
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

            # 尝试多种常见字段名
            result["spot_price"] = (
                inner.get("spot_price")
                or inner.get("spotPrice")
                or inner.get("price")
                or inner.get("underlying_price")
            )

            result["net_gex"] = (
                inner.get("net_gex")
                or inner.get("netGEX")
                or inner.get("netGamma")
                or inner.get("total_net_gex")
            )

            result["call_gex"] = (
                inner.get("call_gex")
                or inner.get("callGEX")
                or inner.get("total_call_gex")
            )

            result["put_gex"] = (
                inner.get("put_gex")
                or inner.get("putGEX")
                or inner.get("total_put_gex")
            )

            result["zero_gamma_level"] = (
                inner.get("zero_gamma_level")
                or inner.get("zeroGammaLevel")
                or inner.get("zero_gamma")
                or inner.get("gamma_neutral")
                or inner.get("flip_point")
            )

            # Call Wall / Put Wall - 从 strikes 数组或顶层字段提取
            result["call_wall"] = (
                inner.get("call_wall")
                or inner.get("callWall")
                or inner.get("resistance_level")
            )
            result["put_wall"] = (
                inner.get("put_wall")
                or inner.get("putWall")
                or inner.get("support_level")
            )

            # 如果顶层没有，尝试从 strikes 数组推断
            if (result["call_wall"] is None or result["put_wall"] is None):
                strikes = inner.get("strikes", []) or inner.get("levels", [])
                if strikes:
                    # 查找最大 call/put gamma 对应的行权价
                    max_call_strike = None
                    max_call_val = 0
                    max_put_strike = None
                    max_put_val = 0
                    for s in strikes:
                        if isinstance(s, dict):
                            cg = s.get("call_gex") or s.get("callGEX") or s.get("gamma") or 0
                            pg = s.get("put_gex") or s.get("putGEX") or 0
                            strike = s.get("strike") or s.get("strike_price") or 0
                            if cg is None and pg is None:
                                continue
                            if cg and abs(float(cg)) > max_call_val:
                                max_call_val = abs(float(cg))
                                max_call_strike = float(strike)
                            if pg and abs(float(pg)) > max_put_val:
                                max_put_val = abs(float(pg))
                                max_put_strike = float(strike)
                    if result["call_wall"] is None:
                        result["call_wall"] = max_call_strike
                    if result["put_wall"] is None:
                        result["put_wall"] = max_put_strike

            # 如果 call_gex/put_gex 为空但 net_gex 有值，尝试从 strikes 汇总
            if result["call_gex"] is None or result["put_gex"] is None:
                strikes = inner.get("strikes", []) or inner.get("levels", [])
                if strikes:
                    call_sum = 0.0
                    put_sum = 0.0
                    for s in strikes:
                        if isinstance(s, dict):
                            cg = s.get("call_gex") or s.get("callGEX") or s.get("gamma") or 0
                            pg = s.get("put_gex") or s.get("putGEX") or 0
                            if cg:
                                call_sum += float(cg)
                            if pg:
                                put_sum += float(pg)
                    if result["call_gex"] is None and call_sum != 0:
                        result["call_gex"] = call_sum
                    if result["put_gex"] is None and put_sum != 0:
                        result["put_gex"] = put_sum

            # 计算 total_gamma
            if result["call_gex"] is not None and result["put_gex"] is not None:
                result["total_gamma"] = abs(result["call_gex"]) + abs(result["put_gex"])

            # 如果 net_gex 为空但 call_gex 和 put_gex 都有值
            if result["net_gex"] is None and result["call_gex"] is not None and result["put_gex"] is not None:
                result["net_gex"] = result["call_gex"] - abs(result["put_gex"])

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
                    # v2.3: 数据质量验证 (后置, 不阻塞保存)
                    quality = self._enrich_with_quality(symbol, data)
                    success_list[-1]["quality"] = quality
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
                    success_list.append({
                        "symbol": symbol,
                        "filename": fp.name,
                        "timestamp": data.get("timestamp", ""),
                        "file_size": size,
                    })
                    # v2.3: 数据质量验证
                    quality = self._enrich_with_quality(symbol, data)
                    success_list[-1]["quality"] = quality
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
                    success_list.append({
                        "symbol": symbol,
                        "filename": fp.name,
                        "timestamp": data.get("timestamp", ""),
                        "file_size": size,
                    })
                    # v2.3: 数据质量验证
                    quality = self._enrich_with_quality(symbol, data)
                    success_list[-1]["quality"] = quality
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
