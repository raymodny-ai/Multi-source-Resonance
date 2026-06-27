"""
Multi-source Resonance V2.0 - 流水线编排器

串联 Layer 1 → Layer 2 → Layer 3 的六阶段批处理流水线。
支持完整运行、单日回测、降级策略。
"""

import os
import time
import uuid
import asyncio
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import Config
from utils.logger import getLogger
from utils.fallback_manager import FallbackManager

logger = getLogger('pipeline_v2.orchestrator')


@dataclass
class PipelineContext:
    """流水线上下文 — 在阶段间传递中间结果

    Attributes:
        run_id: 流水线运行 ID (UUID)
        start_time: 流水线启动时间
        current_stage: 当前阶段名称
        stage_results: 各阶段中间结果 (stage_name → result)
        errors: 错误列表
        metadata: 扩展元数据
    """
    run_id: str = ""
    start_time: float = 0.0
    current_stage: str = ""
    stage_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.run_id:
            self.run_id = str(uuid.uuid4())
        if not self.start_time:
            self.start_time = time.time()

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def set_result(self, stage: str, data: Any) -> None:
        self.stage_results[stage] = data

    def get_result(self, stage: str) -> Optional[Any]:
        return self.stage_results.get(stage)

    def add_error(self, stage: str, error: Exception) -> None:
        self.errors.append({
            'stage': stage,
            'error_type': type(error).__name__,
            'message': str(error),
            'timestamp': datetime.now().isoformat(),
        })


class PipelineOrchestrator:
    """V2.0 三层解耦流水线编排器

    六阶段处理:
    1. STAGE_INGEST   — 数据下载与加载
    2. STAGE_COMPUTE  — Layer 1 全量数学计算
    3. STAGE_REDUCE   — 多因子降维
    4. STAGE_GATEWAY  — Layer 2 JSON 封装与校验
    5. STAGE_INFER    — Layer 3 LLM 推理
    6. STAGE_DISPATCH — 报告分发

    Attributes:
        fallback: FallbackManager 实例
        output_dir: 报告输出目录
        db: DatabaseManager 实例（延迟加载）
    """

    def __init__(self, output_dir: Optional[str] = None):
        self.fallback = FallbackManager()
        self.output_dir = output_dir or Config.PIPELINE_OUTPUT_DIR
        self._db = None
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    @property
    def db(self):
        if self._db is None:
            from database.db_manager import DatabaseManager
            self._db = DatabaseManager()
        return self._db

    async def run_full_pipeline(
        self,
        target_date: Optional[date] = None,
        skip_llm: bool = False,
    ) -> PipelineContext:
        """运行完整的六阶段流水线

        Args:
            target_date: 目标日期（默认今天）
            skip_llm: 跳过 LLM 推理阶段（仅输出 Layer 2 JSON）

        Returns:
            PipelineContext: 包含各阶段结果的上下文
        """
        ctx = PipelineContext()
        if target_date is None:
            target_date = date.today()

        logger.info(f"========== Pipeline V2.0 启动 ==========")
        logger.info(f"Run ID: {ctx.run_id}")
        logger.info(f"Target Date: {target_date}")
        logger.info(f"Skip LLM: {skip_llm}")

        try:
            # Stage 1: 数据加载
            ctx = await self._stage_ingest(ctx, target_date)
            if ctx.has_errors:
                logger.error("Stage 1 失败，流水线终止")
                return ctx

            # Stage 2: Layer 1 计算
            ctx = await self._stage_compute(ctx, target_date)
            if ctx.has_errors:
                logger.error("Stage 2 失败，流水线终止")
                return ctx

            # Stage 3: 降维
            ctx = await self._stage_reduce(ctx, target_date)
            if ctx.has_errors:
                logger.error("Stage 3 失败，流水线终止")
                return ctx

            # Stage 4: 网关
            ctx = await self._stage_gateway(ctx, target_date)
            if ctx.has_errors:
                logger.error("Stage 4 失败，流水线终止")
                return ctx

            # Stage 5: LLM 推理
            if not skip_llm:
                ctx = await self._stage_infer(ctx, target_date)
            else:
                logger.info("Stage 5 (LLM) 已跳过")
                ctx.set_result('infer', None)

            # Stage 6: 报告分发
            ctx = await self._stage_dispatch(ctx, target_date)

            # 持久化网关快照
            self._persist_gateway_snapshot(ctx, target_date)

        except Exception as e:
            logger.error(f"流水线执行异常: {e}", exc_info=True)
            ctx.add_error('pipeline', e)

        finally:
            elapsed = ctx.elapsed_seconds
            logger.info(f"========== Pipeline V2.0 完成 (耗时 {elapsed:.1f}s) ==========")
            if ctx.errors:
                logger.warning(f"流水线错误数: {len(ctx.errors)}")

        return ctx

    # ──────────────────────────────────────────────
    # 各阶段实现
    # ──────────────────────────────────────────────

    async def _stage_ingest(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 1: 数据下载与加载"""
        ctx.current_stage = 'ingest'
        logger.info("--- Stage 1: Data Ingestion ---")

        try:
            from data_fetchers.batch_loader import BatchDataLoader
            loader = BatchDataLoader()

            # 加载 SPX 期权链数据
            option_data = loader.load_option_chain(underlying="SPX")
            # 加载暗盘数据
            darkpool_data = loader.load_darkpool_data()
            # 执行数据清洗
            if option_data is not None and not (hasattr(option_data, 'empty') and option_data.empty):
                option_data = loader.clean_pipeline(option_data)

            result = {
                'option_data': option_data,
                'darkpool_data': darkpool_data,
                'target_date': target_date,
            }
            ctx.set_result('ingest', result)

            logger.info(f"Stage 1 完成: 期权数据={option_data is not None}, 暗盘数据={darkpool_data is not None}")
        except Exception as e:
            logger.error(f"Stage 1 失败: {e}")
            ctx.add_error('ingest', e)
            # 使用模拟数据降级
            ctx.set_result('ingest', {
                'option_data': None,
                'darkpool_data': None,
                'target_date': target_date,
                'degraded': True,
            })

        return ctx

    async def _stage_compute(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 2: Layer 1 全量数学计算"""
        ctx.current_stage = 'compute'
        logger.info("--- Stage 2: Layer 1 Computation ---")

        try:
            ingest_result = ctx.get_result('ingest') or {}
            option_data = ingest_result.get('option_data')
            darkpool_data = ingest_result.get('darkpool_data')
            is_degraded = ingest_result.get('degraded', False)

            result = {}

            # 提取标的现价 (从期权链数据或默认值)
            spot_price = 5500.0  # SPX 默认值
            if option_data is not None and hasattr(option_data, 'attrs'):
                spot_price = float(option_data.attrs.get('spot_price', spot_price))
            elif option_data is not None and 'spot_price' in getattr(option_data, 'columns', []):
                spot_price = float(option_data['spot_price'].iloc[0])

            # GEX 计算 (V2.0: 传递 spot_price 参数)
            from quant_logic.gex_calculator import GEXCalculator
            gex_calc = GEXCalculator()
            if option_data is not None:
                gex_result = gex_calc.calculate_portfolio_gex_vectorized(
                    option_data, spot_price, symbol='SPX'  # 标的是 SPX
                )
            else:
                gex_result = gex_calc._empty_gex_result()
            result['gex'] = gex_result
            result['gex']['spot_price'] = spot_price  # 回传现价

            # Vanna/Charm 二阶希腊字母计算 (V2.0 PRD §Vanna 敞口)
            # 从 bs_engine 获取全量 Greeks，聚合 OI 加权 Vanna 暴露
            vanna_net_exposure = 0.0
            charm_net_exposure = 0.0
            if option_data is not None and not option_data.empty:
                try:
                    from quant_logic.bs_engine import VectorizedBSEngine
                    bs_engine = VectorizedBSEngine()
                    df_valid = option_data[option_data['open_interest'] > 0].copy()
                    if not df_valid.empty:
                        greeks = bs_engine.compute_all_greeks(
                            S=np.full(len(df_valid), spot_price),
                            K=df_valid['strike'].to_numpy(dtype=float),
                            sigma=df_valid.get('implied_volatility', 0.2).to_numpy(dtype=float),
                            T=(df_valid.get('days_to_expiry', 30) / 365.0).to_numpy(dtype=float),
                            option_types=df_valid['type'].to_numpy(),
                        )
                        oi = df_valid['open_interest'].to_numpy(dtype=float)
                        # Vanna 暴露 = sum(Vanna_i * 100 * OI_i * S)
                        vanna_contrib = greeks.vanna * 100 * oi * spot_price
                        vanna_net_exposure = float(np.sum(vanna_contrib))
                        # Charm 暴露 = sum(Charm_i * 100 * OI_i * S)
                        charm_contrib = greeks.charm * 100 * oi * spot_price
                        charm_net_exposure = float(np.sum(charm_contrib))
                        logger.info(
                            f"Vanna/Charm 计算完成: VEX=${vanna_net_exposure/1e6:.1f}M, "
                            f"CEX=${charm_net_exposure/1e6:.1f}M"
                        )
                except Exception as vex_err:
                    logger.warning(f"Vanna/Charm 计算降级: {vex_err}，使用默认值 0")
            result['vanna_exposure'] = vanna_net_exposure
            result['charm_exposure'] = charm_net_exposure

            # 暗盘验证
            from quant_logic.darkpool_verifier import DarkPoolVerifier
            dp_verifier = DarkPoolVerifier()
            if darkpool_data is not None:
                dix_val = darkpool_data.get('dix_value', 50.0)
                dix_pct = dp_verifier.calculate_dix_percentile(
                    dix_val,
                    dix_historical=darkpool_data.get('dix_historical', []),
                )
                is_aggregated = darkpool_data.get('aggregated_signal', False)
                dbmf_rec = darkpool_data.get('dbmf_ma5_recovery', False)
                accumulation = dp_verifier.classify_accumulation_regime(
                    dix_value=dix_val,
                    dix_percentile=dix_pct,
                    aggregated_signal=is_aggregated,
                    dbmf_recovery=dbmf_rec,
                )
            else:
                dix_pct = 50.0
                dix_val = 50.0
                accumulation = "Neutral"
            result['darkpool'] = {
                'dix_percentile': dix_pct,
                'accumulation_regime': accumulation,
                'dix_value': dix_val,
            }

            # VIX 分析
            from quant_logic.vix_analyzer import VIXAnalyzer
            vix_analyzer = VIXAnalyzer()
            try:
                vix_result = vix_analyzer.get_analysis_result()
            except Exception:
                vix_result = {
                    'term_structure': 'NEUTRAL',
                    'panic_premium_pct': 0.0,
                    'vanna_exposure': 0.0,
                }
            result['vix'] = vix_result

            # 加密杠杆
            from quant_logic.crypto_leverage_cleaner import CryptoLeverageCleaner
            crypto_cleaner = CryptoLeverageCleaner()
            try:
                crypto_result = crypto_cleaner.get_cleaner_result()
            except Exception:
                crypto_result = {
                    'leverage_state': 'NORMAL',
                    'oi_change_pct': 0.0,
                    'funding_rate': 0.0,
                }
            result['crypto'] = crypto_result

            # 跨资产共振分析 (P2-1)
            cross_asset_result = self._compute_cross_asset(result, spot_price)
            result['cross_asset'] = cross_asset_result

            result['degraded'] = is_degraded
            ctx.set_result('compute', result)

            logger.info("Stage 2 完成")
        except Exception as e:
            logger.error(f"Stage 2 失败: {e}")
            ctx.add_error('compute', e)

        return ctx

    async def _stage_reduce(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 3: 多因子降维"""
        ctx.current_stage = 'reduce'
        logger.info("--- Stage 3: Dimension Reduction ---")

        try:
            compute_result = ctx.get_result('compute') or {}
            gex = compute_result.get('gex', {})
            darkpool = compute_result.get('darkpool', {})
            vix = compute_result.get('vix', {})
            crypto = compute_result.get('crypto', {})

            from quant_logic.dimension_reducer import DimensionReducer

            reducer = DimensionReducer()
            # V2.0: 使用 bs_engine 计算的 Vanna/Charm 暴露 (替代 VIX 粗略估计)
            vanna_net = compute_result.get('vanna_exposure', vix.get('vanna_exposure', 0.0))

            # P2-1: 跨资产共振参数
            cross_asset = compute_result.get('cross_asset', {})
            ca_coherence = cross_asset.get('coherence_score', 50.0)
            ca_direction = cross_asset.get('alignment_direction', 'NEUTRAL')
            ca_strength = cross_asset.get('resonance_strength', 'None')
            ca_aligned = cross_asset.get('alignment_count', 0)

            vector = reducer.compute_resonance_vector(
                underlying_asset="SPX",
                spot_price=gex.get('spot_price', 5500.0),
                net_gex=gex.get('total_gex', 0.0),
                gex_regime=gex.get('regime', 'Neutral'),
                gamma_flip_level=gex.get('flip_level', 0.0),
                put_wall_strikes=gex.get('put_walls', []),
                call_wall_strikes=gex.get('call_walls', []),
                gex_by_strike=gex.get('gex_by_strike', {}),
                dix_value=darkpool.get('dix_value', 50.0),
                dix_signal=darkpool.get('dix_value', 50.0) > 45,
                darkpool_aggregated=False,
                accumulation_regime=darkpool.get('accumulation_regime', 'Neutral'),
                vx1=vix.get('vx1', 15.0),
                vx2=vix.get('vx2', 15.5),
                vix_spot=vix.get('vix_spot', 15.0),
                vix_state=vix.get('term_structure', 'NEUTRAL'),
                panic_premium=vix.get('panic_premium_pct', 0.0),
                vanna_net_exposure=vanna_net,
                crypto_leverage_state=crypto.get('leverage_state', 'NORMAL'),
                crypto_oi_change_pct=crypto.get('oi_change_pct', 0.0),
                funding_rate=crypto.get('funding_rate', 0.0),
                hawkes_ratio=0.5,
                hawkes_state='SUBCRITICAL',
                # P2-1: 跨资产共振
                cross_asset_coherence=ca_coherence,
                cross_asset_direction=ca_direction,
                cross_asset_strength=ca_strength,
                cross_asset_aligned=ca_aligned,
            )

            ctx.set_result('reduce', vector)
            logger.info(f"Stage 3 完成: 共振得分={vector.resonance_intensity_score}")
        except Exception as e:
            logger.error(f"Stage 3 失败: {e}")
            ctx.add_error('reduce', e)

        return ctx

    async def _stage_gateway(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 4: Layer 2 JSON 网关"""
        ctx.current_stage = 'gateway'
        logger.info("--- Stage 4: JSON Gateway ---")

        try:
            vector = ctx.get_result('reduce')
            if vector is None:
                raise ValueError("Stage 3 未产出共振向量")

            from gateway.serializer import GatewaySerializer
            from gateway.interceptor import GatewayInterceptor

            # 序列化
            serializer = GatewaySerializer()
            envelope = serializer.from_resonance_vector(
                vector,
                pipeline_run_id=ctx.run_id,
                processing_duration_ms=int(ctx.elapsed_seconds * 1000),
            )

            # 验证和拦截
            interceptor = GatewayInterceptor()
            interception = interceptor.validate_and_intercept(envelope)

            ctx.set_result('gateway', {
                'envelope': envelope,
                'interception': interception,
                'json': serializer.to_llm_prompt_json(envelope),
            })

            status_emoji = "✓" if interception.is_passthrough else "⚠️" if interception.is_degraded else "❌"
            logger.info(f"Stage 4 完成: 拦截状态={interception.status.value} {status_emoji}")
        except Exception as e:
            logger.error(f"Stage 4 失败: {e}")
            ctx.add_error('gateway', e)

        return ctx

    async def _stage_infer(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 5: Layer 3 LLM 推理"""
        ctx.current_stage = 'infer'
        logger.info("--- Stage 5: LLM Inference ---")

        try:
            gateway_result = ctx.get_result('gateway')
            if not gateway_result:
                raise ValueError("Stage 4 未产出网关数据")

            envelope = gateway_result['envelope']
            interception = gateway_result['interception']

            if interception.is_blocked:
                logger.warning("Stage 5 跳过: 网关拦截状态为 BLOCKED")
                ctx.set_result('infer', {
                    'blocked': True,
                    'error_snapshot': interception.error_snapshot,
                })
                return ctx

            # 获取 LLM Provider
            provider = self._get_llm_provider()
            if provider is None:
                logger.warning("Stage 5 跳过: LLM Provider 不可用")
                ctx.set_result('infer', {'degraded': True, 'reason': 'LLM not configured'})
                return ctx

            # 构建 Prompt (V2.6 时间混淆测试)
            from llm_inference.prompt_builder import PromptBuilder
            from gateway.serializer import GatewaySerializer
            from datetime import date

            builder = PromptBuilder()

            # V2.6: 脱敏 JSON (阻断 LLM 对历史宏观事件的记忆联想)
            obfuscated_json = GatewaySerializer.to_obfuscated_json(
                envelope,
                current_real_date=date.today(),
            )

            # V2.6: 加载脱敏 Few-Shot 样例
            obfuscated_few_shot = builder.load_few_shot_examples(
                num_examples=2,
                min_resonance_score=70,
                current_real_date=date.today(),
            )

            system_prompt = builder.build_system_prompt()
            user_prompt = builder.build_user_prompt(
                envelope,
                obfuscated_asset="Asset_A",                  # 脱敏资产
                obfuscated_json_data=obfuscated_json,        # 脱敏 JSON
                relative_time_marker="Day 0",                 # 相对时间
                few_shot_examples=obfuscated_few_shot,       # 脱敏 Few-Shot
            )

            # 调用 LLM
            response = await provider.generate(user_prompt, system_prompt)

            # 解析输出
            from llm_inference.response_parser import ResponseParser
            briefing = ResponseParser.parse_strategy_briefing(response.content)

            # 幻觉检测
            hallu_flags = ResponseParser.detect_hallucination(response.content, envelope)
            briefing.hallucination_flags = hallu_flags

            ctx.set_result('infer', {
                'response': response,
                'briefing': briefing,
                'hallucination_flags': hallu_flags,
            })

            logger.info(
                f"Stage 5 完成: tokens={response.total_tokens}, "
                f"latency={response.latency_ms}ms, hallucinations={len(hallu_flags)}"
            )
        except Exception as e:
            logger.error(f"Stage 5 失败: {e}")
            ctx.add_error('infer', e)
            ctx.set_result('infer', {
                'degraded': True,
                'reason': str(e),
            })

        return ctx

    async def _stage_dispatch(self, ctx: PipelineContext, target_date: date) -> PipelineContext:
        """Stage 6: 报告分发"""
        ctx.current_stage = 'dispatch'
        logger.info("--- Stage 6: Report Dispatch ---")

        try:
            gateway_result = ctx.get_result('gateway')
            infer_result = ctx.get_result('infer')
            envelope = gateway_result['envelope'] if gateway_result else None

            if envelope is None:
                raise ValueError("Stage 4 未产出信封数据")

            from llm_inference.report_composer import ReportComposer
            composer = ReportComposer(output_dir=self.output_dir)

            if infer_result and not infer_result.get('blocked') and not infer_result.get('degraded'):
                # 正常模式：完整报告
                briefing = infer_result.get('briefing')
                report_text = composer.compose_full_report(
                    envelope, briefing, pipeline_run_id=ctx.run_id
                )
            else:
                # 降级模式
                error_msg = infer_result.get('reason', 'LLM unavailable') if infer_result else 'No inference result'
                report_text = composer.compose_degraded_mode_report(envelope, error_msg)

            # 保存 Markdown 文件
            md_path = composer.to_markdown_file(report_text)
            ctx.set_result('dispatch', {
                'report_text': report_text,
                'markdown_path': md_path,
                'mode': 'degraded' if (infer_result and infer_result.get('degraded')) else 'full',
            })

            # 发送通知 (不阻塞主流程)
            try:
                self._send_notification(report_text, envelope)
            except Exception as notify_err:
                logger.warning(f"通知发送失败 (非致命): {notify_err}")

            logger.info(f"Stage 6 完成: 报告保存至 {md_path}")
        except Exception as e:
            logger.error(f"Stage 6 失败: {e}")
            ctx.add_error('dispatch', e)

        return ctx

    # ──────────────────────────────────────────────
    # 回测支持
    # ──────────────────────────────────────────────

    async def run_backtest(
        self,
        backtest_date: date,
    ) -> PipelineContext:
        """对指定历史日期执行 Layer 3 回测

        从数据库加载历史网关 JSON，重新运行 LLM 推理。

        Args:
            backtest_date: 回测日期

        Returns:
            PipelineContext 包含推理结果
        """
        logger.info(f"========== Pipeline V2.0 回测模式: {backtest_date} ==========")

        ctx = PipelineContext()

        try:
            # 从数据库加载历史快照
            snapshot_record = self.db.get_gateway_snapshot_by_date(backtest_date)
            if snapshot_record is None:
                raise ValueError(f"未找到 {backtest_date} 的网关快照")

            snapshot_json = snapshot_record.get('snapshot_json')
            if isinstance(snapshot_json, str):
                import json
                snapshot_json = json.loads(snapshot_json)

            # 重建 GatewayEnvelope
            from gateway.schemas import GatewayEnvelope
            envelope = GatewayEnvelope(**snapshot_json)

            ctx.set_result('gateway', {
                'envelope': envelope,
                'json': envelope.model_dump_json(indent=2),
            })

            # 重新运行 LLM 推理
            ctx = await self._stage_infer(ctx, backtest_date)

            # 生成回测报告
            from llm_inference.report_composer import ReportComposer
            composer = ReportComposer(output_dir=self.output_dir)
            infer_result = ctx.get_result('infer')

            if infer_result and infer_result.get('briefing'):
                report_text = composer.compose_full_report(
                    envelope, infer_result['briefing'], pipeline_run_id=ctx.run_id
                )
            else:
                report_text = composer.compose_degraded_mode_report(
                    envelope, "Backtest: LLM inference failed"
                )

            date_str = backtest_date.strftime('%Y%m%d')
            md_path = composer.to_markdown_file(report_text, f"backtest_briefing_{date_str}.md")
            ctx.set_result('dispatch', {'report_text': report_text, 'markdown_path': md_path})

            logger.info(f"回测完成: 报告保存至 {md_path}")

        except Exception as e:
            logger.error(f"回测失败: {e}")
            ctx.add_error('backtest', e)

        return ctx

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    def _get_llm_provider(self):
        """根据配置创建 LLM Provider 实例"""

    def _compute_cross_asset(
        self, result: dict, spot_price: float
    ) -> Dict[str, Any]:
        """计算跨资产共振一致性 (P2-1)

        从各维度提取所需参数，调用 CrossAssetResonanceEngine。

        Args:
            result: Stage 2 compute 结果字典
            spot_price: 标的现价

        Returns:
            cross_asset_result 字典
        """
        try:
            from quant_logic.cross_asset import CrossAssetResonanceEngine

            gex = result.get('gex', {})
            darkpool = result.get('darkpool', {})
            vix = result.get('vix', {})
            crypto = result.get('crypto', {})

            engine = CrossAssetResonanceEngine()
            ca_result = engine.analyze(
                net_gex=gex.get('total_gex', 0.0),
                gex_regime=gex.get('regime', 'Neutral'),
                gex_percentile=50.0,
                crypto_leverage_state=crypto.get('leverage_state', 'NORMAL'),
                crypto_oi_change_pct=crypto.get('oi_change_pct', 0.0),
                crypto_funding_rate=crypto.get('funding_rate', 0.0),
                vix_spot=vix.get('vix_spot', 15.0),
                vix_term_structure=vix.get('term_structure', 'NEUTRAL'),
                vix_panic_premium=vix.get('panic_premium_pct', 0.0),
                dix_value=darkpool.get('dix_value', 50.0),
                accumulation_regime=darkpool.get('accumulation_regime', 'Neutral'),
                dix_percentile=darkpool.get('dix_percentile', 50.0),
            )

            logger.info(
                f"跨资产共振分析完成: 一致性={ca_result.coherence_score:.1f}, "
                f"方向={ca_result.alignment_direction}, "
                f"强度={ca_result.resonance_strength}"
            )

            return {
                'coherence_score': ca_result.coherence_score,
                'alignment_direction': ca_result.alignment_direction,
                'resonance_strength': ca_result.resonance_strength,
                'alignment_count': ca_result.alignment_count,
                'total_assets': ca_result.total_assets,
            }
        except Exception as e:
            logger.warning(f"跨资产共振分析降级: {e}")
            return {
                'coherence_score': 50.0,
                'alignment_direction': 'NEUTRAL',
                'resonance_strength': 'None',
                'alignment_count': 0,
                'total_assets': 4,
                'error': str(e),
            }
        provider_name = Config.LLM_PROVIDER.lower()

        if provider_name == 'openai':
            if not Config.OPENAI_API_KEY:
                logger.warning("OPENAI_API_KEY 未配置")
                return None
            from llm_inference.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=Config.OPENAI_API_KEY,
                model=Config.OPENAI_MODEL,
                temperature=Config.LLM_TEMPERATURE,
                max_tokens=Config.LLM_MAX_TOKENS,
                timeout=Config.LLM_TIMEOUT,
                organization=Config.OPENAI_ORGANIZATION or None,
                base_url=Config.OPENAI_BASE_URL or None,
            )

        elif provider_name == 'anthropic':
            if not Config.ANTHROPIC_API_KEY:
                logger.warning("ANTHROPIC_API_KEY 未配置")
                return None
            from llm_inference.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=Config.ANTHROPIC_API_KEY,
                model=Config.ANTHROPIC_MODEL,
                temperature=Config.LLM_TEMPERATURE,
                max_tokens=Config.LLM_MAX_TOKENS,
                timeout=Config.LLM_TIMEOUT,
                base_url=Config.ANTHROPIC_BASE_URL or None,
            )

        else:
            logger.warning(f"Unknown LLM provider: {provider_name}")
            return None

    def _persist_gateway_snapshot(
        self, ctx: PipelineContext, target_date: date
    ) -> None:
        """持久化网关快照到数据库"""
        try:
            gateway_result = ctx.get_result('gateway')
            if not gateway_result:
                return

            envelope = gateway_result.get('envelope')
            interception = gateway_result.get('interception')

            if envelope is None:
                return

            snapshot_json = envelope.model_dump_json(indent=2)
            data_quality = envelope.snapshot.data_quality_flag
            resonance_score = envelope.snapshot.resonance_intensity_score
            interception_status = interception.status.value if interception else 'unknown'

            self.db.insert_gateway_snapshot(
                snapshot_date=target_date,
                pipeline_run_id=ctx.run_id,
                snapshot_json=snapshot_json,
                schema_version=envelope.schema_version,
                data_quality_flag=data_quality,
                resonance_score=resonance_score,
                processing_duration_ms=int(ctx.elapsed_seconds * 1000),
                interception_status=interception_status,
            )

            logger.debug(f"网关快照已持久化: {target_date}")
        except Exception as e:
            logger.warning(f"网关快照持久化失败 (非致命): {e}")

    def _send_notification(
        self, report_text: str, envelope
    ) -> None:
        """发送策略简报通知"""
        try:
            from notification.alert_sender import AlertSender
            sender = AlertSender()

            # 生成简化的纯文本摘要
            from llm_inference.prompt_builder import PromptBuilder
            builder = PromptBuilder()
            summary = builder.build_degraded_mode_prompt(
                type('Envelope', (), {'snapshot': envelope.snapshot})()
            )

            subject = (
                f"📊 Multi-source Resonance — "
                f"Daily Briefing (Score: {envelope.snapshot.resonance_intensity_score}/100)"
            )

            sender.send_alert(
                subject=subject,
                message=summary,
                alert_level="INFO",
            )

            logger.info("策略简报通知已发送")
        except ImportError:
            logger.debug("AlertSender 不可用，跳过通知")
        except Exception as e:
            logger.warning(f"通知发送失败: {e}")

    # ──────────────────────────────────────────────
    # 便捷方法
    # ──────────────────────────────────────────────

    @staticmethod
    async def run_daily() -> PipelineContext:
        """便捷方法：运行今日完整流水线"""
        orchestrator = PipelineOrchestrator()
        return await orchestrator.run_full_pipeline()

    @staticmethod
    async def run_backtest_for_date(date_str: str) -> PipelineContext:
        """便捷方法：指定日期回测

        Args:
            date_str: 日期字符串 (YYYY-MM-DD)
        """
        from datetime import datetime
        backtest_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        orchestrator = PipelineOrchestrator()
        return await orchestrator.run_backtest(backtest_date)
