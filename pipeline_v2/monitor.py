"""
Multi-source Resonance V2.0 - 流水线运行监控

记录每阶段耗时、成功/失败状态、数据量统计，
并将运行日志写入数据库供 Dashboard 展示。
"""

import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from utils.logger import getLogger
from pipeline_v2.orchestrator import PipelineContext

logger = getLogger('pipeline_v2.monitor')


@dataclass
class StageMetrics:
    """单阶段运行指标

    Attributes:
        stage_name: 阶段名称
        status: 执行状态 (success / failed / skipped)
        duration_ms: 执行耗时 (毫秒)
        input_size: 输入数据量统计
        output_size: 输出数据量统计
        error_message: 错误信息
        started_at: 开始时间
        completed_at: 完成时间
    """
    stage_name: str
    status: str = "pending"
    duration_ms: int = 0
    input_size: Dict[str, Any] = field(default_factory=dict)
    output_size: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    started_at: str = ""
    completed_at: str = ""


@dataclass
class PipelineRunMetrics:
    """单次流水线运行指标

    Attributes:
        run_id: 流水线运行 ID
        target_date: 目标日期
        overall_status: 整体状态 (success / partial / failed)
        total_duration_ms: 总耗时
        stages: 各阶段指标列表
    """
    run_id: str
    target_date: str
    overall_status: str = "running"
    total_duration_ms: int = 0
    stages: List[StageMetrics] = field(default_factory=list)


class PipelineMonitor:
    """流水线运行监控器

    记录每阶段耗时、成功/失败状态、数据量统计，
    支持将运行日志写入数据库。

    Attributes:
        current_run: 当前运行的指标
        history: 历史运行指标 (内存缓存)
    """

    def __init__(self, max_history: int = 100):
        self.current_run: Optional[PipelineRunMetrics] = None
        self.history: List[PipelineRunMetrics] = []
        self.max_history = max_history

    def start_run(self, run_id: str, target_date: str) -> None:
        """开始新一次流水线运行监控

        Args:
            run_id: 流水线运行 ID
            target_date: 目标日期
        """
        self.current_run = PipelineRunMetrics(
            run_id=run_id,
            target_date=target_date,
        )
        logger.info(f"监控启动: run_id={run_id[:8]}..., date={target_date}")

    def record_stage_start(self, stage_name: str) -> StageMetrics:
        """记录阶段开始

        Args:
            stage_name: 阶段名称

        Returns:
            StageMetrics: 阶段指标对象
        """
        metrics = StageMetrics(
            stage_name=stage_name,
            started_at=datetime.now().isoformat(),
        )
        if self.current_run:
            self.current_run.stages.append(metrics)
        return metrics

    def record_stage_end(
        self,
        stage_name: str,
        status: str,
        duration_ms: int,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: str = "",
    ) -> None:
        """记录阶段结束

        Args:
            stage_name: 阶段名称
            status: 执行状态
            duration_ms: 耗时
            input_data: 输入统计
            output_data: 输出统计
            error_message: 错误信息
        """
        if not self.current_run:
            return

        for stage in self.current_run.stages:
            if stage.stage_name == stage_name and stage.status == "pending":
                stage.status = status
                stage.duration_ms = duration_ms
                stage.input_size = input_data or {}
                stage.output_size = output_data or {}
                stage.error_message = error_message
                stage.completed_at = datetime.now().isoformat()
                break

    def end_run(self, ctx: PipelineContext) -> PipelineRunMetrics:
        """结束当前运行监控

        Args:
            ctx: 流水线上下文

        Returns:
            PipelineRunMetrics: 完整运行指标
        """
        if not self.current_run:
            return PipelineRunMetrics(run_id="", target_date="")

        run = self.current_run

        # 判断整体状态
        if not ctx.errors:
            run.overall_status = "success"
        elif len(ctx.errors) < 3:
            run.overall_status = "partial"
        else:
            run.overall_status = "failed"

        run.total_duration_ms = int(ctx.elapsed_seconds * 1000)

        # 存入历史
        self.history.append(run)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # 持久化到数据库
        self._persist_run(run)

        logger.info(
            f"监控结束: status={run.overall_status}, "
            f"duration={run.total_duration_ms}ms, stages={len(run.stages)}"
        )

        self.current_run = None
        return run

    def _persist_run(self, run: PipelineRunMetrics) -> None:
        """持久化运行指标到数据库"""
        try:
            from database.db_manager import DatabaseManager
            db = DatabaseManager()

            import json
            for stage in run.stages:
                db.connection.execute("""
                    INSERT OR REPLACE INTO system_config
                    (key, value, description, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    f"pipeline_run_{run.run_id}_{stage.stage_name}",
                    json.dumps({
                        'run_id': run.run_id,
                        'target_date': run.target_date,
                        'stage': stage.stage_name,
                        'status': stage.status,
                        'duration_ms': stage.duration_ms,
                        'error': stage.error_message,
                        'started_at': stage.started_at,
                        'completed_at': stage.completed_at,
                    }),
                    f"Pipeline V2.0 stage metric: {stage.stage_name}",
                ))
            db.connection.commit()

            logger.debug(f"运行指标已持久化: {run.run_id[:8]}...")
        except Exception as e:
            logger.debug(f"指标持久化跳过: {e}")

    def get_latest_run(self) -> Optional[PipelineRunMetrics]:
        """获取最近一次运行指标"""
        if self.history:
            return self.history[-1]
        return None

    def get_run_summary(self) -> Dict[str, Any]:
        """获取运行摘要统计"""
        if not self.history:
            return {'total_runs': 0}

        success_count = sum(1 for r in self.history if r.overall_status == 'success')
        partial_count = sum(1 for r in self.history if r.overall_status == 'partial')
        failed_count = sum(1 for r in self.history if r.overall_status == 'failed')

        avg_duration = sum(r.total_duration_ms for r in self.history) / len(self.history)

        return {
            'total_runs': len(self.history),
            'success_rate': round(success_count / len(self.history) * 100, 1),
            'success_count': success_count,
            'partial_count': partial_count,
            'failed_count': failed_count,
            'avg_duration_ms': int(avg_duration),
        }
