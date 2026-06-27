-- ============================================================
-- 多源共振监控系统 - 数据库Schema定义
-- ============================================================
-- 版本: 1.0
-- 创建日期: 2026-06-09
-- 描述: 定义所有核心数据表结构、索引和初始配置
-- ============================================================

-- ============================================================
-- 表1: gex_history (GEX历史表)
-- 存储Gamma Exposure的历史估算值和校准值
-- ============================================================
CREATE TABLE IF NOT EXISTS gex_history (
    timestamp DATETIME PRIMARY KEY,
    gex_local REAL NOT NULL,           -- 本地估算GEX(美元)
    gex_calibrated REAL,               -- 校准后GEX(美元)
    alpha_factor REAL DEFAULT 1.0,     -- 修正系数α
    put_wall_level REAL,               -- Put Wall支撑点位
    flip_zone_lower REAL,              -- Flip Zone下界
    flip_zone_upper REAL,              -- Flip Zone上界
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 索引: 按时间查询最近记录
CREATE INDEX IF NOT EXISTS idx_gex_timestamp ON gex_history(timestamp DESC);


-- ============================================================
-- 表2: dark_pool_metrics (暗盘指标表)
-- 存储来自多个数据源的暗盘活动指标
-- ============================================================
CREATE TABLE IF NOT EXISTS dark_pool_metrics (
    date DATE PRIMARY KEY,
    dix_value REAL,                    -- SqueezeMetrics DIX百分比
    chartexchange_short_ratio REAL,    -- ChartExchange卖空比百分比
    stockgrid_20d_slope REAL,          -- Stockgrid 20日净头寸斜率
    stockgrid_60d_slope REAL,          -- Stockgrid 60日净头寸斜率
    stockgrid_divergence BOOLEAN DEFAULT FALSE,  -- 底背离标志
    dbmf_ma5_recovery BOOLEAN DEFAULT FALSE,     -- DBMF均线收复标志
    dix_signal BOOLEAN DEFAULT FALSE,  -- DIX>45%信号
    short_ratio_signal BOOLEAN DEFAULT FALSE,    -- 卖空比>45%信号
    stockgrid_signal BOOLEAN DEFAULT FALSE,      -- Stockgrid拐点信号
    aggregated_signal BOOLEAN DEFAULT FALSE,     -- 三选二聚合信号
    -- 暗盘预处理字段 (v2.1: EMA降噪 + 拐点检测)
    v_net REAL,                        -- 净做空量 V_net = 2*V_short - V_total
    ema_fast_5 REAL,                   -- EMA快线 (span=5) 近一周短期做市商情绪
    ema_slow_20 REAL,                  -- EMA慢线 (span=20) 近一月基准流动性状态
    zero_cross_signal TEXT,            -- 零轴穿越信号: 'BULLISH'/'BEARISH'/NULL
    momentum_reversal_signal TEXT,     -- 动量反转信号: 'EARLY_SELL_WARNING'/NULL
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_darkpool_date ON dark_pool_metrics(date DESC);


-- ============================================================
-- 表3: crypto_derivatives (加密衍生品表)
-- 存储加密货币衍生品市场的关键指标
-- ============================================================
CREATE TABLE IF NOT EXISTS crypto_derivatives (
    timestamp DATETIME PRIMARY KEY,
    btc_funding_rate REAL NOT NULL,    -- BTC永续合约资金费率
    btc_oi REAL,                       -- BTC全网持仓量(美元)
    oi_change_1h REAL,                 -- 1小时OI变化率(%)
    liquidation_spike BOOLEAN DEFAULT FALSE,  -- 清算峰值标志
    cryptoquant_elr REAL,              -- CryptoQuant预估杠杆率
    funding_anomaly BOOLEAN DEFAULT FALSE,     -- 费率异常(<-0.01%)
    oi_crash BOOLEAN DEFAULT FALSE,    -- OI断崖下跌(>15%)
    leverage_cleanup BOOLEAN DEFAULT FALSE,    -- 去杠杆完成标志
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crypto_timestamp ON crypto_derivatives(timestamp DESC);


-- ============================================================
-- 表4: signal_alerts (信号触发日志表)
-- 记录所有共振信号的触发事件
-- ============================================================
CREATE TABLE IF NOT EXISTS signal_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_time DATETIME NOT NULL,
    total_score REAL NOT NULL,         -- 共振总分(0-5)
    gex_score REAL DEFAULT 0,          -- GEX维度得分
    vix_score REAL DEFAULT 0,          -- VIX维度得分
    crypto_score REAL DEFAULT 0,       -- 加密维度得分
    darkpool_score REAL DEFAULT 0,     -- 暗盘维度得分
    alert_level TEXT NOT NULL,         -- LEVEL_1/LEVEL_2/LEVEL_3
    hawkes_branching_ratio REAL,       -- Hawkes分支比
    details TEXT,                      -- JSON格式详细触发条件
    acknowledged BOOLEAN DEFAULT FALSE, -- 是否已确认
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_time ON signal_alerts(trigger_time DESC);
CREATE INDEX IF NOT EXISTS idx_alert_level ON signal_alerts(alert_level);


-- ============================================================
-- 附加表: system_config (系统配置表)
-- 存储运行时可调整的配置参数
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 预置配置项
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
('alpha_factor', '1.0', 'GEX校准系数'),
('last_dix_update', '', '最后DIX更新时间'),
('db_version', '1.0', '数据库版本');


-- ============================================================
-- 视图: 可选的便捷查询视图
-- ============================================================

-- 最新GEX快照视图
CREATE VIEW IF NOT EXISTS v_latest_gex AS
SELECT * FROM gex_history
ORDER BY timestamp DESC
LIMIT 1;

-- 最新暗盘指标视图
CREATE VIEW IF NOT EXISTS v_latest_darkpool AS
SELECT * FROM dark_pool_metrics
ORDER BY date DESC
LIMIT 1;

-- 最新加密数据视图
CREATE VIEW IF NOT EXISTS v_latest_crypto AS
SELECT * FROM crypto_derivatives
ORDER BY timestamp DESC
LIMIT 1;

-- ============================================================
-- 表5: gex_snapshots (GEXMetrix 期权市场结构快照表)
-- 存储 GEXMetrix API 返回的快照关键指标摘要，完整 JSON 保留在文件系统。
-- 每个 symbol 保留最近 50 个快照。
-- ============================================================
CREATE TABLE IF NOT EXISTS gex_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,              -- 标的代码 (SPX, SPY, QQQ, ...)
    timestamp DATETIME NOT NULL,       -- 快照时间戳
    filename TEXT NOT NULL,            -- 原始 JSON 文件名
    net_gex REAL,                      -- 净 Gamma Exposure
    call_gex REAL,                     -- Call 端 Gamma 总值
    put_gex REAL,                      -- Put 端 Gamma 总值
    zero_gamma_level REAL,            -- 零 Gamma 价位
    call_wall REAL,                    -- Call Wall 行权价
    put_wall REAL,                     -- Put Wall 行权价
    spot_price REAL,                   -- 现货价格
    total_gamma REAL,                  -- 总 Gamma
    file_size INTEGER,                 -- 文件大小 (bytes)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gex_snap_symbol ON gex_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_gex_snap_timestamp ON gex_snapshots(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_gex_snap_created ON gex_snapshots(created_at DESC);

-- ============================================================
-- 表6: gateway_snapshots (V2.0 网关快照表)
-- 存储每日穿过 Layer 2 网关的 JSON 快照，用于审计和回测
-- ============================================================
CREATE TABLE IF NOT EXISTS gateway_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL,          -- 快照日期
    pipeline_run_id TEXT NOT NULL UNIQUE, -- 流水线运行 ID (UUID)
    snapshot_json TEXT NOT NULL,          -- 完整 GatewayEnvelope JSON
    schema_version TEXT DEFAULT '2.0.0',  -- Schema 版本
    data_quality_flag TEXT DEFAULT 'NORMAL', -- NORMAL / DEGRADED / ERROR
    resonance_score INTEGER DEFAULT 0,   -- 共振得分 (冗余索引字段)
    processing_duration_ms INTEGER DEFAULT 0, -- 处理耗时 (毫秒)
    interception_status TEXT DEFAULT 'pass_through', -- pass_through / degraded / blocked
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gateway_date ON gateway_snapshots(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_gateway_run_id ON gateway_snapshots(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_gateway_quality ON gateway_snapshots(data_quality_flag);


-- 未确认警报视图
CREATE VIEW IF NOT EXISTS v_unacknowledged_alerts AS
SELECT * FROM signal_alerts
WHERE acknowledged = FALSE
ORDER BY trigger_time DESC;


-- ============================================================
-- 表7: validation_audit_log (V2.0 数据校验审计日志表)
-- 持久化存储所有因 Pandera/Greeks/Parity/Arbitrage/IF 校验
-- 失败的数据记录，满足 PRD §不可变审计日志 要求。
-- ============================================================
CREATE TABLE IF NOT EXISTS validation_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL,           -- 快照日期
    pipeline_run_id TEXT NOT NULL,         -- 关联的流水线运行 ID
    check_type TEXT NOT NULL,              -- 校验类型: PANDERA/GREEKS_BOUNDS/PUT_CALL_PARITY/NO_ARBITRAGE/ISO_FOREST
    severity TEXT NOT NULL DEFAULT 'WARN', -- 严重级别: ERROR/WARN/INFO
    field_name TEXT,                       -- 违规字段名
    expected_range TEXT,                   -- 期望范围
    actual_value TEXT,                     -- 实际值
    option_type TEXT,                      -- 期权类型 (CALL/PUT)
    strike REAL,                           -- 行权价
    expiry TEXT,                           -- 到期日
    pass_rate_pct REAL,                    -- 当日校验总体通过率 (%)
    details TEXT,                          -- 详细描述
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_date ON validation_audit_log(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON validation_audit_log(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_audit_check_type ON validation_audit_log(check_type);
CREATE INDEX IF NOT EXISTS idx_audit_severity ON validation_audit_log(severity);

-- 每日校验通过率视图 (用于 95% 熔断判定)
CREATE VIEW IF NOT EXISTS v_daily_pass_rate AS
SELECT
    snapshot_date,
    pipeline_run_id,
    pass_rate_pct,
    COUNT(*) AS violation_count,
    SUM(CASE WHEN severity = 'ERROR' THEN 1 ELSE 0 END) AS error_count,
    SUM(CASE WHEN severity = 'WARN' THEN 1 ELSE 0 END) AS warn_count
FROM validation_audit_log
GROUP BY snapshot_date, pipeline_run_id
ORDER BY snapshot_date DESC;

-- ============================================================
-- VIX 期限结构分析表
-- ============================================================
CREATE TABLE IF NOT EXISTS vix_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    vix_spot REAL DEFAULT 0,
    vx1 REAL DEFAULT 0,
    vx2 REAL DEFAULT 0,
    term_structure_ratio REAL DEFAULT 1.0,
    term_structure_state TEXT DEFAULT 'NEUTRAL',
    panic_premium REAL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vix_analysis_ts ON vix_analysis(timestamp DESC);
