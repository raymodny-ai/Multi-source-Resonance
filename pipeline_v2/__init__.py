"""
Multi-source Resonance V2.0 - 端到端批处理流水线

将三层架构串联为每日定时盘后任务：
    Stage 1: 数据下载与加载 (Layer 1 前置)
    Stage 2: 全量数学计算 (Layer 1)
    Stage 3: 多因子降维 (Layer 1 → Layer 2)
    Stage 4: JSON 网关 (Layer 2)
    Stage 5: LLM 推理 (Layer 3)
    Stage 6: 报告分发

核心组件:
- PipelineOrchestrator: 流水线编排器
- PipelineContext: 阶段间数据传递上下文
- StageRunner: 各阶段执行器
- PipelineMonitor: 运行监控与日志
"""

from pipeline_v2.orchestrator import PipelineOrchestrator, PipelineContext
from pipeline_v2.monitor import PipelineMonitor

__all__ = [
    'PipelineOrchestrator',
    'PipelineContext',
    'PipelineMonitor',
]
