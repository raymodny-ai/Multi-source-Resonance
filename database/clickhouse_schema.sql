-- ════════════════════════════════════════════
-- V2.5 P4: ClickHouse 列式时序数据库 Schema
-- ════════════════════════════════════════════
-- 用途: 高频日内 Tick-level 期权链数据存储与聚合查询
-- 设计:
--   - MergeTree 引擎: 列式存储 + 主键索引
--   - 按 (symbol, date) 分区
--   - 按 (symbol, timestamp) 排序
--   - 数据保留 90 天, 之后归档到冷存储
-- ════════════════════════════════════════════

-- 期权链 Tick 快照表
CREATE TABLE IF NOT EXISTS gex_option_ticks (
    -- 主键字段
    symbol          String,
    timestamp       DateTime64(6, 'America/New_York'),
    strike          Float64,
    expiry          Date,
    option_type     Enum8('C' = 1, 'P' = 2),
    days_to_expiry  UInt16,

    -- 价格字段
    bid             Float64,
    ask             Float64,
    last            Float64,
    mid_price       Float64,
    spread          Float64,
    spread_pct      Float64,

    -- 量价字段
    volume          UInt32,
    open_interest   UInt32,

    -- 隐含波动率
    implied_vol     Float64,
    smoothed_iv     Float64 DEFAULT 0,    -- V2.5 P2: SVI 平滑后 IV
    iv_rank         Float32 DEFAULT 0,

    -- 计算敞口 (V2.5 P5 多通道张量)
    gex             Float64,               -- Gamma Exposure
    vex             Float64,               -- Vanna Exposure
    chex            Float64,               -- Charm Exposure

    -- 元数据
    spot_price      Float64,
    risk_free_rate  Float32,
    source          LowCardinality(String),  -- 'gexmetrix'/'tradier'/'yfinance'/'synthesized'
    quality_score   Float32 DEFAULT 1.0,    -- V2.5 P1 流动性评分
    created_at      DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY (symbol, toYYYYMM(timestamp))
ORDER BY (symbol, timestamp, strike, option_type)
TTL toDate(timestamp) + INTERVAL 90 DAY
SETTINGS
    index_granularity = 8192,
    enable_mixed_granularity_parts = 1,
    min_bytes_for_wide_part = 0;

-- 索引: 按 strike 范围查询
ALTER TABLE gex_option_ticks ADD INDEX IF NOT EXISTS idx_strike strike TYPE bloom_filter() GRANULARITY 4;
ALTER TABLE gex_option_ticks ADD INDEX IF NOT EXISTS idx_expiry expiry TYPE bloom_filter() GRANULARITY 4;

-- GEX Profile 历史表 (聚合后的 GEX 曲线)
CREATE TABLE IF NOT EXISTS gex_profiles (
    symbol          String,
    timestamp       DateTime64(6, 'America/New_York'),
    spot_price      Float64,
    net_gex         Float64,
    call_gex        Float64,
    put_gex         Float64,
    flip_point      Nullable(Float64),
    profile_json    String,  -- 完整的 GEX 曲线 JSON
    backend         LowCardinality(String),  -- 计算后端
    computation_ms  UInt32,
    created_at      DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY (symbol, toYYYYMM(timestamp))
ORDER BY (symbol, timestamp)
TTL toDate(timestamp) + INTERVAL 180 DAY
SETTINGS index_granularity = 8192;

-- 共振信号历史表
CREATE TABLE IF NOT EXISTS resonance_signals (
    signal_id       String,
    symbol          String,
    timestamp       DateTime64(6, 'America/New_York'),
    score           Float32,
    level           Enum8('LEVEL_1' = 1, 'LEVEL_2' = 2, 'LEVEL_3' = 3, 'NONE' = 0),
    components      String,  -- JSON: 各分项分数
    trigger_reasons String,  -- JSON: 触发原因
    llm_inference_ms UInt32,
    created_at      DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY (symbol, toYYYYMM(timestamp))
ORDER BY (symbol, timestamp)
TTL toDate(timestamp) + INTERVAL 365 DAY
SETTINGS index_granularity = 8192;

-- 管道监控表 (V2.5 P6)
CREATE TABLE IF NOT EXISTS pipeline_metrics (
    metric_id       String,
    layer_name      LowCardinality(String),  -- 'layer1_filter'/'layer2_vec'/'layer3_tensor'/'layer4_llm'
    symbol          String,
    timestamp       DateTime64(6, 'America/New_York'),
    duration_ms     UInt32,
    input_count     UInt32,
    output_count    UInt32,
    removed_count   UInt32,
    error           String DEFAULT '',
    metadata        String DEFAULT '{}',  -- JSON
    created_at      DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (layer_name, timestamp)
TTL toDate(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- 物化视图: 实时 GEX 聚合 (5 分钟滚动)
CREATE MATERIALIZED VIEW IF NOT EXISTS gex_5min_aggregate_mv
ENGINE = SummingMergeTree()
PARTITION BY (symbol, toYYYYMM(bucket))
ORDER BY (symbol, bucket)
AS SELECT
    symbol,
    toStartOfFiveMinute(timestamp) AS bucket,
    avg(spot_price) AS avg_spot,
    sum(gex) AS total_gex,
    sumIf(gex, option_type = 'C') AS call_gex,
    sumIf(gex, option_type = 'P') AS put_gex,
    count() AS contract_count
FROM gex_option_ticks
WHERE gex != 0
GROUP BY symbol, bucket;

-- 物化视图: 每日 OI 变化跟踪
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_oi_change_mv
ENGINE = SummingMergeTree()
PARTITION BY (symbol, date)
ORDER BY (symbol, date, strike)
AS SELECT
    symbol,
    toDate(timestamp) AS date,
    strike,
    option_type,
    sum(volume) AS total_volume,
    sum(gex) AS daily_gex_contribution
FROM gex_option_ticks
GROUP BY symbol, date, strike, option_type;
