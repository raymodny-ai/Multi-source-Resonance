"""
多源共振监控系统 - 异常容错与降级管理器

该模块提供系统级的容错机制，包括：
- 暗盘数据源的独立降级逻辑
- 失败计数与熔断机制
- 自动重试装饰器
- 优雅的错误恢复策略

使用示例:
    from utils.fallback_manager import FallbackManager, handle_fetch_errors
    
    # 使用降级管理器
    fallback = FallbackManager()
    result = fallback.handle_darkpool_fallback(
        squeezemetrics_success=True,
        chartexchange_success=False,
        stockgrid_success=True
    )
    
    # 使用重试装饰器
    @handle_fetch_errors(max_retries=3)
    async def fetch_data():
        ...
"""

from functools import wraps
from typing import Dict, List
from tenacity import retry, stop_after_attempt, wait_exponential
from utils.logger import getLogger

logger = getLogger('fallback_manager')


class FallbackManager:
    """异常容错与降级管理器
    
    负责处理各数据源的失败情况，实施降级策略，
    避免单点故障导致整个系统瘫痪。
    """
    
    def __init__(self):
        """初始化降级管理器"""
        self.logger = getLogger('fallback_manager')
        self.failure_counts: Dict[str, int] = {}  # 记录各模块失败次数
        self.circuit_breakers: Dict[str, bool] = {}  # 熔断状态
    
    def handle_darkpool_fallback(
        self,
        squeezemetrics_success: bool,
        chartexchange_success: bool,
        stockgrid_success: bool
    ) -> dict:
        """
        暗盘模块独立降级逻辑
        
        当多个暗盘数据源部分失败时，根据可用数据源数量决定降级策略：
        - FULL (3/3): 正常运行，三源校验
        - PARTIAL (1-2/3): 部分降级，使用可用数据源
        - DEGRADED (0/3): 极端退化，暗盘得分降为0，退化为纯GEX+DBMF模式
        
        Args:
            squeezemetrics_success: SqueezeMetrics是否成功获取DIX数据
            chartexchange_success: ChartExchange是否成功获取卖空比
            stockgrid_success: Stockgrid是否成功抓取净头寸
        
        Returns:
            dict: {
                'mode': str,              # 'FULL', 'PARTIAL', 'DEGRADED'
                'available_sources': list, # 可用数据源列表
                'fallback_action': str,   # 降级动作说明
                'warning_level': str      # 'NONE', 'WARNING', 'CRITICAL'
            }
        
        Examples:
            >>> fallback = FallbackManager()
            >>> result = fallback.handle_darkpool_fallback(True, False, True)
            >>> print(result['mode'])
            'PARTIAL'
        """
        sources = []
        if squeezemetrics_success:
            sources.append('SqueezeMetrics')
        if chartexchange_success:
            sources.append('ChartExchange')
        if stockgrid_success:
            sources.append('Stockgrid')
        
        success_count = len(sources)
        
        if success_count == 3:
            mode = 'FULL'
            action = '正常运行,三源校验'
            warning = 'NONE'
            self.logger.debug("暗盘数据源: FULL模式 - 所有数据源可用")
            
        elif success_count >= 1:
            mode = 'PARTIAL'
            sources_str = ", ".join(sources)
            action = f'部分降级,仅使用{sources_str}进行校验'
            warning = 'WARNING'
            self.logger.warning(f"暗盘数据源: PARTIAL模式 - 可用源: {sources_str}")
            
        else:
            mode = 'DEGRADED'
            action = '极端退化:暗盘得分降为0,退化为纯GEX+DBMF模式,发出CRITICAL警告'
            warning = 'CRITICAL'
            self.logger.critical("暗盘数据源: DEGRADED模式 - 所有数据源失效!")
        
        return {
            'mode': mode,
            'available_sources': sources,
            'fallback_action': action,
            'warning_level': warning
        }
    
    def record_failure(self, module_name: str):
        """
        记录模块失败
        
        每次调用会增加指定模块的失败计数，用于后续熔断判断。
        
        Args:
            module_name: 模块名称（如 'fetch_dix', 'calculate_gex'）
        
        Examples:
            >>> fallback = FallbackManager()
            >>> fallback.record_failure('fetch_dix')
        """
        if module_name not in self.failure_counts:
            self.failure_counts[module_name] = 0
        self.failure_counts[module_name] += 1
        
        count = self.failure_counts[module_name]
        self.logger.warning(f"模块 {module_name} 失败次数: {count}")
        
        # 如果达到阈值，触发熔断
        if self.should_circuit_break(module_name):
            self.circuit_breakers[module_name] = True
            self.logger.error(f"[CIRCUIT BREAK] 模块 {module_name} 已触发熔断!暂停请求")
    
    def should_circuit_break(self, module_name: str, threshold: int = 5) -> bool:
        """
        判断是否触发熔断(连续失败N次)
        
        熔断机制防止系统持续向故障服务发送请求，
        减少资源浪费和错误日志噪音。
        
        Args:
            module_name: 模块名称
            threshold: 失败阈值，默认5次
        
        Returns:
            bool: True表示应触发熔断,暂停该模块请求
        
        Examples:
            >>> fallback = FallbackManager()
            >>> for _ in range(5):
            ...     fallback.record_failure('api_call')
            >>> fallback.should_circuit_break('api_call')
            True
        """
        failure_count = self.failure_counts.get(module_name, 0)
        is_broken = failure_count >= threshold
        
        if is_broken and not self.circuit_breakers.get(module_name, False):
            self.circuit_breakers[module_name] = True
            self.logger.error(f"[BREAKER TRIGGERED] 模块 {module_name} (失败{failure_count}次)")
        
        return is_broken
    
    def reset_failure_count(self, module_name: str):
        """
        重置失败计数(成功后调用)
        
        当模块恢复正常后，清除其失败记录和熔断状态。
        
        Args:
            module_name: 模块名称
        
        Examples:
            >>> fallback = FallbackManager()
            >>> fallback.reset_failure_count('fetch_dix')
        """
        if module_name in self.failure_counts:
            old_count = self.failure_counts[module_name]
            self.failure_counts[module_name] = 0
            
            # 清除熔断状态
            if self.circuit_breakers.get(module_name, False):
                self.circuit_breakers[module_name] = False
                self.logger.info(f"[RECOVERED] 模块 {module_name} 熔断已解除 (之前失败{old_count}次)")
            else:
                self.logger.info(f"模块 {module_name} 失败计数已重置 (之前{old_count}次)")
    
    def get_module_status(self, module_name: str) -> dict:
        """
        获取模块当前状态
        
        Args:
            module_name: 模块名称
        
        Returns:
            dict: {
                'failure_count': int,
                'is_circuit_broken': bool,
                'status': str  # 'HEALTHY', 'DEGRADED', 'BROKEN'
            }
        """
        failure_count = self.failure_counts.get(module_name, 0)
        is_broken = self.circuit_breakers.get(module_name, False)
        
        if is_broken:
            status = 'BROKEN'
        elif failure_count > 0:
            status = 'DEGRADED'
        else:
            status = 'HEALTHY'
        
        return {
            'failure_count': failure_count,
            'is_circuit_broken': is_broken,
            'status': status
        }
    
    def clear_all_failures(self):
        """清除所有模块的失败记录"""
        self.failure_counts.clear()
        self.circuit_breakers.clear()
        self.logger.info("所有模块失败记录已清除")


# ==================== 装饰器 ====================

def handle_fetch_errors(max_retries: int = 3):
    """
    数据获取错误处理装饰器
    
    提供自动重试和失败记录功能：
    - 指数退避重试（5s → 10s → 20s → 40s）
    - 失败时自动记录到FallbackManager
    - 触发熔断时返回None而非抛出异常
    
    Args:
        max_retries: 最大重试次数，默认3次
    
    Usage:
        @handle_fetch_errors(max_retries=3)
        async def fetch_spy_price():
            response = await session.get(url)
            return response.json()
    
    Examples:
        >>> @handle_fetch_errors(max_retries=2)
        ... async def test_fetch():
        ...     raise ConnectionError("Network error")
        ...
        >>> result = await test_fetch()
        >>> print(result)  # None (熔断后)
    """
    def decorator(func):
        @wraps(func)
        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=5, max=45),
            reraise=False  # 不重新抛出异常，返回None
        )
        async def wrapper(*args, **kwargs):
            fallback_mgr = None
            try:
                result = await func(*args, **kwargs)
                
                # 成功后重置失败计数
                try:
                    fallback_mgr = FallbackManager()
                    fallback_mgr.reset_failure_count(func.__name__)
                except Exception as e:
                    logger.debug(f"重置失败计数时出错: {e}")
                
                return result
                
            except Exception as e:
                # 记录失败
                try:
                    fallback_mgr = FallbackManager()
                    fallback_mgr.record_failure(func.__name__)
                    
                    # 检查是否熔断
                    if fallback_mgr.should_circuit_break(func.__name__):
                        logger.error(f"模块 {func.__name__} 触发熔断,返回None")
                        return None
                        
                except Exception as log_err:
                    logger.error(f"记录失败时出错: {log_err}")
                
                # 重试耗尽后返回None
                logger.error(f"模块 {func.__name__} 重试耗尽: {e}")
                return None
                
        return wrapper
    return decorator


def sync_handle_fetch_errors(max_retries: int = 3):
    """
    同步版本的数据获取错误处理装饰器
    
    用于非异步函数的错误处理。
    
    Args:
        max_retries: 最大重试次数
    
    Usage:
        @sync_handle_fetch_errors(max_retries=3)
        def fetch_local_data():
            with open('data.csv') as f:
                return f.read()
    """
    def decorator(func):
        @wraps(func)
        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=5, max=45),
            reraise=False
        )
        def wrapper(*args, **kwargs):
            fallback_mgr = None
            try:
                result = func(*args, **kwargs)
                
                # 成功后重置失败计数
                try:
                    fallback_mgr = FallbackManager()
                    fallback_mgr.reset_failure_count(func.__name__)
                except Exception as e:
                    logger.debug(f"重置失败计数时出错: {e}")
                
                return result
                
            except Exception as e:
                # 记录失败
                try:
                    fallback_mgr = FallbackManager()
                    fallback_mgr.record_failure(func.__name__)
                    
                    # 检查是否熔断
                    if fallback_mgr.should_circuit_break(func.__name__):
                        logger.error(f"模块 {func.__name__} 触发熔断,返回None")
                        return None
                        
                except Exception as log_err:
                    logger.error(f"记录失败时出错: {log_err}")
                
                # 重试耗尽后返回None
                logger.error(f"模块 {func.__name__} 重试耗尽: {e}")
                return None
                
        return wrapper
    return decorator


# ==================== 便捷函数 ====================

def create_fallback_manager() -> FallbackManager:
    """创建并返回FallbackManager实例"""
    return FallbackManager()


if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    async def test_fallback():
        print("=" * 60)
        print("测试 FallbackManager")
        print("=" * 60)
        
        fallback = FallbackManager()
        
        # 测试1: 暗盘降级逻辑
        print("\n【测试1】暗盘降级逻辑")
        result = fallback.handle_darkpool_fallback(True, True, True)
        print(f"FULL模式: {result}")
        
        result = fallback.handle_darkpool_fallback(True, False, True)
        print(f"PARTIAL模式: {result}")
        
        result = fallback.handle_darkpool_fallback(False, False, False)
        print(f"DEGRADED模式: {result}")
        
        # 测试2: 失败计数与熔断
        print("\n【测试2】失败计数与熔断")
        for i in range(6):
            fallback.record_failure('test_module')
            status = fallback.get_module_status('test_module')
            print(f"第{i+1}次失败: {status}")
        
        # 测试3: 重置失败计数
        print("\n【测试3】重置失败计数")
        fallback.reset_failure_count('test_module')
        status = fallback.get_module_status('test_module')
        print(f"重置后状态: {status}")
        
        print("\n✅ 所有测试完成")
    
    asyncio.run(test_fallback())
