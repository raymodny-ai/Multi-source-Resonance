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

-- 未确认警报视图
CREATE VIEW IF NOT EXISTS v_unacknowledged_alerts AS
SELECT * FROM signal_alerts
WHERE acknowledged = FALSE
ORDER BY trigger_time DESC;
