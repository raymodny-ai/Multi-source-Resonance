"""
V2.5 P4: ClickHouse 列式时序数据库客户端

包装 clickhouse-driver, 提供:
  - 期权链 Tick 批量插入
  - GEX Profile 历史写入
  - 跨行权价 / 跨到期日 聚合查询 (10-100× 加速)
  - 信号历史查询
  - 管道监控写入

依赖: clickhouse-driver (可选, 缺失时降级到内存)

Examples:
    >>> client = ClickHouseClient()
    >>> client.insert_ticks('SPY', ticks_df)
    >>> result = client.query_gex_aggregate('SPY', start='2026-06-01', end='2026-06-24')
"""
from __future__ import annotations

import os
import time
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

import pandas as pd
import numpy as np
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('clickhouse_client')

# ── 可选依赖: clickhouse-driver ──
try:
    from clickhouse_driver import Client as CHClient
    CLICKHOUSE_AVAILABLE = True
except ImportError:
    CLICKHOUSE_AVAILABLE = False
    CHClient = None  # type: ignore
    logger.warning(
        "clickhouse-driver 不可用, ClickHouseClient 降级为内存模式。"
        "安装方法: pip install clickhouse-driver"
    )


class ClickHouseClient:
    """ClickHouse 客户端 (V2.5 P4)

    通过环境变量配置:
      CLICKHOUSE_HOST (默认 localhost)
      CLICKHOUSE_PORT (默认 9000)
      CLICKHOUSE_USER (默认 default)
      CLICKHOUSE_PASSWORD (默认空)
      CLICKHOUSE_DATABASE (默认 resonance)
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host or os.getenv('CLICKHOUSE_HOST', 'localhost')
        self.port = port or int(os.getenv('CLICKHOUSE_PORT', '9000'))
        self.database = database or os.getenv('CLICKHOUSE_DATABASE', 'resonance')
        self.user = user or os.getenv('CLICKHOUSE_USER', 'default')
        self.password = password or os.getenv('CLICKHOUSE_PASSWORD', '')

        self._client: Optional[CHClient] = None
        self._connected = False
        self._fallback_memory: Dict[str, List[Dict]] = {}  # 内存降级

        if CLICKHOUSE_AVAILABLE:
            try:
                self._client = CHClient(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    connect_timeout=5,
                )
                self._client.execute('SELECT 1')
                self._connected = True
                logger.info(
                    f"ClickHouse 连接成功: {self.host}:{self.port}/{self.database}"
                )
            except Exception as e:
                logger.warning(
                    f"ClickHouse 连接失败 ({self.host}:{self.port}): {e}. "
                    f"降级为内存模式。"
                )
                self._client = None
        else:
            logger.info("ClickHouse 不可用, 降级为内存模式")

    # ════════════════════════════════════════
    # 连接管理
    # ════════════════════════════════════════

    def is_connected(self) -> bool:
        return self._connected

    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        if not self._connected or self._client is None:
            return {
                'connected': False,
                'backend': 'in_memory',
                'host': self.host,
                'port': self.port,
            }
        try:
            t0 = time.perf_counter()
            self._client.execute('SELECT 1')
            latency_ms = (time.perf_counter() - t0) * 1000
            version = self._client.execute('SELECT version()')[0][0]
            return {
                'connected': True,
                'backend': 'clickhouse',
                'version': version,
                'host': self.host,
                'port': self.port,
                'latency_ms': round(latency_ms, 2),
            }
        except Exception as e:
            return {'connected': False, 'error': str(e)}

    # ════════════════════════════════════════
    # 期权链 Tick 写入
    # ════════════════════════════════════════

    def insert_ticks(
        self,
        symbol: str,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        source: str = 'gexmetrix',
    ) -> int:
        """批量插入期权链 Tick 数据

        Args:
            symbol: 标的代码
            option_chain_df: 期权链 DataFrame, 必含 strike/expiry/type/bid/ask/volume/open_interest
            spot_price: 标的价格
            source: 数据源
        Returns:
            插入行数
        """
        if option_chain_df.empty:
            return 0

        now = datetime.now(timezone.utc)
        rows = []
        for _, r in option_chain_df.iterrows():
            expiry = r.get('expiry', now.date())
            if isinstance(expiry, str):
                try:
                    expiry = datetime.fromisoformat(expiry).date()
                except ValueError:
                    expiry = now.date()
            dte = (expiry - now.date()).days if hasattr(expiry, 'year') else 30

            bid = float(r.get('bid', 0) or 0)
            ask = float(r.get('ask', 0) or 0)
            mid = (bid + ask) / 2.0 if (bid or ask) else 0
            spread = max(ask - bid, 0)
            spread_pct = (spread / ask * 100) if ask > 0 else 0

            rows.append((
                symbol,
                now,
                float(r.get('strike', 0)),
                expiry,
                'C' if str(r.get('type', 'C')).upper().startswith('C') else 'P',
                max(dte, 0),
                bid,
                ask,
                float(r.get('last', mid) or 0),
                mid,
                spread,
                spread_pct,
                int(r.get('volume', 0) or 0),
                int(r.get('open_interest', 0) or 0),
                float(r.get('implied_volatility', 0) or 0),
                float(r.get('smoothed_iv', 0) or 0),  # V2.5 P2
                float(r.get('iv_rank', 0) or 0),
                float(r.get('gex', 0) or 0),  # V2.5 P5
                float(r.get('vex', 0) or 0),  # V2.5 P5
                float(r.get('chex', 0) or 0),  # V2.5 P5
                spot_price,
                0.05,  # risk-free rate
                source,
                float(r.get('quality_score', 1.0) or 1.0),
            ))

        if not rows:
            return 0

        return self._execute_insert(
            'INSERT INTO gex_option_ticks',
            rows,
            columns=[
                'symbol', 'timestamp', 'strike', 'expiry', 'option_type',
                'days_to_expiry', 'bid', 'ask', 'last', 'mid_price', 'spread',
                'spread_pct', 'volume', 'open_interest', 'implied_vol',
                'smoothed_iv', 'iv_rank', 'gex', 'vex', 'chex',
                'spot_price', 'risk_free_rate', 'source', 'quality_score',
            ],
        )

    # ════════════════════════════════════════
    # 聚合查询
    # ════════════════════════════════════════

    def query_gex_aggregate(
        self,
        symbol: str,
        start: str,
        end: str,
        aggregation: str = '5min',
    ) -> pd.DataFrame:
        """查询 GEX 聚合 (跨行权价 / 跨到期日)

        Args:
            symbol: 标的代码
            start: 起始时间 (ISO 格式)
            end: 结束时间
            aggregation: '5min' / '1hour' / '1day'
        Returns:
            DataFrame: [bucket, total_gex, call_gex, put_gex, contract_count]
        """
        bucket_expr = {
            '5min': 'toStartOfFiveMinute(timestamp)',
            '1hour': 'toStartOfHour(timestamp)',
            '1day': 'toDate(timestamp)',
        }.get(aggregation, 'toStartOfFiveMinute(timestamp)')

        query = f"""
            SELECT
                {bucket_expr} AS bucket,
                sum(gex) AS total_gex,
                sumIf(gex, option_type = 'C') AS call_gex,
                sumIf(gex, option_type = 'P') AS put_gex,
                count() AS contract_count,
                avg(spot_price) AS avg_spot
            FROM gex_option_ticks
            WHERE symbol = %(symbol)s
              AND timestamp BETWEEN %(start)s AND %(end)s
            GROUP BY bucket
            ORDER BY bucket
        """
        return self._execute_query(query, {
            'symbol': symbol, 'start': start, 'end': end,
        })

    def query_flip_point_history(
        self,
        symbol: str,
        days: int = 30,
    ) -> pd.DataFrame:
        """查询 Flip Point 历史 (Gamma 反转点时间序列)

        Returns:
            DataFrame: [timestamp, flip_point, net_gex]
        """
        query = """
            SELECT
                timestamp,
                flip_point,
                net_gex,
                spot_price
            FROM gex_profiles
            WHERE symbol = %(symbol)s
              AND timestamp >= now() - INTERVAL %(days)s DAY
              AND flip_point IS NOT NULL
            ORDER BY timestamp
        """
        return self._execute_query(query, {
            'symbol': symbol, 'days': days,
        })

    def query_strike_level_gex(
        self,
        symbol: str,
        timestamp: str,
        strike_range: Optional[Tuple[float, float]] = None,
    ) -> pd.DataFrame:
        """查询某时间点逐 strike 的 GEX 分布 (LLM 输入)

        Args:
            symbol: 标的
            timestamp: 时间点 (ISO 格式)
            strike_range: (low, high) 行权价范围, 默认 ±10% spot
        Returns:
            DataFrame: [strike, call_gex, put_gex, net_gex, gex, vex, chex]
        """
        strike_filter = ""
        params: Dict[str, Any] = {'symbol': symbol, 'ts': timestamp}
        if strike_range is not None:
            strike_filter = "AND strike BETWEEN %(lo)s AND %(hi)s"
            params['lo'] = strike_range[0]
            params['hi'] = strike_range[1]

        query = f"""
            SELECT
                strike,
                option_type,
                days_to_expiry,
                sumIf(gex, option_type = 'C') AS call_gex,
                sumIf(gex, option_type = 'P') AS put_gex,
                sum(gex) AS net_gex,
                sum(vex) AS vex,
                sum(chex) AS chex
            FROM gex_option_ticks
            WHERE symbol = %(symbol)s
              AND timestamp = %(ts)s
              {strike_filter}
            GROUP BY strike, option_type, days_to_expiry
            ORDER BY strike, option_type, days_to_expiry
        """
        return self._execute_query(query, params)

    # ════════════════════════════════════════
    # GEX Profile 写入
    # ════════════════════════════════════════

    def insert_gex_profile(
        self,
        symbol: str,
        timestamp: str,
        spot_price: float,
        net_gex: float,
        call_gex: float,
        put_gex: float,
        flip_point: Optional[float],
        profile_json: str,
        backend: str = 'numpy',
        computation_ms: int = 0,
    ) -> int:
        """插入 GEX Profile 快照"""
        rows = [(
            symbol, timestamp, spot_price, net_gex, call_gex, put_gex,
            flip_point, profile_json, backend, computation_ms,
        )]
        return self._execute_insert(
            'INSERT INTO gex_profiles',
            rows,
            columns=[
                'symbol', 'timestamp', 'spot_price', 'net_gex', 'call_gex',
                'put_gex', 'flip_point', 'profile_json', 'backend', 'computation_ms',
            ],
        )

    # ════════════════════════════════════════
    # 管道监控 (P6)
    # ════════════════════════════════════════

    def insert_pipeline_metric(
        self,
        layer_name: str,
        symbol: str,
        duration_ms: int,
        input_count: int,
        output_count: int,
        removed_count: int = 0,
        error: str = '',
        metadata: Optional[Dict] = None,
    ) -> int:
        """插入管道层处理耗时"""
        import uuid
        rows = [(
            str(uuid.uuid4()),
            layer_name,
            symbol,
            datetime.now(timezone.utc),
            duration_ms,
            input_count,
            output_count,
            removed_count,
            error,
            json.dumps(metadata or {}),
        )]
        return self._execute_insert(
            'INSERT INTO pipeline_metrics',
            rows,
            columns=[
                'metric_id', 'layer_name', 'symbol', 'timestamp', 'duration_ms',
                'input_count', 'output_count', 'removed_count', 'error', 'metadata',
            ],
        )

    # ════════════════════════════════════════
    # 内部执行方法
    # ════════════════════════════════════════

    def _execute_insert(
        self,
        query: str,
        rows: List[Tuple],
        columns: List[str],
    ) -> int:
        if not self._connected or self._client is None:
            # 降级: 内存存储
            table = query.split('INTO ')[1].strip() if 'INTO ' in query else 'unknown'
            if table not in self._fallback_memory:
                self._fallback_memory[table] = []
            self._fallback_memory[table].extend(
                [dict(zip(columns, row)) for row in rows]
            )
            # 限制内存大小, 防止 OOM
            if len(self._fallback_memory[table]) > 10000:
                self._fallback_memory[table] = self._fallback_memory[table][-5000:]
            return len(rows)

        try:
            self._client.execute(query, rows, column_names=columns)
            return len(rows)
        except Exception as e:
            logger.error(f"ClickHouse 插入失败: {e}")
            return 0

    def _execute_query(self, query: str, params: Dict) -> pd.DataFrame:
        if not self._connected or self._client is None:
            # 降级: 返回空 DataFrame
            return pd.DataFrame()

        try:
            result = self._client.execute(query, params, with_column_types=True)
            if not result:
                return pd.DataFrame()
            rows, types = result
            columns = [t[0] for t in types]
            return pd.DataFrame(rows, columns=columns)
        except Exception as e:
            logger.error(f"ClickHouse 查询失败: {e}")
            return pd.DataFrame()

    # ════════════════════════════════════════
    # Schema 管理
    # ════════════════════════════════════════

    def initialize_schema(self, schema_path: Optional[str] = None) -> bool:
        """初始化 ClickHouse Schema (执行 DDL)

        Args:
            schema_path: SQL 文件路径, 默认 database/clickhouse_schema.sql
        Returns:
            成功 True / 失败 False
        """
        if not self._connected or self._client is None:
            logger.warning("未连接, 跳过 Schema 初始化")
            return False

        if schema_path is None:
            schema_path = os.path.join(
                os.path.dirname(__file__), 'clickhouse_schema.sql',
            )
        if not os.path.exists(schema_path):
            logger.error(f"Schema 文件不存在: {schema_path}")
            return False

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            # 分割语句 (按 ; 分割, 忽略空语句和注释)
            statements = []
            for stmt in sql_content.split(';'):
                # 移除注释
                clean = '\n'.join(
                    line for line in stmt.split('\n')
                    if not line.strip().startswith('--')
                ).strip()
                if clean:
                    statements.append(clean)
            for stmt in statements:
                self._client.execute(stmt)
            logger.info(f"ClickHouse Schema 初始化完成: {len(statements)} 条 DDL")
            return True
        except Exception as e:
            logger.error(f"Schema 初始化失败: {e}")
            return False


# ── 单例 ──
_CLIENT_SINGLETON: Optional[ClickHouseClient] = None


def get_client() -> ClickHouseClient:
    """获取全局 ClickHouse 客户端 (懒加载)"""
    global _CLIENT_SINGLETON
    if _CLIENT_SINGLETON is None:
        _CLIENT_SINGLETON = ClickHouseClient()
    return _CLIENT_SINGLETON
