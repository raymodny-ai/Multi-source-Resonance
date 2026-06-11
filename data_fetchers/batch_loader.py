"""
Multi-source Resonance V2.0 - Layer 1 盘后数据批量加载器

该模块负责盘后从本地文件系统（Parquet/HDF5/CSV）批量加载收盘数据快照。
支持 TDS (Trade Data Snapshots) 和 SPR (Systematic Positioning Reports) 格式。

数据清洗管道：去重 → 缺失值填充 → 异常值标记 → 时区对齐。

该模块为 Layer 1 纯本地 I/O 组件，严禁任何 LLM 依赖。
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date

import pandas as pd
import numpy as np
import pytz

from utils.logger import getLogger

logger = getLogger('batch_loader')

# 可选依赖
try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    logger.info("Polars 不可用，回退到 Pandas")

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    pa = None
    PARQUET_AVAILABLE = False


class BatchDataLoader:
    """盘后数据批量加载器

    支持多种文件格式的透明加载，自动执行清洗管道。

    Attributes:
        data_root: 数据文件根目录
        et_timezone: 美东时区
    """

    def __init__(self, data_root: str = "./data/raw"):
        self.data_root = Path(data_root)
        self.et_timezone = pytz.timezone('US/Eastern')
        self.data_root.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────
    # 通用加载接口
    # ──────────────────────────────────────────────

    def load_dataframe(
        self,
        file_path: str,
        file_format: str = "auto",
        use_polars: bool = True,
    ) -> pd.DataFrame:
        """通用 DataFrame 加载，自动检测格式

        Args:
            file_path: 文件路径（可相对 data_root）
            file_format: "auto" | "parquet" | "csv" | "hdf5"
            use_polars: 是否优先使用 Polars（更快）

        Returns:
            pd.DataFrame
        """
        full_path = self._resolve_path(file_path)
        fmt = file_format if file_format != "auto" else self._detect_format(full_path)

        if use_polars and POLARS_AVAILABLE and fmt in ("parquet", "csv"):
            return self._load_with_polars(full_path, fmt)

        return self._load_with_pandas(full_path, fmt)

    def load_option_chain(
        self,
        symbol: str = "SPX",
        date_str: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载指定日期的期权链数据

        Args:
            symbol: 标的代码
            date_str: 日期字符串 YYYY-MM-DD，默认最近一个交易日

        Returns:
            期权链 DataFrame（含 strike, type, expiry, bid, ask, volume, open_interest 等）
        """
        if date_str is None:
            date_str = datetime.now(self.et_timezone).strftime("%Y-%m-%d")

        # 多路径尝试
        candidates = [
            f"options/{symbol}/{date_str}_options.parquet",
            f"options/{symbol}_{date_str}.csv",
            f"tds/{symbol}/{date_str}/option_chain.parquet",
        ]

        for path in candidates:
            full_path = self.data_root / path
            if full_path.exists():
                df = self.load_dataframe(str(full_path))
                df = self._clean_option_chain(df)
                logger.info(f"加载期权链: {path}, {len(df)} 行")
                return df

        logger.warning(f"未找到 {symbol} {date_str} 的期权链数据")
        return pd.DataFrame()

    def load_darkpool_data(
        self,
        symbol: str = "SPY",
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """加载暗盘交易数据 (SPR 格式)

        Returns:
            {
                'trades': DataFrame,
                'summary': {dix, short_ratio, total_volume, ...}
            }
        """
        if date_str is None:
            date_str = datetime.now(self.et_timezone).strftime("%Y-%m-%d")

        trades_df = pd.DataFrame()
        candidates = [
            f"spr/{symbol}/{date_str}_darkpool.parquet",
            f"darkpool/{symbol}_{date_str}.csv",
        ]
        for path in candidates:
            full_path = self.data_root / path
            if full_path.exists():
                trades_df = self.load_dataframe(str(full_path))
                break

        trades_df = self._clean_trade_data(trades_df)

        summary = {
            'dix': 50.0,
            'short_ratio': 50.0,
            'total_volume': 0,
            'trade_count': len(trades_df),
        }

        if not trades_df.empty:
            if 'buy_volume' in trades_df.columns and 'total_volume' in trades_df.columns:
                total_vol = trades_df['total_volume'].sum()
                if total_vol > 0:
                    summary['dix'] = float(trades_df['buy_volume'].sum() / total_vol * 100)
            if 'short_volume' in trades_df.columns and 'total_volume' in trades_df.columns:
                total_vol = trades_df['total_volume'].sum()
                if total_vol > 0:
                    summary['short_ratio'] = float(trades_df['short_volume'].sum() / total_vol * 100)
            summary['total_volume'] = float(trades_df['total_volume'].sum()) if 'total_volume' in trades_df.columns else 0

        return {'trades': trades_df, 'summary': summary}

    # ──────────────────────────────────────────────
    # 数据清洗管道
    # ──────────────────────────────────────────────

    def clean_pipeline(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准数据清洗管道"""
        df = self._remove_duplicates(df)
        df = self._fill_missing(df)
        df = self._mark_outliers(df)
        df = self._align_timezone(df)
        return df

    def _clean_option_chain(self, df: pd.DataFrame) -> pd.DataFrame:
        """期权链专用清洗"""
        df = self.clean_pipeline(df)

        # 确保必要列存在
        required = ['strike', 'type', 'open_interest']
        for col in required:
            if col not in df.columns:
                logger.warning(f"期权链缺少必要列: {col}")
                if col == 'open_interest':
                    df[col] = 0
                elif col == 'type':
                    df[col] = 'CALL'

        # 填充 implied_volatility 默认值
        if 'implied_volatility' not in df.columns:
            df['implied_volatility'] = 0.2

        # 填充 days_to_expiry
        if 'days_to_expiry' not in df.columns and 'expiry' in df.columns:
            today = pd.Timestamp.now()
            df['days_to_expiry'] = (pd.to_datetime(df['expiry']) - today).dt.days.clip(lower=1)

        # 过滤 OI > 0
        df = df[df['open_interest'] >= 0]

        return df

    def _clean_trade_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """交易数据专用清洗"""
        if df.empty:
            return df
        df = self.clean_pipeline(df)

        # 过滤异常成交量
        if 'total_volume' in df.columns:
            q99 = df['total_volume'].quantile(0.99)
            df = df[df['total_volume'] <= q99 * 5]

        return df

    # ──────────────────────────────────────────────
    # 清洗子步骤
    # ──────────────────────────────────────────────

    @staticmethod
    def _remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
        before = len(df)
        df = df.drop_duplicates()
        after = len(df)
        if before > after:
            logger.debug(f"去重: {before} → {after} 行")
        return df

    @staticmethod
    def _fill_missing(df: pd.DataFrame) -> pd.DataFrame:
        """填充缺失值：数值列用 0，字符串列用空字符串"""
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(0)
            else:
                df[col] = df[col].fillna('')
        return df

    @staticmethod
    def _mark_outliers(df: pd.DataFrame) -> pd.DataFrame:
        """标记异常值（添加 outlier_flag 列）"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df['outlier_flag'] = False
        for col in numeric_cols:
            if col == 'outlier_flag':
                continue
            q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                lower, upper = q1 - 5 * iqr, q3 + 5 * iqr
                df.loc[(df[col] < lower) | (df[col] > upper), 'outlier_flag'] = True
        return df

    @staticmethod
    def _align_timezone(df: pd.DataFrame) -> pd.DataFrame:
        """对齐时间列为美东时区"""
        time_cols = ['timestamp', 'datetime', 'date', 'time', 'trade_time']
        et = pytz.timezone('US/Eastern')
        for col in time_cols:
            if col in df.columns:
                try:
                    df[col] = pd.to_datetime(df[col], utc=True)
                    df[col] = df[col].dt.tz_convert(et)
                except Exception:
                    pass
        return df

    # ──────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────

    def _resolve_path(self, file_path: str) -> Path:
        p = Path(file_path)
        if p.is_absolute():
            return p
        full = self.data_root / p
        if full.exists():
            return full
        return p  # 回退到原始路径

    @staticmethod
    def _detect_format(file_path: Path) -> str:
        ext = file_path.suffix.lower()
        if ext == '.parquet':
            return 'parquet'
        elif ext in ('.csv', '.txt'):
            return 'csv'
        elif ext in ('.h5', '.hdf5', '.hdf'):
            return 'hdf5'
        return 'csv'

    def _load_with_polars(self, path: Path, fmt: str) -> pd.DataFrame:
        try:
            if fmt == 'parquet':
                df_pl = pl.read_parquet(str(path))
            else:
                df_pl = pl.read_csv(str(path))
            return df_pl.to_pandas()
        except Exception as e:
            logger.warning(f"Polars 加载失败，降级到 Pandas: {e}")
            return self._load_with_pandas(path, fmt)

    @staticmethod
    def _load_with_pandas(path: Path, fmt: str) -> pd.DataFrame:
        if fmt == 'parquet' and PARQUET_AVAILABLE:
            return pq.read_table(str(path)).to_pandas()
        elif fmt == 'parquet':
            return pd.read_parquet(str(path))
        elif fmt == 'hdf5':
            return pd.read_hdf(str(path))
        else:
            return pd.read_csv(str(path))

    # ──────────────────────────────────────────────
    # Parquet 持久化 (P2-2: 批量数据框架)
    # ──────────────────────────────────────────────

    def save_dataframe(
        self,
        df: pd.DataFrame,
        file_path: str,
        file_format: str = "parquet",
        compression: str = "snappy",
        use_polars: bool = True,
    ) -> Path:
        """保存 DataFrame 到本地文件系统

        Args:
            df: 要保存的 DataFrame
            file_path: 目标文件路径（可相对 data_root）
            file_format: "parquet" | "csv"
            compression: Parquet 压缩算法 (snappy/gzip/brotli/lz4/zstd)
            use_polars: 是否优先使用 Polars（写入更快）

        Returns:
            Path: 实际写入的文件路径
        """
        full_path = self.data_root / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if file_format == "parquet" and use_polars and POLARS_AVAILABLE:
            try:
                df_pl = pl.from_pandas(df)
                df_pl.write_parquet(str(full_path), compression=compression)
                logger.info(f"[Polars] 已保存: {full_path} ({len(df)} 行, 压缩={compression})")
                return full_path
            except Exception as e:
                logger.warning(f"Polars 写入失败，降级到 Pandas: {e}")

        if file_format == "parquet":
            if PARQUET_AVAILABLE:
                table = pa.Table.from_pandas(df)
                pq.write_table(table, str(full_path), compression=compression)
            else:
                df.to_parquet(str(full_path), compression=compression)
        else:
            df.to_csv(str(full_path), index=False)

        logger.info(f"已保存: {full_path} ({len(df)} 行)")
        return full_path

    def persist_daily_snapshot(
        self,
        symbol: str,
        date_str: str,
        option_chain: Optional[pd.DataFrame] = None,
        darkpool_df: Optional[pd.DataFrame] = None,
        gex_result: Optional[Dict[str, Any]] = None,
        resonance_vector: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Path]:
        """持久化单日完整数据快照（Parquet 格式）

        按 PRD 定义的目录结构组织：
          data/raw/options/{symbol}/{date}_options.parquet
          data/raw/spr/{symbol}/{date}_darkpool.parquet
          data/processed/{symbol}/{date}_gex.parquet
          data/processed/{symbol}/{date}_resonance.json

        Args:
            symbol: 标的代码
            date_str: 日期字符串 YYYY-MM-DD
            option_chain: 期权链 DataFrame
            darkpool_df: 暗盘交易 DataFrame
            gex_result: GEX 计算结果字典
            resonance_vector: 共振向量字典

        Returns:
            Dict[str, Path]: 各文件的保存路径
        """
        saved = {}

        # 期权链 → Parquet
        if option_chain is not None and not option_chain.empty:
            opt_path = f"options/{symbol}/{date_str}_options.parquet"
            saved['option_chain'] = self.save_dataframe(
                option_chain, opt_path, file_format="parquet"
            )

        # 暗盘 → Parquet
        if darkpool_df is not None and not darkpool_df.empty:
            dp_path = f"spr/{symbol}/{date_str}_darkpool.parquet"
            saved['darkpool'] = self.save_dataframe(
                darkpool_df, dp_path, file_format="parquet"
            )

        # GEX 结果 → Parquet
        if gex_result:
            gex_df = pd.DataFrame([{
                'date': date_str,
                'total_gex': gex_result.get('total_gex', 0),
                'flip_level': gex_result.get('flip_level', 0),
                'regime': gex_result.get('regime', 'Neutral'),
                'put_wall_count': len(gex_result.get('put_walls', [])),
                'call_wall_count': len(gex_result.get('call_walls', [])),
            }])
            processed_dir = self.data_root.parent / "data" / "processed" / symbol
            processed_dir.mkdir(parents=True, exist_ok=True)
            gex_path = f"../data/processed/{symbol}/{date_str}_gex.parquet"
            saved['gex'] = self.save_dataframe(gex_df, gex_path, file_format="parquet")

        # 共振向量 → JSON
        if resonance_vector:
            import json
            processed_dir = self.data_root.parent / "data" / "processed" / symbol
            processed_dir.mkdir(parents=True, exist_ok=True)
            rv_path = processed_dir / f"{date_str}_resonance.json"
            with open(rv_path, 'w') as f:
                json.dump(resonance_vector, f, indent=2, default=str)
            saved['resonance_vector'] = rv_path
            logger.info(f"共振向量已持久化: {rv_path}")

        return saved


class ArchiveManager:
    """数据归档管理器 (P2-2)

    管理历史数据的版本化存储与检索，支持：
    - 按日期范围查询历史快照
    - 数据压缩与清理策略
    - 元数据索引

    Attributes:
        data_root: 数据根目录
        archive_root: 归档根目录
    """

    def __init__(self, data_root: str = "./data"):
        self.data_root = Path(data_root)
        self.archive_root = self.data_root / "archive"
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def list_available_dates(
        self,
        symbol: str = "SPX",
        data_type: str = "options",
    ) -> List[str]:
        """列出已有数据的日期列表

        Args:
            symbol: 标的代码
            data_type: 数据类型 (options/darkpool/gex)

        Returns:
            List[str]: 日期字符串列表 (YYYY-MM-DD)
        """
        if data_type == "options":
            search_dir = self.data_root / "raw" / "options" / symbol
        elif data_type == "darkpool":
            search_dir = self.data_root / "raw" / "spr" / symbol
        elif data_type == "gex":
            search_dir = self.data_root / "processed" / symbol
        else:
            search_dir = self.data_root / "raw" / data_type / symbol

        if not search_dir.exists():
            return []

        dates = set()
        for f in search_dir.glob("*.parquet"):
            # 解析文件名中的日期: YYYY-MM-DD_options.parquet
            name = f.stem
            parts = name.split('_')
            if parts and len(parts[0]) == 10:
                dates.add(parts[0])
        return sorted(dates, reverse=True)

    def load_date_range(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        data_type: str = "options",
    ) -> pd.DataFrame:
        """加载日期范围内的数据并合并

        Args:
            symbol: 标的代码
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            data_type: 数据类型

        Returns:
            pd.DataFrame: 合并后的 DataFrame
        """
        loader = BatchDataLoader(data_root=str(self.data_root / "raw"))
        dates = self.list_available_dates(symbol, data_type)
        dates_in_range = [d for d in dates if start_date <= d <= end_date]

        frames = []
        for d in dates_in_range:
            if data_type == "options":
                df = loader.load_option_chain(symbol, d)
            elif data_type == "darkpool":
                result = loader.load_darkpool_data(symbol, d)
                df = result.get('trades', pd.DataFrame())
            else:
                # GEX 等处理后数据
                processed_dir = self.data_root / "processed" / symbol
                gex_file = processed_dir / f"{d}_gex.parquet"
                if gex_file.exists():
                    df = loader.load_dataframe(str(gex_file))
                else:
                    continue

            if not df.empty:
                frames.append(df)

        if frames:
            return pd.concat(frames, ignore_index=True)
        return pd.DataFrame()

    def vacuum_old_data(self, keep_days: int = 90) -> int:
        """清理超过保留期限的旧数据

        Args:
            keep_days: 保留天数

        Returns:
            int: 删除的文件数
        """
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = 0

        for root_dir in [self.data_root / "raw", self.data_root / "processed"]:
            if not root_dir.exists():
                continue
            for parquet_file in root_dir.rglob("*.parquet"):
                mtime = datetime.fromtimestamp(parquet_file.stat().st_mtime)
                if mtime < cutoff:
                    parquet_file.unlink()
                    deleted += 1
                    logger.debug(f"已清理过期文件: {parquet_file}")

        logger.info(f"数据清理完成: 删除 {deleted} 个过期文件 (保留 {keep_days} 天)")
        return deleted


def init_data_structure(data_root: str = "./data") -> Dict[str, Path]:
    """初始化 PRD 定义的 Parquet 数据目录结构

    创建以下目录：
      data/raw/options/{symbol}/
      data/raw/spr/{symbol}/
      data/processed/{symbol}/
      data/archive/

    Args:
        data_root: 数据根目录

    Returns:
        Dict[str, Path]: 创建的目录路径
    """
    root = Path(data_root)
    dirs = {
        'raw_options': root / "raw" / "options" / "SPX",
        'raw_options_spy': root / "raw" / "options" / "SPY",
        'raw_spr': root / "raw" / "spr" / "SPY",
        'processed': root / "processed" / "SPX",
        'archive': root / "archive",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"数据目录已就绪: {path}")

    logger.info(
        f"Parquet 数据目录结构已初始化 (root={root.resolve()}), "
        f"共 {len(dirs)} 个目录"
    )
    return dirs


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def load_daily_snapshot(
    symbol: str = "SPX",
    date_str: Optional[str] = None,
    data_root: str = "./data/raw",
) -> Dict[str, Any]:
    """便捷函数：加载单日完整数据快照"""
    loader = BatchDataLoader(data_root=data_root)
    return {
        'option_chain': loader.load_option_chain(symbol, date_str),
        'darkpool': loader.load_darkpool_data(symbol, date_str),
    }
