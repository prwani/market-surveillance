"""
Tests for exchange_data_simulator.py

Validates that the simulation engine produces correctly-structured events,
injects the expected manipulation patterns, and emits accurate statistics.
"""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone

# Ensure the src/ directory is on the path regardless of
# how pytest is invoked (from the repo root or from the tests/ directory).
_PKG_ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
_SIM_ROOT = os.path.join(_PKG_ROOT, "simulator")
for _p in (_PKG_ROOT, _SIM_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from exchange_data_simulator import (
    ExchangeId,
    ManipulationType,
    ManipulationInjector,
    MarketState,
    NormalTradingGenerator,
    OrderBookEvent,
    SimulationEngine,
    Symbol,
    TradeEvent,
    CsvWriter,
    JsonWriter,
)


class TestSymbolAndMarketState(unittest.TestCase):
    """Unit tests for Symbol and MarketState models."""

    def _make_symbol(self) -> Symbol:
        return Symbol(
            ticker="OCBC",
            exchange=ExchangeId.SGX,
            currency="SGD",
            base_price=14.50,
            avg_daily_volume=1_500_000,
            tick_size=0.01,
            lot_size=100,
        )

    def test_market_state_initialises_from_symbol(self):
        sym = self._make_symbol()
        state = MarketState(sym)
        self.assertAlmostEqual(state.mid_price, sym.base_price)
        self.assertLess(state.bid, state.mid_price)
        self.assertGreater(state.ask, state.mid_price)

    def test_market_state_step_changes_price(self):
        import random
        random.seed(0)
        sym = self._make_symbol()
        state = MarketState(sym)
        original = state.mid_price
        for _ in range(100):
            state.step(dt_seconds=1.0)
        # Price should have changed (with overwhelming probability at seed 0)
        self.assertNotAlmostEqual(state.mid_price, original, places=4)

    def test_inject_shock_positive(self):
        sym = self._make_symbol()
        state = MarketState(sym)
        before = state.mid_price
        state.inject_shock(0.05)
        self.assertGreater(state.mid_price, before)

    def test_inject_shock_negative(self):
        sym = self._make_symbol()
        state = MarketState(sym)
        before = state.mid_price
        state.inject_shock(-0.05)
        self.assertLess(state.mid_price, before)


class TestNormalTradingGenerator(unittest.TestCase):
    """Tests for normal (non-manipulative) event generation."""

    def setUp(self):
        import random, time
        random.seed(42)
        self.symbol = Symbol(
            ticker="DBS",
            exchange=ExchangeId.SGX,
            currency="SGD",
            base_price=38.20,
            avg_daily_volume=2_000_000,
            tick_size=0.01,
            lot_size=100,
        )
        self.generator = NormalTradingGenerator(self.symbol, ExchangeId.SGX)
        self.base_ts = time.time()

    def test_generate_trade_returns_trade_event(self):
        trade = self.generator.generate_trade(self.base_ts)
        self.assertIsInstance(trade, TradeEvent)

    def test_trade_fields_are_populated(self):
        trade = self.generator.generate_trade(self.base_ts)
        self.assertEqual(trade.event_type, "TRADE")
        self.assertEqual(trade.exchange_id, "SGX")
        self.assertEqual(trade.symbol, "DBS")
        self.assertGreater(trade.price, 0)
        self.assertGreater(trade.quantity, 0)
        self.assertNotEqual(trade.buyer_id, "")
        self.assertNotEqual(trade.seller_id, "")

    def test_trade_is_not_labelled_manipulation(self):
        trade = self.generator.generate_trade(self.base_ts)
        self.assertFalse(trade.labels["is_manipulation"])
        self.assertEqual(trade.labels["manipulation_type"], ManipulationType.NONE.value)

    def test_generate_order_book_event_returns_order_book_event(self):
        ev = self.generator.generate_order_book_event(self.base_ts)
        self.assertIsInstance(ev, OrderBookEvent)
        self.assertEqual(ev.event_type, "ORDER_BOOK")

    def test_quantity_is_multiple_of_lot_size(self):
        for _ in range(20):
            trade = self.generator.generate_trade(self.base_ts)
            self.assertEqual(trade.quantity % self.symbol.lot_size, 0)


class TestManipulationInjector(unittest.TestCase):
    """Tests for manipulation pattern injection."""

    def setUp(self):
        import time
        self.symbol = Symbol(
            ticker="0700.HK",
            exchange=ExchangeId.HKEX,
            currency="HKD",
            base_price=380.0,
            avg_daily_volume=5_000_000,
            tick_size=0.20,
            lot_size=100,
        )
        self.market = MarketState(self.symbol)
        self.injector = ManipulationInjector(self.symbol, ExchangeId.HKEX, self.market)
        self.base_ts = time.time()

    def test_spoofing_sequence_structure(self):
        events = self.injector.generate_spoofing_sequence(self.base_ts, start_offset=0.0)
        self.assertTrue(len(events) > 0)
        # Should have both OrderBookEvent and TradeEvent
        types = {type(e) for e in events}
        self.assertIn(OrderBookEvent, types)
        self.assertIn(TradeEvent, types)

    def test_spoofing_events_are_labelled(self):
        events = self.injector.generate_spoofing_sequence(self.base_ts, start_offset=0.0)
        for ev in events:
            self.assertTrue(ev.labels["is_manipulation"])
            self.assertEqual(ev.labels["manipulation_type"], ManipulationType.SPOOFING.value)

    def test_spoofing_events_sorted_by_timestamp(self):
        events = self.injector.generate_spoofing_sequence(self.base_ts, start_offset=0.0)
        timestamps = [e.timestamp for e in events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_layering_sequence_structure(self):
        events = self.injector.generate_layering_sequence(self.base_ts, start_offset=0.0)
        self.assertTrue(len(events) > 0)
        for ev in events:
            self.assertEqual(ev.labels["manipulation_type"], ManipulationType.LAYERING.value)

    def test_wash_trading_sequence_all_trades(self):
        events = self.injector.generate_wash_trading_sequence(self.base_ts, start_offset=0.0)
        self.assertTrue(len(events) > 0)
        for ev in events:
            self.assertIsInstance(ev, TradeEvent)
            self.assertEqual(ev.labels["manipulation_type"], ManipulationType.WASH_TRADING.value)

    def test_price_anomaly_sequence(self):
        events = self.injector.generate_price_anomaly(self.base_ts, start_offset=0.0, direction="up")
        self.assertTrue(len(events) > 0)
        for ev in events:
            self.assertIsInstance(ev, TradeEvent)
            self.assertEqual(ev.labels["manipulation_type"], ManipulationType.PRICE_ANOMALY.value)


class TestSimulationEngine(unittest.TestCase):
    """Integration tests for SimulationEngine."""

    def _make_config(self, **overrides) -> dict:
        base = {
            "exchanges": ["SGX"],
            "duration": 60,           # short run for tests
            "events_per_second": 5,
            "inject_spoofing": False,
            "inject_layering": False,
            "inject_wash_trading": False,
            "inject_price_anomaly": False,
            "coordinated_manipulation": False,
        }
        base.update(overrides)
        return base

    def test_engine_generates_events(self):
        import random
        random.seed(1)
        engine = SimulationEngine(self._make_config())
        events = engine.generate_all_events()
        self.assertGreater(len(events), 0)

    def test_events_are_sorted_by_timestamp(self):
        import random
        random.seed(2)
        engine = SimulationEngine(self._make_config())
        events = engine.generate_all_events()
        timestamps = [e.timestamp for e in events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_statistics_fields(self):
        import random
        random.seed(3)
        engine = SimulationEngine(self._make_config())
        engine.generate_all_events()
        stats = engine.get_statistics()
        for key in ("total_events", "trade_events", "order_book_events",
                    "manipulation_events", "manipulation_rate_pct"):
            self.assertIn(key, stats)

    def test_manipulation_events_present_when_injection_enabled(self):
        import random
        random.seed(4)
        config = self._make_config(
            duration=400,
            inject_spoofing=True,
            spoofing_start=10,
            spoofing_repeat=1,
        )
        engine = SimulationEngine(config)
        engine.generate_all_events()
        stats = engine.get_statistics()
        self.assertGreater(stats["manipulation_events"], 0)

    def test_multi_exchange_generates_events_per_exchange(self):
        import random
        random.seed(5)
        config = self._make_config(exchanges=["SGX", "HKEX"], duration=30)
        engine = SimulationEngine(config)
        events = engine.generate_all_events()
        exchanges_seen = {e.exchange_id for e in events}
        self.assertIn("SGX", exchanges_seen)
        self.assertIn("HKEX", exchanges_seen)

    def test_empty_after_init_statistics(self):
        engine = SimulationEngine(self._make_config())
        # No events generated yet
        stats = engine.get_statistics()
        self.assertEqual(stats, {})


class TestOutputWriters(unittest.TestCase):
    """Tests for CsvWriter and JsonWriter."""

    def _sample_events(self):
        import time, random
        random.seed(10)
        sym = Symbol(
            ticker="RELIANCE",
            exchange=ExchangeId.NSE,
            currency="INR",
            base_price=2950.0,
            avg_daily_volume=6_000_000,
            tick_size=0.05,
            lot_size=1,
        )
        gen = NormalTradingGenerator(sym, ExchangeId.NSE)
        base_ts = time.time()
        events = []
        for i in range(5):
            events.append(gen.generate_trade(base_ts, offset=float(i)))
            events.append(gen.generate_order_book_event(base_ts, offset=float(i) + 0.5))
        return events

    def test_csv_writer_creates_files(self):
        events = self._sample_events()
        with tempfile.TemporaryDirectory() as tmpdir:
            CsvWriter(tmpdir).write(events)
            files = os.listdir(tmpdir)
            self.assertIn("trades.csv", files)
            self.assertIn("order_book_events.csv", files)

    def test_json_writer_creates_file(self):
        events = self._sample_events()
        with tempfile.TemporaryDirectory() as tmpdir:
            outpath = os.path.join(tmpdir, "events.json")
            JsonWriter(outpath).write(events)
            self.assertTrue(os.path.exists(outpath))
            with open(outpath) as f:
                data = json.load(f)
            self.assertEqual(len(data), len(events))


if __name__ == "__main__":
    unittest.main()
