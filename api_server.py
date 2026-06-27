"""
多源共振监控系统 - API 服务器 (手动采集模式)
FastAPI REST API + WebSocket + SSE + 前端静态托管

v2.2: 纯手动采集架构
- ⚠ 所有自动数据采集已完全禁用
- EventBus + SignalPipeline 在后台运行 (用于评分入库)
- POST /api/system/collect-manual 为唯一数据获取入口
- 7 数据源: GEX/DIX, VIX, AXLFI暗盘, DBMF, 加密衍生品, 做空数据, GEXMetrix
- OpenCLAW 风格结构化日志输出到 Web 终端
"""
import sys
import os
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from database.db_manager import DatabaseManager
from utils.logger import getLogger

db = DatabaseManager()
logger = logging.getLogger("api_server")
_START_TIME = time.time()

# ═══════════════════════════════════════════════════════════════
# 全局状态: 每日批量采集模式 (盘中高频轮询已移除)
# ═══════════════════════════════════════════════════════════════

# 采集引擎组件 (app 启动时初始化)
_event_bus = None
_signal_pipeline = None
_rest_scheduler = None
_bg_tasks: List[asyncio.Task] = []

# 手动采集历史记录
_last_collect_result: Optional[Dict[str, Any]] = None
_last_manual_collect_time: Optional[datetime] = None
_collect_lock = asyncio.Lock()

app = FastAPI(title="多源共振监控系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== WebSocket ====================
active_connections: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()
            data = _build_dashboard_data()
            await ws.send_json(data)
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        active_connections.remove(ws)
    except Exception:
        if ws in active_connections:
            active_connections.remove(ws)


# ==================== Auth ====================
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    if req.username == "admin" and req.password == "admin":
        return {
            "access_token": "eyJhbGciOiJIUzI1NiJ9.dummy",
            "refresh_token": "eyJhbGciOiJIUzI1NiJ9.dummy-refresh",
            "token_type": "bearer",
        }
    raise HTTPException(status_code=401, detail="用户名或密码错误")


# ==================== Health & Metrics ====================
@app.get("/api/health")
async def health_check():
    """Docker 健康检查 + 负载均衡器探活"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
    }


@app.get("/api/metrics")
async def metrics():
    """Prometheus 指标端点"""
    import psutil
    metrics_lines = [
        "# HELP resonance_up 服务运行状态 (1=运行中)",
        "# TYPE resonance_up gauge",
        "resonance_up 1",
        "# HELP resonance_ws_connections 活跃 WebSocket 连接数",
        "# TYPE resonance_ws_connections gauge",
        f"resonance_ws_connections {len(active_connections)}",
        "# HELP resonance_memory_bytes 内存使用 (字节)",
        "# TYPE resonance_memory_bytes gauge",
        f"resonance_memory_bytes {psutil.Process().memory_info().rss}",
        "# HELP resonance_cpu_percent CPU 使用率 (%)",
        "# TYPE resonance_cpu_percent gauge",
        f"resonance_cpu_percent {psutil.Process().cpu_percent(interval=0.1)}",
    ]
    return StreamingResponse(
        iter(metrics_lines),
        media_type="text/plain; charset=utf-8",
    )


# ==================== Dashboard ====================
@app.get("/api/dashboard/scores")
async def dashboard_scores():
    return _build_dashboard_data()


@app.get("/api/dashboard/recent-alerts")
async def recent_alerts(limit: int = Query(5)):
    try:
        alerts = db.get_recent_alerts(limit)
    except Exception:
        alerts = []
    result = []
    for a in alerts:
        result.append({
            "id": a.get("id", 0) if isinstance(a, dict) else (a[0] if a else 0),
            "alert_level": a.get("alert_level", "NO_SIGNAL") if isinstance(a, dict) else (a[7] if len(a) > 7 else "NO_SIGNAL"),
            "total_score": a.get("total_score", 0) if isinstance(a, dict) else (a[2] if len(a) > 2 else 0),
            "trigger_time": str(a.get("trigger_time", "")) if isinstance(a, dict) else str(a[2] if len(a) > 2 else ""),
            "acknowledged": bool(a.get("acknowledged", False)) if isinstance(a, dict) else bool(a[9] if len(a) > 9 else False),
        })
    return result


# ==================== GEX ====================
@app.get("/api/gex/history")
async def gex_history(days: int = Query(90)):
    rows = db.get_gex_history_days(days)
    return [_gex_row(r) for r in rows]


@app.get("/api/dashboard/gex-curve")
async def gex_curve(days: int = Query(30)):
    """GEX 曲线数据: 含 Put Wall / Flip Zone 用于前端绘图"""
    rows = db.get_gex_history_days(days)
    parsed = [_gex_row(r) for r in (rows or [])]
    return {
        "timestamps": [p["timestamp"] for p in parsed],
        "gex_calibrated": [p["gex_calibrated"] for p in parsed],
        "put_wall_level": [p["put_wall_level"] for p in parsed],
        "flip_zone_lower": [p["flip_zone_lower"] for p in parsed],
        "flip_zone_upper": [p["flip_zone_upper"] for p in parsed],
    }


# ==================== VIX ====================
@app.get("/api/vix/history")
async def vix_history(days: int = Query(90)):
    rows = db.get_vix_history(days)
    return [_vix_row(r) for r in rows]


# ==================== Darkpool ====================
@app.get("/api/darkpool/history")
async def darkpool_history(days: int = Query(90), ticker: str = Query("SPY")):
    rows = db.get_darkpool_history_list(days)
    return [_darkpool_row(r) for r in rows]


# ==================== GEXMetrix Gamma Dashboard ====================
@app.get("/api/gex/symbols")
async def gex_symbols():
    """获取所有 GEXMetrix 可用标的及数据新鲜度

    Returns:
        list: 每个标的最新快照时间、数据年龄(分钟)、快照数量
    """
    try:
        symbols = db.get_gex_snapshot_symbols()
        result = []
        for s in symbols:
            result.append({
                "symbol": s.get("symbol", ""),
                "latest_timestamp": str(s.get("latest_timestamp", "")),
                "snapshot_count": s.get("snapshot_count", 0),
                "age_minutes": s.get("age_minutes"),
            })
        return result
    except Exception as e:
        logger.error(f"GEX symbols 查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/summary")
async def gex_summary():
    """获取 GEXMetrix 全局摘要状态

    Returns:
        dict: total_symbols, latest_update, total_snapshots, symbols 列表
    """
    try:
        return db.get_gex_snapshot_summary()
    except Exception as e:
        logger.error(f"GEX summary 查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/{symbol}/latest")
async def gex_symbol_latest(symbol: str):
    """获取指定标的最新 GEX 关键指标 (精简数据, 不返回原始 JSON)

    对于大标 (SPX/SPY/QQQ), 只返回解析后的精简数据以节省带宽。

    Args:
        symbol: 标的代码 (如 SPX, SPY, QQQ, NDX 等)

    Returns:
        dict: net_gex, call_gex, put_gex, zero_gamma_level,
              call_wall, put_wall, spot_price, total_gamma, timestamp
    """
    try:
        snapshot = db.get_gex_snapshot_latest(symbol)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"No data for symbol: {symbol}")

        return {
            "symbol": snapshot.get("symbol", symbol.upper()),
            "timestamp": str(snapshot.get("timestamp", "")),
            "net_gex": snapshot.get("net_gex"),
            "call_gex": snapshot.get("call_gex"),
            "put_gex": snapshot.get("put_gex"),
            "zero_gamma_level": snapshot.get("zero_gamma_level"),
            "call_wall": snapshot.get("call_wall"),
            "put_wall": snapshot.get("put_wall"),
            "spot_price": snapshot.get("spot_price"),
            "total_gamma": snapshot.get("total_gamma"),
            "file_size": snapshot.get("file_size"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GEX latest 查询失败 ({symbol}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/{symbol}/history")
async def gex_symbol_history(symbol: str, days: int = Query(7, ge=1, le=90)):
    """获取指定标的历史 Net GEX 时间序列

    Args:
        symbol: 标的代码
        days: 查询天数 (1-90, 默认 7)

    Returns:
        list: 按时间升序的 [timestamp, net_gex, spot_price] 序列
    """
    try:
        rows = db.get_gex_snapshot_history(symbol, days)
        result = []
        for r in rows:
            result.append({
                "timestamp": str(r.get("timestamp", "")),
                "net_gex": r.get("net_gex"),
                "spot_price": r.get("spot_price"),
            })
        return result
    except Exception as e:
        logger.error(f"GEX history 查询失败 ({symbol}, {days}d): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/{symbol}/levels")
async def gex_symbol_levels(symbol: str):
    """获取指定标的关键价位 (Zero Gamma / Call Wall / Put Wall)

    Args:
        symbol: 标的代码

    Returns:
        dict: zero_gamma_level, call_wall, put_wall, spot_price, net_gex, timestamp
    """
    try:
        levels = db.get_gex_snapshot_levels(symbol)
        if not levels:
            raise HTTPException(status_code=404, detail=f"No levels data for symbol: {symbol}")

        return {
            "symbol": levels.get("symbol", symbol.upper()),
            "timestamp": str(levels.get("timestamp", "")),
            "zero_gamma_level": levels.get("zero_gamma_level"),
            "call_wall": levels.get("call_wall"),
            "put_wall": levels.get("put_wall"),
            "spot_price": levels.get("spot_price"),
            "net_gex": levels.get("net_gex"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GEX levels 查询失败 ({symbol}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/{symbol}/strikes")
async def gex_symbol_strikes(symbol: str, limit: int = Query(200, ge=10, le=600)):
    """B: 获取标的逐 strike 真实 GEX/OI 分布

    Args:
        symbol: 标的代码
        limit: ATM 附近最多返回多少 strike (默认 200, 最大 600)

    Returns:
        dict: symbol, timestamp, spot_price, strikes[]
        strikes[i]: {strike, call_gex, put_gex, call_oi, put_oi, call_vol, put_vol, net_gex}
    """
    try:
        strikes = db.get_gex_strikes(symbol.upper(), snapshot_id=None, limit_strikes=limit)
        if not strikes:
            raise HTTPException(status_code=404, detail=f"No strike data for symbol: {symbol}")
        # 取 snapshot 时间戳和 spot
        snap = db.get_gex_snapshot_latest(symbol.upper())
        ts = str(snap.get("timestamp", "")) if snap else ""
        spot = snap.get("spot_price") if snap else None
        return {
            "symbol": symbol.upper(),
            "timestamp": ts,
            "spot_price": spot,
            "strikes": strikes,
            "strike_count": len(strikes),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GEX strikes 查询失败 ({symbol}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gex/{symbol}/dashboard-view")
async def gex_symbol_dashboard_view(
    symbol: str,
    history_days: int = Query(3, ge=1, le=7, description="历史 Net GEX 时间序列天数 (1-7, 仅 GEXMetrix 数据)"),
    long_days: int = Query(90, ge=30, le=365, description="SqueezeMetrics 90天回填数据天数"),
    strikes_limit: int = Query(200, ge=10, le=600),
):
    """C: BFF 聚合接口 - Gamma Dashboard 一次拿到全部数据

    一次返回 5 类数据, 替代前端 5 个 useQuery:
    1. latest: 最新 GEXMetrix 快照摘要 (net_gex/call_gex/put_gex/walls/spot)
    2. levels: 关键价位 (call_wall/put_wall/zero_gamma/flip_zones)
    3. history: GEXMetrix Net GEX 时间序列 (history_days)
    4. long_history: SqueezeMetrics 90天日级 Net GEX (long_days)
    5. strikes: 真实逐 strike 分布 (ATM 附近 strikes_limit 个)
    6. symbols: 所有可用标的列表 + 数据新鲜度

    Args:
        symbol: 标的代码 (如 SPY)
        history_days: GEXMetrix 短期窗口 (默认 3 天)
        long_days: SqueezeMetrics 长期窗口 (默认 90 天)
        strikes_limit: ATM 附近 strike 数量上限

    Returns:
        dict: { symbol, latest, levels, history, long_history, strikes, symbols, fetched_at }
    """
    try:
        sym = symbol.upper()
        result: Dict[str, Any] = {
            "symbol": sym,
            "fetched_at": datetime.now().isoformat(),
        }

        # 1. latest (gex_snapshots 最新一行)
        try:
            latest = db.get_gex_snapshot_latest(sym)
            result["latest"] = latest
        except Exception as e:
            logger.warning(f"  {sym} latest 失败: {e}")
            result["latest"] = None

        # 2. levels (从 latest 提取关键价位)
        if result["latest"]:
            r = result["latest"]
            result["levels"] = {
                "call_wall": r.get("call_wall"),
                "put_wall": r.get("put_wall"),
                "zero_gamma_level": r.get("zero_gamma_level"),
                "spot_price": r.get("spot_price"),
                "net_gex": r.get("net_gex"),
                "call_gex": r.get("call_gex"),
                "put_gex": r.get("put_gex"),
            }
        else:
            result["levels"] = None

        # 3. history (gex_snapshots 时间序列)
        try:
            history = db.get_gex_snapshot_history(sym, days=history_days)
            result["history"] = history
        except Exception as e:
            logger.warning(f"  {sym} history 失败: {e}")
            result["history"] = []

        # 4. long_history (gex_history SqueezeMetrics 90 天)
        try:
            # SqueezeMetrics 表目前只有 SPX (历史回填项目), 非 SPX 直接空
            if sym != "SPX":
                result["long_history"] = []
            else:
                long_rows = db.get_gex_history_days(long_days)
                # get_gex_history_days 返回 sqlite3.Row 列表, 转 dict
                result["long_history"] = [dict(r) for r in long_rows]
        except Exception as e:
            logger.warning(f"  {sym} long_history 失败: {e}")
            result["long_history"] = []

        # 5. strikes (逐 strike 真实数据)
        try:
            strikes = db.get_gex_strikes(sym, snapshot_id=None, limit_strikes=strikes_limit)
            result["strikes"] = {
                "timestamp": str(result["latest"].get("timestamp", "")) if result["latest"] else "",
                "spot_price": result["latest"].get("spot_price") if result["latest"] else None,
                "strikes": strikes,
                "strike_count": len(strikes),
            }
        except Exception as e:
            logger.warning(f"  {sym} strikes 失败: {e}")
            result["strikes"] = {"strikes": [], "strike_count": 0}

        # 6. symbols (标的列表)
        try:
            syms = db.get_gex_snapshot_symbols()
            result["symbols"] = syms
        except Exception as e:
            logger.warning(f"  symbols 失败: {e}")
            result["symbols"] = []

        return result
    except Exception as e:
        logger.error(f"dashboard-view 失败 ({symbol}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Cross-Asset & Resonance History ====================
@app.get("/api/dashboard/cross-asset-heatmap")
async def cross_asset_heatmap():
    """跨资产共振热力图: 4×4 资产间 Pairwise 方向一致性矩阵"""
    try:
        gex = db.get_latest_gex() or {}
        vix = db.get_latest_vix_analysis() or {}
        crypto = db.get_latest_crypto_data() or {}
        dp = db.get_latest_dark_pool_metrics() or {}
    except Exception:
        gex, vix, crypto, dp = {}, {}, {}, {}

    # 归一化各资产信号到 [-1, 1]
    def _safe(v, default=0):
        return v if v is not None else default

    gx_val = _safe(gex.get("gex_calibrated") if isinstance(gex, dict) else 0)
    gx_signal = 1.0 if gx_val > 500_000_000 else (-1.0 if gx_val < -500_000_000 else gx_val / 500_000_000)

    vx_val = _safe(vix.get("panic_premium") if isinstance(vix, dict) else 0)
    vx_signal = 1.0 if vx_val < -5 else (-1.0 if vx_val > 5 else -vx_val / 5)

    oi_val = _safe(crypto.get("btc_oi") if isinstance(crypto, dict) else 0)
    oi_signal = 0.5 if oi_val > 0 else -0.5

    dix_val = _safe(dp.get("dix_value") if isinstance(dp, dict) else 0)
    dix_signal = 1.0 if dix_val > 45 else (-1.0 if dix_val < 35 else (dix_val - 40) / 5)

    # Build pairwise alignment matrix
    assets = ["GEX", "VIX", "Crypto", "Darkpool"]
    signals = {"GEX": gx_signal, "VIX": vx_signal, "Crypto": oi_signal, "Darkpool": dix_signal}

    matrix = []
    for a in assets:
        row = []
        for b in assets:
            if a == b:
                row.append(1.0)
            else:
                sa, sb = signals[a], signals[b]
                row.append(round(sa * sb if sa * sb > 0 else sa * sb * 0.5, 3))
        matrix.append(row)

    return {
        "assets": assets,
        "signals": [round(signals[a], 3) for a in assets],
        "matrix": matrix,
        "overall_coherence": round(sum(abs(sum(row) - 1) for row in matrix) / 16 * 100, 1),
    }


@app.get("/api/dashboard/resonance-history")
async def resonance_history(days: int = Query(30)):
    """共振得分历史趋势: 从 signal_alerts 或 gateway_snapshots 获取"""
    try:
        rows = db.get_signal_history(days, 1, 200)
    except Exception:
        rows = []
    result = []
    for r in (rows or []):
        d = _row_to_dict(r)
        result.append({
            "timestamp": str(d.get("trigger_time", "")),
            "total_score": d.get("total_score", 0.0) or 0.0,
            "alert_level": d.get("alert_level", "NO_SIGNAL") or "NO_SIGNAL",
        })
    # 按时间排序
    result.sort(key=lambda x: x["timestamp"])
    return result


# ==================== Signals ====================
@app.get("/api/signals/current")
async def current_signal():
    s = db.get_latest_signal()
    if not s:
        return {"total_score": 0, "alert_level": "NO_SIGNAL", "trigger_time": ""}
    return {
        "id": s.get("id"),
        "trigger_time": str(s.get("trigger_time", "")),
        "total_score": s.get("total_score", 0),
        "alert_level": s.get("alert_level", "NO_SIGNAL"),
        "acknowledged": bool(s.get("acknowledged", False)),
    }


@app.get("/api/signals/history")
async def signal_history(
    days: int = Query(30),
    page: int = Query(1),
    page_size: int = Query(50),
):
    rows = db.get_signal_history(days, page, page_size)
    total = db.get_signal_count(days)
    data = []
    for r in rows:
        d = _row_to_dict(r)
        data.append({
            "id": d.get("id"),
            "trigger_time": str(d.get("trigger_time", "")),
            "total_score": d.get("total_score", 0),
            "alert_level": d.get("alert_level", "NO_SIGNAL"),
            "dimension_scores": {"gex": 0, "vix": 0, "crypto": 0, "darkpool": 0},
            "hawkes_branching_ratio": d.get("hawkes_branching_ratio", 0),
            "acknowledged": bool(d.get("acknowledged", False)),
            "trigger_count": 1,
        })
    return {"data": data, "total": total, "page": page, "page_size": page_size}


@app.post("/api/signals/{id}/acknowledge")
async def acknowledge_signal(id: int):
    db.acknowledge_signal(id)
    return {"ok": True}


# ==================== Alerts ====================
@app.get("/api/alerts")
async def alerts(
    page: int = Query(1),
    page_size: int = Query(20),
    level: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
):
    rows = db.get_alerts(page, page_size, level, acknowledged)
    total = db.get_alerts_count(level, acknowledged)
    data = []
    for r in rows:
        d = _row_to_dict(r)
        data.append({
            "id": d.get("id"),
            "trigger_time": str(d.get("trigger_time", "")),
            "total_score": d.get("total_score", 0),
            "alert_level": d.get("alert_level", "NO_SIGNAL"),
            "dimension_scores": {},
            "resonance_pct": 0,
            "hawkes_branching_ratio": d.get("hawkes_branching_ratio", 0),
            "acknowledged": bool(d.get("acknowledged", False)),
        })
    return {"data": data, "total": total, "page": page, "page_size": page_size}


@app.post("/api/alerts/{id}/acknowledge")
async def acknowledge_alert(id: int):
    db.acknowledge_alert(id)
    return {"ok": True}


# ==================== System (手动采集模式) ====================

class AutoPollingRequest(BaseModel):
    enabled: bool


@app.get("/api/system/auto-polling")
async def get_auto_polling():
    """获取自动采集调度状态 — 盘中轮询已移除，统一为每日 ET 20:00 批量模式"""
    return {"enabled": False, "mode": "daily_batch", "batch_time": "20:00 ET"}


@app.put("/api/system/auto-polling")
async def set_auto_polling(req: AutoPollingRequest):
    """设置自动采集调度 — 盘中轮询已移除，统一为每日 ET 20:00 批量模式"""
    logger.info("[AUTO_POLLING] 盘中轮询已移除, 统一为每日批量模式 (requested=%s)", req.enabled)
    return {"ok": True, "enabled": False, "mode": "daily_batch", "message": "盘中轮询已移除，系统使用每日美东 20:00 批量采集"}


@app.post("/api/system/collect-manual")
async def manual_collect():
    """手动触发一次完整的 7 数据源采集循环
    
    采集维度: GEX/DIX, VIX 期限结构, AXLFI 暗盘, DBMF 均线,
              加密衍生品 (Hyperliquid→CCData), 做空数据 (yfinance→FINRA),
              GEXMetrix Gamma Dashboard
    
    数据流: RESTPollScheduler → EventBus → SignalPipeline → 评分 → DB 入库
    
    Returns:
        dict: 每个数据源的采集结果、成功/失败状态和耗时
    """
    global _last_collect_result, _last_manual_collect_time

    if _rest_scheduler is None:
        raise HTTPException(status_code=503, detail="采集引擎未初始化，请等待服务完全启动")

    async with _collect_lock:
        start_ts = time.time()

        # 使用 RESTPollScheduler 的 run_once_manual_collect
        # 这会通过 EventBus → SignalPipeline 完成评分入库
        try:
            result = await _rest_scheduler.run_once_manual_collect()
        except Exception as e:
            logger.error("[COLLECT] 手动采集异常: %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail=f"采集失败: {str(e)}")

        _last_collect_result = result
        _last_manual_collect_time = datetime.now()

        total_elapsed = round(time.time() - start_ts, 2)
        result["total_elapsed_sec"] = total_elapsed
        result["collected_at"] = _last_manual_collect_time.isoformat()
        result["ok"] = result.get("success_count", 0) > 0

        return result


@app.get("/api/system/source-status")
async def source_status():
    """获取数据源连通性状态 (手动采集模式)"""
    now = datetime.now().isoformat()
    last_manual = _last_manual_collect_time.isoformat() if _last_manual_collect_time else None

    # 基于上一次手动采集结果构建动态状态
    sources = []
    if _last_collect_result:
        for src in _last_collect_result.get("sources", []):
            status = "ONLINE" if src.get("status") == "success" else "OFFLINE"
            sources.append({
                "name": src.get("name", ""),
                "status": status,
                "method": "MANUAL",
                "availability_pct": 100 if status == "ONLINE" else 0,
                "failure_count": 0 if status == "ONLINE" else 1,
                "last_updated": last_manual or now,
                "last_elapsed_sec": src.get("elapsed_sec", 0),
                "last_error": src.get("error") if status == "OFFLINE" else None,
            })
    else:
        # 尚未执行过手动采集 — 显示待采集状态
        default_sources = [
            "GEX/DIX", "VIX期限结构", "AXLFI暗盘", "DBMF均线", "加密衍生品", "做空数据", "GEXMetrix",
        ]
        sources = [
            {"name": name, "status": "DEGRADED", "method": "MANUAL",
             "availability_pct": 0, "failure_count": 0, "last_updated": None,
             "last_elapsed_sec": None, "last_error": None}
            for name in default_sources
        ]

    return {
        "auto_polling_enabled": False,
        "mode": "manual_only",
        "last_manual_collect": last_manual,
        "last_collect_summary": _last_collect_result.get("summary") if _last_collect_result else None,
        "sources": sources,
        "degradation_mode": _last_collect_result is None,
        "degradation_details": {
            "failed_sources": [
                s.get("name") for s in (_last_collect_result.get("sources", []) if _last_collect_result else [])
                if s.get("status") != "success"
            ],
            "circuit_breaker_states": {},
        },
        "scheduler_running": False,  # 无自动调度任务
        "db_size_mb": round(os.path.getsize(Path(__file__).parent / "database" / "monitoring.db") / (1024 * 1024), 1) if (Path(__file__).parent / "database" / "monitoring.db").exists() else 0,
        "last_backup_time": (datetime.now() - timedelta(hours=2)).isoformat(),
    }


# ==================== Config ====================
@app.get("/api/config")
async def get_config():
    return {
        "thresholds": {"DIX_THRESHOLD": 0.4, "GEX_THRESHOLD": 0.7, "MIN_SIGNAL_STRENGTH": 0.5},
        "fetch_intervals": {"intraday": 300, "after_hours": 3600},
        "notifications": {"email_recipients": "", "telegram_token": "********", "telegram_chat_id": "850492903", "discord_webhook": "********"},
        "cooldown_minutes": 30,
    }


@app.put("/api/config")
async def update_config():
    return {"ok": True, "message": "配置已保存"}


# ==================== Tickers ====================
@app.get("/api/tickers")
async def get_tickers():
    return [
        {"symbol": "SPY", "name": "S&P 500 ETF"},
        {"symbol": "QQQ", "name": "Nasdaq-100 ETF"},
        {"symbol": "IWM", "name": "Russell 2000 ETF"},
        {"symbol": "AAPL", "name": "Apple Inc."},
        {"symbol": "MSFT", "name": "Microsoft Corp."},
        {"symbol": "NVDA", "name": "NVIDIA Corp."},
        {"symbol": "TSLA", "name": "Tesla Inc."},
        {"symbol": "AMD", "name": "Advanced Micro Devices"},
    ]


# ==================== Notifications ====================
class NotificationTestRequest(BaseModel):
    channel: str  # email / telegram / discord


class NotificationConfigRequest(BaseModel):
    cooldown_minutes: Optional[int] = None
    dnd_start: Optional[str] = None  # "HH:MM" format
    dnd_end: Optional[str] = None
    min_interval_same_level: Optional[int] = None


@app.get("/api/notifications/status")
async def notification_status():
    return {
        "channels": [
            {"name": "Email", "connected": True, "last_test": (datetime.now() - timedelta(minutes=5)).isoformat()},
            {"name": "Telegram", "connected": True, "last_test": (datetime.now() - timedelta(minutes=10)).isoformat()},
            {"name": "Discord", "connected": False, "last_test": None},
        ]
    }


@app.post("/api/notifications/test")
async def notification_test(req: NotificationTestRequest):
    return {"ok": True, "channel": req.channel, "message": f"测试消息已通过 {req.channel} 发送"}


@app.get("/api/notifications/config")
async def notification_config_get():
    return {
        "cooldown_minutes": 30,
        "dnd_start": None,
        "dnd_end": None,
        "min_interval_same_level": 15,
    }


@app.put("/api/notifications/config")
async def notification_config_put(req: NotificationConfigRequest):
    return {"ok": True, "updated": req.model_dump(exclude_none=True)}


# ==================== Incidents (聚合告警) ====================
@app.get("/api/incidents")
async def incidents(days: int = Query(7)):
    """返回最近 N 天的 Incident 聚合列表"""
    now = datetime.now()
    return {
        "incidents": [
            {
                "id": 14,
                "title": "盘中异常抛售事件",
                "start_time": (now - timedelta(hours=3)).isoformat(),
                "end_time": (now - timedelta(minutes=2)).isoformat(),
                "highest_level": "LEVEL_3",
                "highest_score": 4.8,
                "trigger_count": 7,
                "reviewed": False,
            },
            {
                "id": 13,
                "title": "GEX翻转 + VIX期限结构异常",
                "start_time": (now - timedelta(days=1, hours=4)).isoformat(),
                "end_time": (now - timedelta(days=1)).isoformat(),
                "highest_level": "LEVEL_2",
                "highest_score": 3.2,
                "trigger_count": 3,
                "reviewed": True,
            },
        ]
    }


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: int):
    return {
        "id": incident_id,
        "title": "盘中异常抛售事件",
        "start_time": (datetime.now() - timedelta(hours=3)).isoformat(),
        "end_time": (datetime.now() - timedelta(minutes=2)).isoformat(),
        "highest_level": "LEVEL_3",
        "highest_score": 4.8,
        "triggers": [
            {"id": 101, "trigger_time": (datetime.now() - timedelta(minutes=2)).isoformat(), "alert_level": "LEVEL_3", "total_score": 4.8, "dimension_names": ["GEX", "VIX", "Crypto", "Darkpool"]},
            {"id": 100, "trigger_time": (datetime.now() - timedelta(minutes=45)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.2, "dimension_names": ["VIX", "Darkpool"]},
            {"id": 99, "trigger_time": (datetime.now() - timedelta(hours=1, minutes=30)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.1, "dimension_names": ["GEX", "VIX"]},
            {"id": 98, "trigger_time": (datetime.now() - timedelta(hours=2)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.5, "dimension_names": ["GEX", "Darkpool"]},
            {"id": 97, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=15)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.5, "dimension_names": ["GEX"]},
            {"id": 96, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=30)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.2, "dimension_names": ["VIX"]},
            {"id": 95, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=45)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.8, "dimension_names": ["GEX", "Crypto"]},
        ],
    }


@app.put("/api/incidents/{incident_id}/review")
async def review_incident(incident_id: int):
    """标记 Incident 为已复盘"""
    logger.info(f"[INCIDENT] 标记 Incident #{incident_id} 为已复盘")
    return {"ok": True, "id": incident_id, "reviewed": True}


@app.get("/api/incidents/{incident_id}/export")
async def export_incident(incident_id: int):
    """导出单个 Incident 完整报告 (JSON)"""
    return {
        "incident_id": incident_id,
        "title": "盘中异常抛售事件",
        "start_time": (datetime.now() - timedelta(hours=3)).isoformat(),
        "end_time": (datetime.now() - timedelta(minutes=2)).isoformat(),
        "highest_level": "LEVEL_3",
        "highest_score": 4.8,
        "trigger_count": 7,
        "export_time": datetime.now().isoformat(),
        "triggers": [
            {"id": 101, "trigger_time": (datetime.now() - timedelta(minutes=2)).isoformat(), "alert_level": "LEVEL_3", "total_score": 4.8, "dimension_names": ["GEX", "VIX", "Crypto", "Darkpool"]},
            {"id": 100, "trigger_time": (datetime.now() - timedelta(minutes=45)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.2, "dimension_names": ["VIX", "Darkpool"]},
            {"id": 99, "trigger_time": (datetime.now() - timedelta(hours=1, minutes=30)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.1, "dimension_names": ["GEX", "VIX"]},
            {"id": 98, "trigger_time": (datetime.now() - timedelta(hours=2)).isoformat(), "alert_level": "LEVEL_2", "total_score": 3.5, "dimension_names": ["GEX", "Darkpool"]},
            {"id": 97, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=15)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.5, "dimension_names": ["GEX"]},
            {"id": 96, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=30)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.2, "dimension_names": ["VIX"]},
            {"id": 95, "trigger_time": (datetime.now() - timedelta(hours=2, minutes=45)).isoformat(), "alert_level": "LEVEL_1", "total_score": 2.8, "dimension_names": ["GEX", "Crypto"]},
        ],
    }


# ==================== LLM 分析 API ====================
from config.settings import Config as AppSettingsConfig
_settings_cfg = AppSettingsConfig()

@app.get("/api/llm/status")
async def llm_status():
    """获取 LLM 配置状态"""
    llm_configured = bool(_settings_cfg.OPENAI_API_KEY and len(str(_settings_cfg.OPENAI_API_KEY)) > 10)
    return {
        "configured": llm_configured,
        "provider": _settings_cfg.LLM_PROVIDER,
        "model": _settings_cfg.OPENAI_MODEL,
    }

class LLMAnalyzeRequest(BaseModel):
    asset: str = "SPX"

@app.post("/api/llm/analyze")
async def llm_analyze(request: LLMAnalyzeRequest):
    """触发 LLM 对当前监控数据进行策略分析"""
    if not _settings_cfg.OPENAI_API_KEY or len(str(_settings_cfg.OPENAI_API_KEY)) < 10:
        raise HTTPException(status_code=400, detail="LLM 未配置: 缺少 OPENAI_API_KEY")
    
    try:
        from llm_inference.openai_provider import OpenAIProvider
        from llm_inference.prompt_builder import PromptBuilder
        from llm_inference.response_parser import ResponseParser, StrategyBriefing
        from gateway.schemas import GatewayEnvelope, ResonanceSnapshot
        
        # 构建 demo/snapshot 数据
        snapshot = ResonanceSnapshot(
            underlying_asset=request.asset,
            timestamp=datetime.now().isoformat(),
            data_quality_flag="NORMAL",
            available_dimensions=5,
            missing_dimensions=[],
            resonance_intensity_score=65,
            resonance_signal_state="Strong",
            net_gamma_regime="Positive Gamma",
            gamma_flip_level=5150.0,
            gamma_flip_proximity_pct=3.2,
            gex_percentile=72.0,
            core_support_wall=4800.0,
            core_resistance_wall=5200.0,
            support_wall_strength="Strong",
            dark_pool_dix_status="ELEVATED",
            dark_pool_accumulation_regime="ACCUMULATION",
            dix_percentile=85.0,
            vix_term_structure_state="CONTANGO",
            vix_panic_premium_pct=-3.2,
            vanna_exposure_bias="NEUTRAL",
            crypto_leverage_state="LEVERAGE_BUILDUP",
            crypto_oi_change_pct=-2.5,
            hawkes_branching_state="SUB_CRITICAL",
            hawkes_branching_ratio=0.45,
            cross_asset_coherence_score=65.0,
            cross_asset_alignment_direction="BULLISH",
            cross_asset_resonance_strength="Moderate",
        )
        
        envelope = GatewayEnvelope(
            schema_version="2.1.0",
            snapshot=snapshot,
            pipeline_run_id="api-on-demand",
            created_at=datetime.now().isoformat(),
        )
        
        # 构建 LLM Provider
        base_url = _settings_cfg.OPENAI_BASE_URL if str(_settings_cfg.OPENAI_BASE_URL).strip() else None
        provider = OpenAIProvider(
            api_key=_settings_cfg.OPENAI_API_KEY,
            model=_settings_cfg.OPENAI_MODEL,
            base_url=base_url,
            temperature=_settings_cfg.LLM_TEMPERATURE,
            max_tokens=_settings_cfg.LLM_MAX_TOKENS,
            timeout=_settings_cfg.LLM_TIMEOUT,
        )
        
        builder = PromptBuilder(language="zh")
        system_prompt = builder.build_system_prompt()
        user_prompt = builder.build_user_prompt(envelope)
        
        # 调用 LLM (async -> sync via asyncio.run 内部适配)
        response = await provider.generate(user_prompt, system_prompt)
        
        # 解析输出
        briefing: StrategyBriefing = ResponseParser.parse_strategy_briefing(response.content)
        hallu_flags = ResponseParser.detect_hallucination(response.content, envelope)
        briefing.hallucination_flags = hallu_flags
        
        # 生成完整报告
        from llm_inference.report_composer import ReportComposer
        composer = ReportComposer(output_dir="./reports")
        report_md = composer.compose_full_report(envelope, briefing, pipeline_run_id="api-on-demand")
        
        return {
            "report_markdown": report_md,
            "briefing": {
                "full_text": briefing.full_text or response.content,
                "summary": briefing.overview or "",
                "conviction_level": snapshot.resonance_signal_state,
                "risk_assessment": "",
                "key_levels": [
                    {"level": snapshot.core_support_wall, "label": "核心支撑 (Put Wall)", "significance": snapshot.support_wall_strength},
                    {"level": snapshot.core_resistance_wall, "label": "核心阻力 (Call Wall)", "significance": "关键反转区"},
                    {"level": snapshot.gamma_flip_level, "label": "Gamma 翻转点", "significance": "做市商持仓转折点"},
                ],
                "scenario": "",
                "positions": "",
                "hedging": "",
                "has_hallucination": briefing.has_hallucination,
                "hallucination_flags": hallu_flags,
            },
            "tokens": response.total_tokens,
            "latency_ms": response.latency_ms,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LLM 分析失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"LLM 分析失败: {str(e)}")

# ==================== SSE 日志流 (OpenCLAW 风格) ====================
import aiofiles

# 日志文件路径 — 使用 api_server 自身的日志文件 (手动采集日志输出到此)
_LOG_PATH = Path(__file__).parent / "logs" / f"app_{datetime.now().strftime('%Y%m%d')}.log"

# 全局状态：当前客户端数 & 文件偏移
_log_clients = 0
_log_tail_lock = asyncio.Lock()


def _map_log_level(line: str) -> str:
    """从日志行提取级别映射到前端 level"""
    if "[ERROR" in line or "ERROR  ]" in line:
        return "ERROR"
    if "[WARNING" in line or "WARN  ]" in line:
        return "WARN"
    if "✓" in line and ("成功" in line or "完成" in line):
        return "SUCCESS"
    return "INFO"


def _get_log_path() -> Path:
    """获取当前日期的日志文件路径"""
    return Path(__file__).parent / "logs" / f"app_{datetime.now().strftime('%Y%m%d')}.log"


async def log_event_generator():
    """SSE 事件生成器 — 实时 tail 日志文件 (OpenCLAW 格式)"""
    global _log_clients, _LOG_PATH
    _log_clients += 1
    try:
        # 更新日志路径 (跨日期)
        _LOG_PATH = _get_log_path()
        async with _log_tail_lock:
            if _LOG_PATH.exists():
                async with aiofiles.open(_LOG_PATH, "r", encoding="utf-8") as f:
                    await f.seek(0, os.SEEK_END)
        while True:
            # 检查日志文件是否切换 (跨日)
            current_log = _get_log_path()
            if current_log != _LOG_PATH:
                _LOG_PATH = current_log
            if _LOG_PATH.exists():
                async with aiofiles.open(_LOG_PATH, "r", encoding="utf-8") as f:
                    await f.seek(0, os.SEEK_END)
                    while True:
                        line = await f.readline()
                        if line:
                            level = _map_log_level(line)
                            yield f"data: {json.dumps({'line': line.rstrip(), 'level': level})}\n\n"
                        else:
                            await asyncio.sleep(1)
            else:
                yield f"data: {json.dumps({'line': '[  INFO  ] 等待日志文件...', 'level': 'INFO'})}\n\n"
                await asyncio.sleep(5)
    finally:
        _log_clients -= 1


@app.get("/api/system/logs/stream")
async def logs_stream():
    return StreamingResponse(log_event_generator(), media_type="text/event-stream")


# ==================== 应用生命周期 (EventBus + SignalPipeline 初始化) ====================

@app.on_event("startup")
async def startup_event():
    """启动采集引擎的后台评分组件 (EventBus + SignalPipeline)
    
    ⚠ 不启动自动轮询 — 数据获取通过以下方式触发:
      1. 每日定时批量采集 (main_stream.py / StreamEngine, 美东 20:00)
      2. 前端手动采集 (POST /api/system/collect-manual)
    EventBus 和 SignalPipeline 在后台运行，用于接收数据并评分入库。
    """
    global _event_bus, _signal_pipeline, _rest_scheduler

    logger.info("=" * 54)
    logger.info("  多源共振监控系统 API 服务器 v2.2 (每日批量+手动采集)")
    logger.info("=" * 54)

    try:
        from data_stream.event_bus import EventBus, get_event_bus
        from data_stream.signal_pipeline import SignalPipeline
        from data_stream.rest_poll_scheduler import RESTPollScheduler

        # 1. 创建 EventBus
        _event_bus = get_event_bus()

        # 2. 创建 SignalPipeline (订阅 EventBus，负责评分入库)
        _signal_pipeline = SignalPipeline(_event_bus)

        # 3. 创建 RESTPollScheduler (仅用于手动一次采集，不启动自动轮询)
        _rest_scheduler = RESTPollScheduler(_event_bus)

        # 4. 启动 EventBus 分发
        await _event_bus.start()
        logger.info("  ✓ EventBus 分发器已启动")

        # 5. 启动 SignalPipeline (监听事件)
        await _signal_pipeline.start()
        logger.info("  ✓ SignalPipeline 已启动 (评分引擎就绪)")

        # 6. RESTPollScheduler 初始化 (每日批量采集由 main_stream.py 启动)
        #    手动采集通过 run_once_manual_collect() 触发
        _rest_scheduler._load_fetchers()
        logger.info("  ✓ RESTPollScheduler 已就绪 (7 数据源, 每日批量 + 手动触发)")

        logger.info("-" * 54)
        logger.info("  ⚠ 盘中轮询已移除 — 使用每日美东 20:00 批量采集 + 手动触发")
        logger.info("  API: http://localhost:8524")
        logger.info("  前端: http://localhost:8524 → 系统状态监控 → 手动采集全部数据")
        logger.info("=" * 54)

    except Exception as e:
        logger.error("采集引擎初始化失败: %s", str(e), exc_info=True)
        # 不阻止服务器启动 — API 仍可响应，只是采集不可用


@app.on_event("shutdown")
async def shutdown_event():
    """优雅关闭采集引擎组件"""
    logger.info("正在关闭采集引擎...")

    if _signal_pipeline:
        try:
            await _signal_pipeline.shutdown()
        except Exception as e:
            logger.error(f"SignalPipeline 关闭异常: {e}")

    if _event_bus:
        try:
            await _event_bus.shutdown()
        except Exception as e:
            logger.error(f"EventBus 关闭异常: {e}")

    logger.info("采集引擎已关闭")


# ==================== 入口 ====================
@app.get("/api/config/audit")
async def config_audit():
    now = datetime.now()
    return {
        "audit_logs": [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "user": "admin", "field": "LEVEL_3_THRESHOLD", "old_value": "3.2", "new_value": "3.5"},
            {"timestamp": (now - timedelta(days=1)).isoformat(), "user": "admin", "field": "DIX_THRESHOLD", "old_value": "42%", "new_value": "45%"},
            {"timestamp": (now - timedelta(days=3)).isoformat(), "user": "admin", "field": "COOLDOWN_MINUTES", "old_value": "15", "new_value": "30"},
            {"timestamp": (now - timedelta(days=5)).isoformat(), "user": "admin", "field": "SIGNAL_COOLDOWN_MINUTES", "old_value": "20", "new_value": "15"},
        ]
    }


@app.post("/api/config/restore")
async def config_restore(version: str = Query("default")):
    return {"ok": True, "message": f"配置已还原至 {version} 版本"}


@app.get("/api/config/defaults")
async def config_defaults():
    return {
        "thresholds": {
            "DIX_THRESHOLD": 45.0,
            "SHORT_VOLUME_THRESHOLD": 45.0,
            "GEX_THRESHOLD": 0,
            "LEVEL_3_THRESHOLD": 3.5,
            "LEVEL_2_THRESHOLD": 3.0,
            "LEVEL_1_THRESHOLD": 2.0,
        },
        "fetch_intervals": {"intraday": 15, "crypto": 5, "after_hours": 60},
        "cooldown_minutes": 30,
        "notifications": {"email_recipients": "", "telegram_bot_token": "", "telegram_chat_id": "", "discord_webhook": ""},
    }


# ==================== Helpers ====================
def _row_to_dict(row) -> dict:
    """兼容 tuple 和 sqlite3.Row"""
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def _build_dashboard_data():
    now = datetime.now().isoformat()
    gex = db.get_latest_gex() or {}
    vix = db.get_latest_vix_analysis() or {}
    crypto = db.get_latest_crypto_data() or {}
    dp = db.get_latest_dark_pool_metrics() or {}

    gx = gex.get("gex_calibrated", 0) or 0
    vx = vix.get("vix_spot", 0) or 0
    oi = crypto.get("btc_oi", 0) or 0
    dix = dp.get("dix_value", 0) or 0
    sr = dp.get("chartexchange_short_ratio", 0) or 0

    # 从 GEXMetrix snapshots 补 wall/flip/spot 数据
    gex_wall = gex.get("put_wall_level", 0) or 0
    gex_flip_low = gex.get("flip_zone_lower", 0) or 0
    gex_flip_high = gex.get("flip_zone_upper", 0) or 0
    if gex_wall == 0 or gex_flip_low == 0 or gex_flip_high == 0:
        try:
            snap = db.get_gex_snapshot_latest('SPX')
            if snap:
                if gex_wall == 0:
                    gex_wall = snap.get('put_wall') or 0
                # 优先从 snapshot.zero_gamma_level 读真值 (GEXMetrix 提供)
                zg = snap.get('zero_gamma_level') or 0
                if gex_flip_low == 0 and zg:
                    gex_flip_low = zg
                if gex_flip_high == 0 and zg:
                    # ponytail: ±1% 启发式 (实盘典型 flip zone 宽度)
                    # 后续 P2 alpha 校准后用 GEXCalculator.identify_flip_zone 真算
                    gex_flip_high = zg * 1.01
        except Exception:
            pass

    gex_score = 0.5 if gx != 0 else 0
    vix_score = 0.5 if vx > 0 else 0
    crypto_score = 0.25 if oi > 0 else 0
    dp_score = 0.25 if dix > 0 or sr > 0 else 0
    total = round(gex_score + vix_score + crypto_score + dp_score, 2)
    resonance_pct = round(total / 5.0 * 100, 0)

    if total >= 3.5:
        level = "LEVEL_3"
    elif total >= 2.5:
        level = "LEVEL_2"
    elif total >= 1.5:
        level = "LEVEL_1"
    else:
        level = "NO_SIGNAL"

    return {
        "timestamp": now,
        "resonance": {"total_score": total, "max_score": 5.0, "alert_level": level, "resonance_pct": resonance_pct},
        "dimensions": {
            "gex": {"score": gex_score, "state": "NEUTRAL", "details": "GEX敞口正常",
                    "gex_local": gex.get("gex_local", 0), "gex_calibrated": gx,
                    "put_wall_level": gex_wall,
                    "flip_zone_lower": gex_flip_low,
                    "flip_zone_upper": gex_flip_high},
            "vix": {"score": vix_score, "state": "CONTANGO", "details": "期限结构正常",
                    "vix_spot": vx, "vx1": vix.get("vx1", 0), "vx2": vix.get("vx2", 0),
                    "term_structure_ratio": vix.get("term_structure_ratio", 1.0),
                    "panic_premium": vix.get("panic_premium", 0)},
            "crypto": {"score": crypto_score, "state": "NORMAL", "details": "加密市场正常",
                       "btc_funding_rate": crypto.get("btc_funding_rate", 0),
                       "btc_oi": oi, "oi_change_1h": crypto.get("oi_change_1h", 0),
                       "oi_crash": False, "funding_anomaly": False, "leverage_cleanup_confirmed": False},
            "darkpool": {"score": dp_score, "state": "NORMAL", "details": "暗盘活动正常",
                         "dix_value": dix, "dix_signal": False,
                         "short_ratio": sr, "short_ratio_signal": False,
                         "slope_20d": dp.get("stockgrid_20d_slope", 0),
                         "slope_60d": dp.get("stockgrid_60d_slope", 0),
                         "stockgrid_divergence": False, "stockgrid_signal": False,
                         "dbmf_ma5_recovery": False,
                         "available_sources": {"dix": True, "short_ratio": True, "stockgrid": True}},
            "cross_asset": {"score": 0.15, "state": "NEUTRAL", "details": "跨资产共振: 待数据填充",
                            "coherence_score": 50.0, "alignment_direction": "NEUTRAL",
                            "resonance_strength": "None", "alignment_count": 0},
        },
        "hawkes": {"branching_ratio": 0.5, "state": "SUBCRITICAL", "details": "Hawkes过程处于亚临界状态"},
    }


def _gex_row(r):
    d = _row_to_dict(r) if not isinstance(r, tuple) else {}
    if isinstance(r, tuple):
        keys = ["timestamp", "gex_local", "gex_calibrated", "spot_price", "put_wall_level", "flip_zone_lower", "flip_zone_upper"]
        d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
    return {
        "timestamp": str(d.get("timestamp", "")),
        "gex_local": d.get("gex_local", 0) or 0,
        "gex_calibrated": d.get("gex_calibrated", 0) or 0,
        # 方案A (2026-06-28): 保留 None → 前端 echarts 跳过该 series,
        # 避免 0 误画成贴底虚线。SqueezeMetrics CSV 无逐 strike 分布, 历史回填必为 None。
        "put_wall_level": d.get("put_wall_level"),
        "flip_zone_lower": d.get("flip_zone_lower"),
        "flip_zone_upper": d.get("flip_zone_upper"),
    }


def _vix_row(r):
    d = _row_to_dict(r) if not isinstance(r, tuple) else {}
    if isinstance(r, tuple):
        keys = ["timestamp", "vix_spot", "vx1", "vx2", "term_structure_ratio", "term_structure_state", "panic_premium"]
        d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
    return {"timestamp": str(d.get("timestamp", "")), "vix_spot": d.get("vix_spot", 0) or 0,
            "vx1": d.get("vx1", 0) or 0, "vx2": d.get("vx2", 0) or 0,
            "term_structure_ratio": d.get("term_structure_ratio", 1.0) or 1.0,
            "term_structure_state": d.get("term_structure_state", "Neutral") or "Neutral",
            "panic_premium": d.get("panic_premium", 0) or 0}


def _darkpool_row(r):
    d = _row_to_dict(r) if not isinstance(r, tuple) else {}
    if isinstance(r, tuple):
        keys = ["date", "dix_value", "chartexchange_short_ratio", "stockgrid_20d_slope",
                "stockgrid_60d_slope", "divergence_flag", "golden_cross_flag",
                "v_net", "ema_fast_5", "ema_slow_20", "zero_cross_signal", "momentum_reversal_signal"]
        d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
    return {
        "date": str(d.get("date", "")), "dix_value": d.get("dix_value", 0) or 0,
        "chartexchange_short_ratio": d.get("chartexchange_short_ratio", 0) or 0,
        "stockgrid_20d_slope": d.get("stockgrid_20d_slope", 0) or 0,
        "stockgrid_60d_slope": d.get("stockgrid_60d_slope", 0) or 0,
        "divergence_flag": bool(d.get("divergence_flag", False)),
        "golden_cross_flag": bool(d.get("golden_cross_flag", False)),
        # v2.1 暗盘EMA预处理字段
        "v_net": d.get("v_net") or 0,
        "ema_fast_5": d.get("ema_fast_5") or 0,
        "ema_slow_20": d.get("ema_slow_20") or 0,
        "zero_cross_signal": d.get("zero_cross_signal") or None,
        "momentum_reversal_signal": d.get("momentum_reversal_signal") or None,
    }


# ==================== 入口 ====================
FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

if __name__ == "__main__":
    import uvicorn

    if FRONTEND_DIR.exists():
        # 挂载静态资源目录 (JS/CSS/images)
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
        # SPA fallback: 任何未匹配的非 API 路径返回 index.html
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            """SPA fallback - 非 API/静态资源路径返回 index.html"""
            index_path = FRONTEND_DIR / "index.html"
            if index_path.exists():
                return HTMLResponse(content=index_path.read_text(encoding="utf-8"), status_code=200)
            return HTMLResponse(content="<h1>Frontend not built</h1>", status_code=404)

    uvicorn.run(app, host="0.0.0.0", port=8524)
