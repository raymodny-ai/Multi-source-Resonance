"""端到端验证: Push 实时流架构"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_stream.event_bus import EventBus, Topics, get_event_bus, reset_event_bus

# ---- 测试1: EventBus pub/sub ----
print("=" * 50)
print("Test 1/4: EventBus pub/sub")

reset_event_bus()
bus = get_event_bus()
received = []

async def test_callback(data):
    received.append(data)

async def test1():
    await bus.start()
    await bus.subscribe(Topics.CRYPTO_FUNDING_RATE, test_callback)
    await bus.publish(Topics.CRYPTO_FUNDING_RATE, {"rate": 0.000125, "coin": "BTC"})
    await asyncio.sleep(0.3)
    assert len(received) == 1, f"Expected 1, got {len(received)}"
    assert received[0]["rate"] == 0.000125
    stats = bus.get_topic_stats()
    print(f"  Pub/Sub OK: 1 event received, rate={received[0]['rate']}")
    print(f"  Topics: {stats}")
    await bus.shutdown()
    print("  PASSED")

asyncio.run(test1())

# ---- 测试2: 多Topic并发 ----
print("=" * 50)
print("Test 2/4: Multi-topic dispatch")

reset_event_bus()
bus2 = get_event_bus()
results = {"funding": [], "oi": [], "gex": []}

async def on_funding(data):
    results["funding"].append(data)

async def on_oi(data):
    results["oi"].append(data)

async def on_gex(data):
    results["gex"].append(data)

async def test2():
    await bus2.start()
    await bus2.subscribe(Topics.CRYPTO_FUNDING_RATE, on_funding)
    await bus2.subscribe(Topics.CRYPTO_OPEN_INTEREST, on_oi)
    await bus2.subscribe(Topics.GEX_UPDATE, on_gex)

    await bus2.publish(Topics.CRYPTO_FUNDING_RATE, {"rate": 0.0001})
    await bus2.publish(Topics.CRYPTO_OPEN_INTEREST, {"oi": 2e9})
    await bus2.publish(Topics.GEX_UPDATE, {"gex": 1e9, "dix": 48.0})
    await asyncio.sleep(0.3)

    assert len(results["funding"]) == 1
    assert len(results["oi"]) == 1
    assert len(results["gex"]) == 1
    print(f"  funding={len(results['funding'])}, oi={len(results['oi'])}, gex={len(results['gex'])}")
    await bus2.shutdown()
    print("  PASSED")

asyncio.run(test2())

# ---- 测试3: 组件实例化 ----
print("=" * 50)
print("Test 3/4: Component instantiation")

reset_event_bus()

from data_stream.hyperliquid_stream import HyperliquidStream
from data_stream.signal_pipeline import SignalPipeline
from data_stream.rest_poll_scheduler import RESTPollScheduler
from data_stream.stream_engine import StreamEngine

bus3 = get_event_bus()
ws = HyperliquidStream(bus3, coin="BTC")
sp = SignalPipeline(bus3)
rp = RESTPollScheduler(bus3)

print(f"  HyperliquidStream: coin={ws._coin}, url={ws._ws_url}")
print(f"  SignalPipeline: eval_cooldown={sp.EVAL_COOLDOWN_SECONDS}s")
print(f"  RESTPollScheduler: running={rp.is_running}")

# 不实际连接, 仅验证初始化
assert ws._coin == "BTC"
assert ws._ws_url == "wss://api.hyperliquid.xyz/ws"
assert sp.EVAL_COOLDOWN_SECONDS == 30
assert not ws.is_connected
print("  PASSED")

# ---- 测试4: 配置验证 ----
print("=" * 50)
print("Test 4/4: StreamConfig")

from config.settings import StreamConfig
sc = StreamConfig()
print(f"  WS URL: {sc.HYPERLIQUID_WS_URL}")
print(f"  Reconnect: {sc.WS_RECONNECT_MIN_DELAY}s-{sc.WS_RECONNECT_MAX_DELAY}s")
print(f"  Ping: {sc.WS_PING_INTERVAL}s")
print(f"  REST Poll: {sc.REST_POLL_INTERVAL_INTRADAY}s intraday, {sc.REST_POLL_INTERVAL_CRYPTO}s crypto")
print(f"  Eval Cooldown: {sc.EVAL_COOLDOWN_SECONDS}s")
print("  PASSED")

print("=" * 50)
print("ALL 4 TESTS PASSED - Push 实时流架构验证完成")
print("=" * 50)
