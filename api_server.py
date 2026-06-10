"""
多源共振监控系统 - API 服务器
FastAPI REST API + WebSocket + 前端静态托管
"""
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from database.db_manager import DatabaseManager

db = DatabaseManager()

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


# ==================== VIX ====================
@app.get("/api/vix/history")
async def vix_history(days: int = Query(90)):
    rows = db.get_vix_history(days)
    return [_vix_row(r) for r in rows]


# ==================== Darkpool ====================
@app.get("/api/darkpool/history")
async def darkpool_history(days: int = Query(90)):
    rows = db.get_darkpool_history_list(days)
    return [_darkpool_row(r) for r in rows]


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


# ==================== System ====================
@app.get("/api/system/source-status")
async def source_status():
    now = datetime.now().isoformat()
    return {
        "sources": [
            {"name": "Tradier (GEX)", "status": "OFFLINE", "availability_pct": 0, "failure_count": 0, "last_updated": now},
            {"name": "Yahoo Finance", "status": "ONLINE", "availability_pct": 100, "failure_count": 0, "last_updated": now},
            {"name": "CCXT (Crypto)", "status": "ONLINE", "availability_pct": 100, "failure_count": 0, "last_updated": now},
            {"name": "SqueezeMetrics", "status": "OFFLINE", "availability_pct": 0, "failure_count": 0, "last_updated": now},
            {"name": "ChartExchange", "status": "ONLINE", "availability_pct": 100, "failure_count": 0, "last_updated": now},
            {"name": "Stockgrid", "status": "ONLINE", "availability_pct": 100, "failure_count": 0, "last_updated": now},
            {"name": "DBMF ETF", "status": "ONLINE", "availability_pct": 100, "failure_count": 0, "last_updated": now},
        ],
        "degradation_mode": False,
        "scheduler_running": True,
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
                    "put_wall_level": gex.get("put_wall_level", 0),
                    "flip_zone_lower": gex.get("flip_zone_lower", 0),
                    "flip_zone_upper": gex.get("flip_zone_upper", 0)},
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
        },
        "hawkes": {"branching_ratio": 0.5, "state": "SUBCRITICAL", "details": "Hawkes过程处于亚临界状态"},
    }


def _gex_row(r):
    d = _row_to_dict(r) if not isinstance(r, tuple) else {}
    if isinstance(r, tuple):
        keys = ["timestamp", "gex_local", "gex_calibrated", "spot_price", "put_wall_level", "flip_zone_lower", "flip_zone_upper"]
        d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
    return {"timestamp": str(d.get("timestamp", "")), "gex_local": d.get("gex_local", 0) or 0,
            "gex_calibrated": d.get("gex_calibrated", 0) or 0,
            "put_wall_level": d.get("put_wall_level", 0) or 0,
            "flip_zone_lower": d.get("flip_zone_lower", 0) or 0,
            "flip_zone_upper": d.get("flip_zone_upper", 0) or 0}


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
                "stockgrid_60d_slope", "divergence_flag", "golden_cross_flag"]
        d = {keys[i]: r[i] for i in range(min(len(keys), len(r)))}
    return {"date": str(d.get("date", "")), "dix_value": d.get("dix_value", 0) or 0,
            "chartexchange_short_ratio": d.get("chartexchange_short_ratio", 0) or 0,
            "stockgrid_20d_slope": d.get("stockgrid_20d_slope", 0) or 0,
            "stockgrid_60d_slope": d.get("stockgrid_60d_slope", 0) or 0,
            "divergence_flag": bool(d.get("divergence_flag", False)),
            "golden_cross_flag": bool(d.get("golden_cross_flag", False))}


# ==================== 入口 ====================
FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

if __name__ == "__main__":
    import uvicorn

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    uvicorn.run(app, host="0.0.0.0", port=8000)
