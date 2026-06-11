"""
Multi-source Resonance V2.0 - Layer 2 拦截器与熔断

在 Layer 2 网关中实现数据质量门禁和熔断机制：
- InterceptionResult: 三种拦截状态 (pass_through / block / degraded)
- validate_and_intercept(): 数据质量检查 → 容错 JSON 生成
- Circuit Breaker: 连续异常熔断，阻止向 Layer 3 发送垃圾数据
- 95% 通过率熔断: 校验防线通过率 < 95% 触发阻断 (PRD §不可变审计日志)

复用 utils/fallback_manager.py 的 circuit_breakers 机制。
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import numpy as np

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope, ErrorSnapshot
from gateway.validator import SnapshotValidator
from utils.fallback_manager import FallbackManager
from utils.logger import getLogger

logger = getLogger('gateway.interceptor')


class InterceptionStatus(str, Enum):
    """拦截状态枚举"""
    PASS_THROUGH = "pass_through"    # 数据正常，放行至 Layer 3
    DEGRADED = "degraded"            # 数据降级，部分字段异常但仍可传递
    BLOCKED = "blocked"              # 数据严重异常，阻止传递，返回容错 JSON


@dataclass
class InterceptionResult:
    """拦截结果

    Attributes:
        status: 拦截状态 (pass_through / degraded / blocked)
        envelope: 放行时的 GatewayEnvelope (仅 PASS_THROUGH 和 DEGRADED 时非空)
        error_snapshot: 阻断时的 ErrorSnapshot (仅 BLOCKED 时非空)
        warnings: 警告消息列表
        anomaly_report: 异常检测报告
        intercepted_at: 拦截时间戳
    """
    status: InterceptionStatus
    envelope: Optional[GatewayEnvelope] = None
    error_snapshot: Optional[ErrorSnapshot] = None
    warnings: List[str] = field(default_factory=list)
    anomaly_report: Dict[str, Any] = field(default_factory=dict)
    intercepted_at: str = ""

    def __post_init__(self):
        if not self.intercepted_at:
            self.intercepted_at = datetime.now().isoformat()

    @property
    def is_passthrough(self) -> bool:
        """是否放行"""
        return self.status == InterceptionStatus.PASS_THROUGH

    @property
    def is_blocked(self) -> bool:
        """是否被阻断"""
        return self.status == InterceptionStatus.BLOCKED

    @property
    def is_degraded(self) -> bool:
        """是否降级"""
        return self.status == InterceptionStatus.DEGRADED


class GatewayInterceptor:
    """网关拦截器

    负责在 Layer 2 数据进入 Layer 3 前执行最后一道安全检查。
    集成 FallbackManager 的熔断机制，防止持续异常数据冲击 LLM。
    集成 95% 通过率熔断，当数据校验防线通过率持续低于阈值时阻断。

    Attributes:
        fallback: FallbackManager 实例，用于熔断状态管理
        circuit_breaker_threshold: 连续失败阈值，超过后触发熔断
        max_warnings_for_pass: 最多允许几个警告后仍放行
        pass_rate_threshold: 校验通过率阈值 (默认 95%，即 0.95)
        min_samples_for_circuit: 熔断判定所需最小样本数
    """

    # 网关拦截器专用模块名
    GATEWAY_MODULE = "gateway_interceptor"

    # 95% 通过率熔断常量
    PASS_RATE_THRESHOLD: float = 0.95
    MIN_SAMPLES_FOR_CIRCUIT: int = 5

    def __init__(
        self,
        circuit_breaker_threshold: int = 5,
        max_warnings_for_pass: int = 3,
        pass_rate_threshold: float = 0.95,
        db_manager=None,
    ):
        self.fallback = FallbackManager()
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.max_warnings_for_pass = max_warnings_for_pass
        self.pass_rate_threshold = pass_rate_threshold
        self._db = db_manager  # 可选的 DatabaseManager 实例 (延迟注入)

    def validate_and_intercept(
        self,
        envelope: GatewayEnvelope,
        strict_mode: bool = False,
        pass_rate_pct: Optional[float] = None,
    ) -> InterceptionResult:
        """验证 GatewayEnvelope 并执行拦截决策

        决策流程：
        1. 快照内容验证 (NaN/Inf/范围/枚举)
        2. 异常检测 (可疑组合)
        3. 95% 校验通过率熔断 (PRD §不可变审计日志)
        4. 数据质量标志检查
        5. 熔断状态检查 (FallbackManager)
        6. LLM 安全检查
        7. 决策: PASS_THROUGH / DEGRADED / BLOCKED

        Args:
            envelope: 网关信封
            strict_mode: 严格模式 - 任何警告都会触发 DEGRADED
            pass_rate_pct: 数据校验防线通过率 (0-100)，用于 95% 熔断判定

        Returns:
            InterceptionResult: 拦截结果
        """
        warnings: List[str] = []

        # ── 1. 快照验证 ──
        is_valid, snapshot_issues = SnapshotValidator.validate_envelope(envelope)
        if not is_valid:
            # 存在硬错误 → 阻止
            logger.error(f"快照验证失败，阻止传递: {snapshot_issues}")
            self.fallback.record_failure(self.GATEWAY_MODULE)
            return self._make_blocked(
                error_code="VALIDATION_FAILED",
                message=f"快照验证失败: {'; '.join(snapshot_issues[:3])}",
                warnings=warnings,
            )

        # 收集警告
        warnings.extend(snapshot_issues)

        # ── 2. 异常检测 ──
        anomaly_report = SnapshotValidator.detect_anomalies(envelope.snapshot)
        if anomaly_report['has_nan'] or anomaly_report['has_inf']:
            logger.error(f"检测到 NaN/Inf 异常: {anomaly_report}")
            self.fallback.record_failure(self.GATEWAY_MODULE)
            return self._make_blocked(
                error_code="ANOMALY_DETECTED",
                message="检测到 NaN 或 Inf 数值异常",
                anomaly_report=anomaly_report,
                warnings=warnings,
            )

        # ── 3. 95% 校验通过率熔断 (V2.0 数据校验防线) ──
        if pass_rate_pct is not None:
            circuit_result = self._check_pass_rate_circuit(pass_rate_pct)
            if circuit_result is not None:
                return circuit_result  # 熔断触发

        # ── 4. 数据质量标志检查 ──
        data_quality = envelope.snapshot.data_quality_flag
        if data_quality == "ERROR":
            logger.error("数据质量标志为 ERROR，阻止传递")
            self.fallback.record_failure(self.GATEWAY_MODULE)
            return self._make_blocked(
                error_code="DATA_QUALITY_ERROR",
                message="数据质量标志为 ERROR",
                anomaly_report=anomaly_report,
                warnings=warnings,
            )

        # ── 5. 熔断检查 ──
        if self.fallback.should_circuit_break(
            self.GATEWAY_MODULE, threshold=self.circuit_breaker_threshold
        ):
            logger.error("网关熔断已触发，阻止所有数据传递")
            return self._make_blocked(
                error_code="CIRCUIT_BREAKER_OPEN",
                message=f"网关熔断: 连续{self.circuit_breaker_threshold}次异常",
                anomaly_report=anomaly_report,
                warnings=warnings,
            )

        # ── 6. LLM 安全检查 ──
        if not envelope.snapshot.is_safe_for_llm():
            logger.warning("数据质量降级，不推荐传递给 LLM")
            warnings.append("data_quality_flag=DEGRADED: LLM 推理可信度受限")

        # ── 7. 决策 ──
        if data_quality == "DEGRADED":
            # 降级但仍传递
            self._record_degraded_pass(warnings)
            return InterceptionResult(
                status=InterceptionStatus.DEGRADED,
                envelope=envelope,
                warnings=warnings,
                anomaly_report=anomaly_report,
            )

        if strict_mode and len(warnings) > 0:
            # 严格模式：任何警告都降级
            self._record_degraded_pass(warnings)
            return InterceptionResult(
                status=InterceptionStatus.DEGRADED,
                envelope=envelope,
                warnings=warnings,
                anomaly_report=anomaly_report,
            )

        if len(warnings) > self.max_warnings_for_pass:
            logger.warning(f"警告过多 ({len(warnings)} > {self.max_warnings_for_pass})，降级处理")
            return InterceptionResult(
                status=InterceptionStatus.DEGRADED,
                envelope=envelope,
                warnings=warnings,
                anomaly_report=anomaly_report,
            )

        # ── 7. 放行 ──
        logger.info("网关放行: 所有检查通过 ✓")
        self.fallback.reset_failure_count(self.GATEWAY_MODULE)

        return InterceptionResult(
            status=InterceptionStatus.PASS_THROUGH,
            envelope=envelope,
            warnings=warnings,
            anomaly_report=anomaly_report,
        )

    def is_circuit_broken(self) -> bool:
        """检查网关是否处于熔断状态"""
        return self.fallback.should_circuit_break(
            self.GATEWAY_MODULE, threshold=self.circuit_breaker_threshold
        )

    def reset_circuit(self) -> None:
        """手动重置熔断状态"""
        self.fallback.reset_failure_count(self.GATEWAY_MODULE)
        logger.info("网关熔断已手动重置")

    def get_gateway_health(self) -> Dict[str, Any]:
        """获取网关健康状态"""
        module_status = self.fallback.get_module_status(self.GATEWAY_MODULE)
        return {
            'module': self.GATEWAY_MODULE,
            'status': module_status['status'],
            'failure_count': module_status['failure_count'],
            'is_circuit_broken': module_status['is_circuit_broken'],
            'breaker_threshold': self.circuit_breaker_threshold,
        }

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    def _check_pass_rate_circuit(
        self, pass_rate_pct: float
    ) -> Optional[InterceptionResult]:
        """检查 95% 校验通过率熔断 (PRD §不可变审计日志)

        基于 DataValidationPipeline 计算的历史通过率判断是否触发熔断。
        当从数据库加载历史通过率时，取最近 MIN_SAMPLES_FOR_CIRCUIT 次平均值。

        Args:
            pass_rate_pct: 本次运行的校验通过率 (0-100)

        Returns:
            InterceptionResult 如果熔断触发，否则 None
        """
        # 尝试从数据库加载历史通过率
        recent_rates = self._load_recent_pass_rates()
        recent_rates.append(pass_rate_pct)

        if len(recent_rates) < self.MIN_SAMPLES_FOR_CIRCUIT:
            return None  # 样本不足，不触发熔断

        recent_avg = float(np.mean(recent_rates[-self.MIN_SAMPLES_FOR_CIRCUIT:]))
        threshold_pct = self.pass_rate_threshold * 100

        if recent_avg < threshold_pct:
            reason = (
                f"95% 通过率熔断: 近{self.MIN_SAMPLES_FOR_CIRCUIT}次平均通过率 "
                f"{recent_avg:.1f}% < {threshold_pct:.0f}%"
            )
            logger.error(reason)
            self.fallback.record_failure(self.GATEWAY_MODULE)
            return self._make_blocked(
                error_code="VALIDATION_PASS_RATE_LOW",
                message=reason,
            )

        return None

    def _load_recent_pass_rates(self) -> list:
        """从数据库加载最近 N 次校验通过率"""
        if self._db is not None:
            try:
                return self._db.get_recent_pass_rates(
                    num_runs=self.MIN_SAMPLES_FOR_CIRCUIT
                )
            except Exception as e:
                logger.warning(f"从数据库加载通过率失败: {e}")
        return []

    def get_validation_health(self) -> Dict[str, Any]:
        """获取校验防线健康状态 (含通过率) """
        recent_rates = self._load_recent_pass_rates()
        avg = float(np.mean(recent_rates)) if recent_rates else 100.0
        return {
            'recent_pass_rates': recent_rates,
            'average_pass_rate': round(avg, 1),
            'threshold_pct': self.pass_rate_threshold * 100,
            'is_healthy': avg >= self.pass_rate_threshold * 100,
            'sample_count': len(recent_rates),
        }

    def _make_blocked(
        self,
        error_code: str,
        message: str,
        anomaly_report: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
    ) -> InterceptionResult:
        """构建 BLOCKED 拦截结果"""
        error_snapshot = SnapshotValidator.create_error_snapshot(error_code, message)

        return InterceptionResult(
            status=InterceptionStatus.BLOCKED,
            error_snapshot=error_snapshot,
            anomaly_report=anomaly_report or {},
            warnings=warnings or [],
        )

    def _record_degraded_pass(self, warnings: List[str]) -> None:
        """记录降级放行事件"""
        logger.warning(f"降级放行: {warnings}")


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def validate_and_intercept(
    envelope: GatewayEnvelope,
    strict_mode: bool = False,
    pass_rate_pct: Optional[float] = None,
    db_manager=None,
) -> InterceptionResult:
    """便捷函数：验证并拦截 (V2.0 含 95% 通过率熔断)

    Args:
        envelope: 网关信封
        strict_mode: 严格模式
        pass_rate_pct: 数据校验通过率 (0-100)
        db_manager: DatabaseManager 实例 (用于加载历史通过率)

    Returns:
        InterceptionResult: 拦截结果
    """
    interceptor = GatewayInterceptor(
        db_manager=db_manager,
    )
    return interceptor.validate_and_intercept(
        envelope,
        strict_mode=strict_mode,
        pass_rate_pct=pass_rate_pct,
    )
