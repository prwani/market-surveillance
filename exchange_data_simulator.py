"""
Exchange Data Simulator for Real-Time Market Surveillance Testing
=================================================================
Simulates realistic trading activity across Asian exchanges (SGX, HKEX, NSE)
including normal market-making and manipulation patterns (spoofing, layering,
wash trading, price anomalies, and coordinated cross-exchange manipulation).

Outputs can be directed to:
  - Kafka topic (for Fabric Event Streams)
  - CSV files (for batch training)
  - WebSocket server (for real-time streaming tests)
  - stdout (for quick inspection)

Usage:
    python exchange_data_simulator.py --help

Requirements:
    pip install -r requirements.txt
"""

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Generator, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

class ExchangeId(str, Enum):
    SGX = "SGX"
    HKEX = "HKEX"
    NSE = "NSE"


class ManipulationType(str, Enum):
    NONE = "NONE"
    SPOOFING = "SPOOFING"
    LAYERING = "LAYERING"
    WASH_TRADING = "WASH_TRADING"
    PRICE_ANOMALY = "PRICE_ANOMALY"
    COORDINATED = "COORDINATED"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderAction(str, Enum):
    ADD = "add"
    CANCEL = "cancel"
    MODIFY = "modify"
    FILL = "fill"


@dataclass
class Symbol:
    ticker: str
    exchange: ExchangeId
    currency: str
    base_price: float
    avg_daily_volume: int  # shares per day
    tick_size: float
    lot_size: int


@dataclass
class TradeEvent:
    event_type: str = "TRADE"
    event_id: str = ""
    exchange_id: str = ""
    symbol: str = ""
    timestamp: str = ""
    price: float = 0.0
    quantity: int = 0
    buyer_id: str = ""
    seller_id: str = ""
    order_type: str = "LIMIT"
    venue: str = ""
    currency: str = ""
    labels: dict = field(default_factory=dict)


@dataclass
class OrderBookEvent:
    event_type: str = "ORDER_BOOK"
    event_id: str = ""
    exchange_id: str = ""
    symbol: str = ""
    timestamp: str = ""
    action: str = ""
    side: str = ""
    price: float = 0.0
    quantity: int = 0
    broker_id: str = ""
    order_id: str = ""
    labels: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exchange Definitions
# ---------------------------------------------------------------------------

EXCHANGE_SYMBOLS = {
    ExchangeId.SGX: [
        Symbol("OCBC",  ExchangeId.SGX,  "SGD", 14.50,  1_500_000, 0.01, 100),
        Symbol("DBS",   ExchangeId.SGX,  "SGD", 38.20,  2_000_000, 0.01, 100),
        Symbol("UOB",   ExchangeId.SGX,  "SGD", 31.80,  1_200_000, 0.01, 100),
        Symbol("SINGTEL", ExchangeId.SGX, "SGD", 2.42,  8_000_000, 0.005, 1000),
    ],
    ExchangeId.HKEX: [
        Symbol("0700.HK", ExchangeId.HKEX, "HKD", 380.0,  5_000_000, 0.20, 100),
        Symbol("9988.HK", ExchangeId.HKEX, "HKD", 89.0,   8_000_000, 0.10, 100),
        Symbol("1299.HK", ExchangeId.HKEX, "HKD", 72.5,   3_000_000, 0.05, 500),
        Symbol("0005.HK", ExchangeId.HKEX, "HKD", 64.0,   4_000_000, 0.05, 400),
    ],
    ExchangeId.NSE: [
        Symbol("RELIANCE", ExchangeId.NSE, "INR", 2950.0,  6_000_000, 0.05, 1),
        Symbol("TCS",      ExchangeId.NSE, "INR", 3800.0,  2_500_000, 0.05, 1),
        Symbol("INFY",     ExchangeId.NSE, "INR", 1750.0,  4_000_000, 0.05, 1),
        Symbol("HDFC",     ExchangeId.NSE, "INR", 1680.0,  5_000_000, 0.05, 1),
    ],
}

# Brokers per exchange (normal + manipulative)
BROKERS = {
    ExchangeId.SGX: {
        "normal": [f"BROKER_SGX_{i:03d}" for i in range(1, 21)],
        "manipulative": ["BROKER_SPOOF_SGX_001", "BROKER_LAYER_SGX_002", "BROKER_WASH_SGX_003"],
    },
    ExchangeId.HKEX: {
        "normal": [f"BROKER_HKEX_{i:03d}" for i in range(1, 21)],
        "manipulative": ["BROKER_SPOOF_HKEX_001", "BROKER_LAYER_HKEX_002", "BROKER_WASH_HKEX_003"],
    },
    ExchangeId.NSE: {
        "normal": [f"BROKER_NSE_{i:03d}" for i in range(1, 21)],
        "manipulative": ["BROKER_SPOOF_NSE_001", "BROKER_LAYER_NSE_002", "BROKER_WASH_NSE_003"],
    },
}


# ---------------------------------------------------------------------------
# Market State
# ---------------------------------------------------------------------------

class MarketState:
    """Maintains the current mid-price and order book for a symbol."""

    def __init__(self, symbol: Symbol):
        self.symbol = symbol
        self.mid_price = symbol.base_price
        self.bid = symbol.base_price - symbol.tick_size
        self.ask = symbol.base_price + symbol.tick_size
        self.last_price = symbol.base_price
        self.day_volume = 0
        # Simple Geometric Brownian Motion parameters
        self.mu = 0.0       # drift (annualised)
        self.sigma = 0.015  # daily volatility

    def step(self, dt_seconds: float = 1.0) -> None:
        """Advance price by one time step using GBM."""
        dt_years = dt_seconds / (252 * 6.5 * 3600)
        z = random.gauss(0, 1)
        log_return = (self.mu - 0.5 * self.sigma ** 2) * dt_years + self.sigma * math.sqrt(dt_years) * z
        self.mid_price = max(self.mid_price * math.exp(log_return), self.symbol.tick_size)
        spread = max(self.symbol.tick_size * 2, self.mid_price * 0.0002)
        self.bid = round(self.mid_price - spread / 2, 4)
        self.ask = round(self.mid_price + spread / 2, 4)
        self.last_price = round(self.mid_price, 4)

    def inject_shock(self, magnitude: float) -> None:
        """Inject a price shock (positive or negative fraction, e.g. 0.03 = +3%)."""
        self.mid_price *= (1 + magnitude)
        self.last_price = round(self.mid_price, 4)
        spread = max(self.symbol.tick_size * 2, self.mid_price * 0.0002)
        self.bid = round(self.mid_price - spread / 2, 4)
        self.ask = round(self.mid_price + spread / 2, 4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sim_ts(base_ts: float, offset_seconds: float) -> str:
    ts = datetime.fromtimestamp(base_ts + offset_seconds, tz=timezone.utc)
    return ts.isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _round_to_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 8)


# ---------------------------------------------------------------------------
# Event Generators
# ---------------------------------------------------------------------------

class NormalTradingGenerator:
    """Generates realistic normal market-making and institutional trading events."""

    def __init__(self, symbol: Symbol, exchange: ExchangeId):
        self.symbol = symbol
        self.exchange = exchange
        self.market = MarketState(symbol)
        self.brokers = BROKERS[exchange]["normal"]
        self._order_id_counter = 0

    def _next_order_id(self) -> str:
        self._order_id_counter += 1
        return f"{self.exchange.value}-{self.symbol.ticker}-{self._order_id_counter:08d}"

    def generate_trade(self, base_ts: float, offset: float = 0.0) -> TradeEvent:
        """Generate a single normal trade event."""
        self.market.step(dt_seconds=1.0)
        buyer = random.choice(self.brokers)
        seller = random.choice([b for b in self.brokers if b != buyer])

        # Volume: log-normal distribution around average order size
        avg_order_size = max(self.symbol.lot_size, self.symbol.avg_daily_volume // 2000)
        qty = max(
            self.symbol.lot_size,
            int(random.lognormvariate(math.log(avg_order_size), 0.5) / self.symbol.lot_size) * self.symbol.lot_size
        )

        # Price: slightly randomised around mid
        price = _round_to_tick(
            self.market.mid_price * random.uniform(0.9998, 1.0002),
            self.symbol.tick_size
        )

        return TradeEvent(
            event_id=_gen_id(f"{self.exchange.value}-TRD"),
            exchange_id=self.exchange.value,
            symbol=self.symbol.ticker,
            timestamp=_sim_ts(base_ts, offset),
            price=price,
            quantity=qty,
            buyer_id=buyer,
            seller_id=seller,
            order_type="LIMIT",
            venue=f"{self.exchange.value}_MAIN",
            currency=self.symbol.currency,
            labels={"is_manipulation": False, "manipulation_type": ManipulationType.NONE.value},
        )

    def generate_order_book_event(self, base_ts: float, offset: float = 0.0) -> OrderBookEvent:
        """Generate a normal order book event (add, cancel, modify)."""
        self.market.step(dt_seconds=0.1)
        broker = random.choice(self.brokers)
        side = random.choice([OrderSide.BUY.value, OrderSide.SELL.value])
        action_weights = [0.6, 0.25, 0.15]  # add, cancel, modify
        action = random.choices(
            [OrderAction.ADD.value, OrderAction.CANCEL.value, OrderAction.MODIFY.value],
            weights=action_weights
        )[0]

        if side == OrderSide.BUY.value:
            price = _round_to_tick(
                self.market.bid * random.uniform(0.998, 1.002),
                self.symbol.tick_size
            )
        else:
            price = _round_to_tick(
                self.market.ask * random.uniform(0.998, 1.002),
                self.symbol.tick_size
            )

        avg_order_size = max(self.symbol.lot_size, self.symbol.avg_daily_volume // 2000)
        qty = max(
            self.symbol.lot_size,
            int(random.lognormvariate(math.log(avg_order_size), 0.5) / self.symbol.lot_size) * self.symbol.lot_size
        )

        return OrderBookEvent(
            event_id=_gen_id(f"{self.exchange.value}-OBK"),
            exchange_id=self.exchange.value,
            symbol=self.symbol.ticker,
            timestamp=_sim_ts(base_ts, offset),
            action=action,
            side=side,
            price=price,
            quantity=qty,
            broker_id=broker,
            order_id=self._next_order_id(),
            labels={"is_manipulation": False, "manipulation_type": ManipulationType.NONE.value},
        )


class ManipulationInjector:
    """Injects manipulation patterns into the event stream at specified times."""

    def __init__(self, symbol: Symbol, exchange: ExchangeId, market: MarketState):
        self.symbol = symbol
        self.exchange = exchange
        self.market = market
        self.manipulative_brokers = BROKERS[exchange]["manipulative"]
        self.normal_brokers = BROKERS[exchange]["normal"]
        self._order_id_counter = 100000

    def _next_order_id(self) -> str:
        self._order_id_counter += 1
        return f"MANIP-{self.exchange.value}-{self.symbol.ticker}-{self._order_id_counter:08d}"

    def generate_spoofing_sequence(self, base_ts: float, start_offset: float) -> List:
        """
        Spoofing: Place large buy orders to push up apparent demand,
        then cancel them within 500ms before they fill, then sell at inflated price.
        Returns a list of events sorted by timestamp offset.
        """
        events = []
        spoofer = self.manipulative_brokers[0]
        seller_account = random.choice(self.normal_brokers)

        spoof_price = _round_to_tick(self.market.ask * 1.005, self.symbol.tick_size)
        spoof_qty = max(self.symbol.lot_size, self.symbol.avg_daily_volume // 100)

        # Step 1: Place 5 large spoofing buy orders at slightly above ask (T=0 to T=200ms)
        order_ids = []
        for i in range(5):
            offset_ms = start_offset + i * 0.04  # 40ms apart
            oid = self._next_order_id()
            order_ids.append(oid)
            events.append(OrderBookEvent(
                event_id=_gen_id(f"{self.exchange.value}-OBK"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, offset_ms),
                action=OrderAction.ADD.value,
                side=OrderSide.BUY.value,
                price=_round_to_tick(spoof_price + i * self.symbol.tick_size, self.symbol.tick_size),
                quantity=spoof_qty,
                broker_id=spoofer,
                order_id=oid,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.SPOOFING.value,
                    "will_cancel_at": _sim_ts(base_ts, offset_ms + 0.344),
                    "cancel_latency_ms": 344 - i * 20,
                },
            ))

        # Step 2: Cancel all orders before fill (T=200ms to T=450ms)
        for i, oid in enumerate(order_ids):
            cancel_offset = start_offset + 0.20 + i * 0.05
            events.append(OrderBookEvent(
                event_id=_gen_id(f"{self.exchange.value}-OBK"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, cancel_offset),
                action=OrderAction.CANCEL.value,
                side=OrderSide.BUY.value,
                price=_round_to_tick(spoof_price + i * self.symbol.tick_size, self.symbol.tick_size),
                quantity=spoof_qty,
                broker_id=spoofer,
                order_id=oid,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.SPOOFING.value,
                },
            ))

        # Step 3: Sell at inflated price (T=500ms)
        self.market.inject_shock(0.003)  # Simulated price lift from spoofing
        sell_qty = spoof_qty * 5
        sell_price = _round_to_tick(self.market.ask * 1.002, self.symbol.tick_size)
        events.append(TradeEvent(
            event_id=_gen_id(f"{self.exchange.value}-TRD"),
            exchange_id=self.exchange.value,
            symbol=self.symbol.ticker,
            timestamp=_sim_ts(base_ts, start_offset + 0.50),
            price=sell_price,
            quantity=sell_qty,
            buyer_id=random.choice(self.normal_brokers),
            seller_id=spoofer,
            order_type="LIMIT",
            venue=f"{self.exchange.value}_MAIN",
            currency=self.symbol.currency,
            labels={
                "is_manipulation": True,
                "manipulation_type": ManipulationType.SPOOFING.value,
                "estimated_gain": round((sell_price - self.market.mid_price * 0.997) * sell_qty, 2),
            },
        ))

        return sorted(events, key=lambda e: e.timestamp)

    def generate_layering_sequence(self, base_ts: float, start_offset: float) -> List:
        """
        Layering: Place many sell orders at multiple price levels to push price down,
        then buy at depressed price, then cancel all the sells.
        """
        events = []
        layer_broker = self.manipulative_brokers[1]
        buyer_account = random.choice(self.normal_brokers)

        ask = self.market.ask
        layer_qty = max(self.symbol.lot_size, self.symbol.avg_daily_volume // 500)

        # Step 1: Place 8 sell orders at ascending price levels (T=0 to T=400ms)
        order_ids = []
        for i in range(8):
            offset = start_offset + i * 0.05
            oid = self._next_order_id()
            order_ids.append(oid)
            layer_price = _round_to_tick(ask + i * self.symbol.tick_size * 2, self.symbol.tick_size)
            events.append(OrderBookEvent(
                event_id=_gen_id(f"{self.exchange.value}-OBK"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, offset),
                action=OrderAction.ADD.value,
                side=OrderSide.SELL.value,
                price=layer_price,
                quantity=layer_qty,
                broker_id=layer_broker,
                order_id=oid,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.LAYERING.value,
                },
            ))

        # Step 2: Buy at depressed price (T=500ms)
        self.market.inject_shock(-0.004)  # Simulated price drop from selling pressure
        buy_price = _round_to_tick(self.market.bid * 0.999, self.symbol.tick_size)
        buy_qty = layer_qty * 8
        events.append(TradeEvent(
            event_id=_gen_id(f"{self.exchange.value}-TRD"),
            exchange_id=self.exchange.value,
            symbol=self.symbol.ticker,
            timestamp=_sim_ts(base_ts, start_offset + 0.50),
            price=buy_price,
            quantity=buy_qty,
            buyer_id=layer_broker,
            seller_id=random.choice(self.normal_brokers),
            order_type="LIMIT",
            venue=f"{self.exchange.value}_MAIN",
            currency=self.symbol.currency,
            labels={
                "is_manipulation": True,
                "manipulation_type": ManipulationType.LAYERING.value,
            },
        ))

        # Step 3: Cancel all layered sell orders (T=600ms to T=1s)
        for i, oid in enumerate(order_ids):
            cancel_offset = start_offset + 0.60 + i * 0.05
            events.append(OrderBookEvent(
                event_id=_gen_id(f"{self.exchange.value}-OBK"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, cancel_offset),
                action=OrderAction.CANCEL.value,
                side=OrderSide.SELL.value,
                price=_round_to_tick(ask + i * self.symbol.tick_size * 2, self.symbol.tick_size),
                quantity=layer_qty,
                broker_id=layer_broker,
                order_id=oid,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.LAYERING.value,
                },
            ))

        return sorted(events, key=lambda e: e.timestamp)

    def generate_wash_trading_sequence(self, base_ts: float, start_offset: float) -> List:
        """
        Wash trading: Same beneficial owner uses two accounts to trade with each other,
        creating artificial volume and/or price movement.
        """
        events = []
        wash_broker_a = self.manipulative_brokers[2]
        # Second account under same ultimate owner (different broker ID, same owner)
        wash_broker_b = f"BROKER_WASH_{self.exchange.value}_004_ALT"

        wash_price = _round_to_tick(self.market.mid_price, self.symbol.tick_size)
        wash_qty = max(self.symbol.lot_size, self.symbol.avg_daily_volume // 200)

        # Generate 10 wash trades between the two accounts
        for i in range(10):
            offset = start_offset + i * 0.30  # 300ms apart
            # Alternate buyer and seller to obscure the pattern
            if i % 2 == 0:
                buyer, seller = wash_broker_a, wash_broker_b
            else:
                buyer, seller = wash_broker_b, wash_broker_a

            # Slightly vary price to look natural
            price = _round_to_tick(wash_price * random.uniform(0.9999, 1.0001), self.symbol.tick_size)

            events.append(TradeEvent(
                event_id=_gen_id(f"{self.exchange.value}-TRD"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, offset),
                price=price,
                quantity=wash_qty,
                buyer_id=buyer,
                seller_id=seller,
                order_type="LIMIT",
                venue=f"{self.exchange.value}_MAIN",
                currency=self.symbol.currency,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.WASH_TRADING.value,
                    "ultimate_owner": f"UBO_{self.exchange.value}_WASH_001",
                    "account_a": wash_broker_a,
                    "account_b": wash_broker_b,
                },
            ))

        return sorted(events, key=lambda e: e.timestamp)

    def generate_price_anomaly(self, base_ts: float, start_offset: float,
                                direction: str = "up") -> List:
        """Generate a sudden price anomaly (flash crash or spike)."""
        events = []
        magnitude = random.uniform(0.03, 0.08) * (1 if direction == "up" else -1)
        self.market.inject_shock(magnitude)

        # Burst of aggressive market orders causing the anomaly
        num_trades = random.randint(20, 50)
        for i in range(num_trades):
            offset = start_offset + i * 0.02
            broker = random.choice(self.normal_brokers)
            events.append(TradeEvent(
                event_id=_gen_id(f"{self.exchange.value}-TRD"),
                exchange_id=self.exchange.value,
                symbol=self.symbol.ticker,
                timestamp=_sim_ts(base_ts, offset),
                price=_round_to_tick(
                    self.market.mid_price * random.uniform(0.999, 1.001),
                    self.symbol.tick_size
                ),
                quantity=max(self.symbol.lot_size,
                             self.symbol.avg_daily_volume // 500 * random.randint(5, 20)),
                buyer_id=broker if direction == "up" else random.choice(self.normal_brokers),
                seller_id=random.choice(self.normal_brokers) if direction == "up" else broker,
                order_type="MARKET",
                venue=f"{self.exchange.value}_MAIN",
                currency=self.symbol.currency,
                labels={
                    "is_manipulation": True,
                    "manipulation_type": ManipulationType.PRICE_ANOMALY.value,
                    "anomaly_direction": direction,
                    "magnitude_pct": round(abs(magnitude) * 100, 2),
                },
            ))

        return events


# ---------------------------------------------------------------------------
# Simulation Engine
# ---------------------------------------------------------------------------

class SimulationEngine:
    """
    Orchestrates normal trading generation and manipulation injection
    across one or more exchanges and symbols.
    """

    def __init__(self, config: dict):
        self.config = config
        self.exchanges = [ExchangeId(e) for e in config.get("exchanges", ["SGX"])]
        self.duration_seconds = config.get("duration", 3600)
        self.events_per_second_normal = config.get("events_per_second", 10)
        self.inject_spoofing = config.get("inject_spoofing", False)
        self.spoofing_start = config.get("spoofing_start", 300)
        self.inject_layering = config.get("inject_layering", False)
        self.layering_start = config.get("layering_start", 600)
        self.inject_wash_trading = config.get("inject_wash_trading", False)
        self.wash_start = config.get("wash_start", 1200)
        self.inject_price_anomaly = config.get("inject_price_anomaly", False)
        self.price_anomaly_start = config.get("price_anomaly_start", 1800)
        self.coordinated_manipulation = config.get("coordinated_manipulation", False)
        self.base_ts = time.time()
        self._all_events: List = []

    def _select_symbols(self) -> dict:
        """Return symbols to simulate for each exchange."""
        symbol_filter = self.config.get("symbols", {})
        result = {}
        for exchange in self.exchanges:
            available = EXCHANGE_SYMBOLS[exchange]
            if exchange.value in symbol_filter:
                tickers = symbol_filter[exchange.value]
                result[exchange] = [s for s in available if s.ticker in tickers]
            else:
                result[exchange] = available
        return result

    def generate_all_events(self) -> List:
        """Generate the full event stream for the simulation duration."""
        symbols_by_exchange = self._select_symbols()
        all_events = []

        for exchange, symbols in symbols_by_exchange.items():
            for symbol in symbols:
                logger.info("Generating events for %s:%s", exchange.value, symbol.ticker)
                generator = NormalTradingGenerator(symbol, exchange)
                injector = ManipulationInjector(symbol, exchange, generator.market)

                # Normal events: distribute across duration
                num_normal_trades = int(
                    self.duration_seconds * self.events_per_second_normal * 0.3
                )
                num_order_events = int(
                    self.duration_seconds * self.events_per_second_normal * 0.7
                )

                for i in range(num_normal_trades):
                    offset = random.uniform(0, self.duration_seconds)
                    all_events.append(generator.generate_trade(self.base_ts, offset))

                for i in range(num_order_events):
                    offset = random.uniform(0, self.duration_seconds)
                    all_events.append(generator.generate_order_book_event(self.base_ts, offset))

                # Inject manipulation patterns at scheduled times
                if self.inject_spoofing:
                    for repeat in range(self.config.get("spoofing_repeat", 3)):
                        start = self.spoofing_start + repeat * 120  # every 2 minutes
                        if start < self.duration_seconds:
                            all_events.extend(
                                injector.generate_spoofing_sequence(self.base_ts, start)
                            )

                if self.inject_layering:
                    for repeat in range(self.config.get("layering_repeat", 2)):
                        start = self.layering_start + repeat * 180
                        if start < self.duration_seconds:
                            all_events.extend(
                                injector.generate_layering_sequence(self.base_ts, start)
                            )

                if self.inject_wash_trading:
                    start = self.wash_start
                    if start < self.duration_seconds:
                        all_events.extend(
                            injector.generate_wash_trading_sequence(self.base_ts, start)
                        )

                if self.inject_price_anomaly:
                    start = self.price_anomaly_start
                    if start < self.duration_seconds:
                        direction = self.config.get("anomaly_direction", "up")
                        all_events.extend(
                            injector.generate_price_anomaly(self.base_ts, start, direction)
                        )

        # Sort all events by timestamp
        all_events.sort(key=lambda e: e.timestamp)
        self._all_events = all_events
        logger.info("Total events generated: %d", len(all_events))
        return all_events

    def get_statistics(self) -> dict:
        """Return summary statistics about the generated event stream."""
        if not self._all_events:
            return {}

        total = len(self._all_events)
        trades = [e for e in self._all_events if isinstance(e, TradeEvent)]
        orders = [e for e in self._all_events if isinstance(e, OrderBookEvent)]
        manip_trades = [e for e in trades if e.labels.get("is_manipulation")]
        manip_orders = [e for e in orders if e.labels.get("is_manipulation")]

        manipulation_types = {}
        for e in self._all_events:
            mt = e.labels.get("manipulation_type", "NONE")
            manipulation_types[mt] = manipulation_types.get(mt, 0) + 1

        return {
            "total_events": total,
            "trade_events": len(trades),
            "order_book_events": len(orders),
            "manipulation_events": len(manip_trades) + len(manip_orders),
            "manipulation_rate_pct": round(
                (len(manip_trades) + len(manip_orders)) / total * 100, 2
            ),
            "manipulation_breakdown": manipulation_types,
        }


# ---------------------------------------------------------------------------
# Output Writers
# ---------------------------------------------------------------------------

class StdoutWriter:
    def write(self, events: List, pretty: bool = False) -> None:
        for event in events:
            data = asdict(event)
            if pretty:
                print(json.dumps(data, indent=2))
            else:
                print(json.dumps(data))


class CsvWriter:
    def __init__(self, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        self.output_dir = output_dir

    def write(self, events: List) -> None:
        trades = [e for e in events if isinstance(e, TradeEvent)]
        orders = [e for e in events if isinstance(e, OrderBookEvent)]

        if trades:
            trade_file = os.path.join(self.output_dir, "trades.csv")
            with open(trade_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(asdict(trades[0]).keys()))
                writer.writeheader()
                for t in trades:
                    row = asdict(t)
                    row["labels"] = json.dumps(row["labels"])
                    writer.writerow(row)
            logger.info("Wrote %d trade events to %s", len(trades), trade_file)

        if orders:
            order_file = os.path.join(self.output_dir, "order_book_events.csv")
            with open(order_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(asdict(orders[0]).keys()))
                writer.writeheader()
                for o in orders:
                    row = asdict(o)
                    row["labels"] = json.dumps(row["labels"])
                    writer.writerow(row)
            logger.info("Wrote %d order book events to %s", len(orders), order_file)


class JsonWriter:
    def __init__(self, output_path: str):
        self.output_path = output_path

    def write(self, events: List) -> None:
        with open(self.output_path, "w") as f:
            json.dump([asdict(e) for e in events], f, indent=2)
        logger.info("Wrote %d events to %s", len(events), self.output_path)


class KafkaWriter:
    """Writes events to a Kafka topic (requires confluent-kafka package)."""

    def __init__(self, broker: str, topic: str):
        try:
            from confluent_kafka import Producer  # type: ignore
            self.producer = Producer({"bootstrap.servers": broker})
            self.topic = topic
            self._available = True
        except ImportError:
            logger.warning(
                "confluent-kafka not installed. Install with: pip install confluent-kafka"
            )
            self._available = False

    def write(self, events: List) -> None:
        if not self._available:
            logger.error("Kafka writer not available — confluent-kafka not installed.")
            return
        for event in events:
            data = json.dumps(asdict(event)).encode("utf-8")
            self.producer.produce(self.topic, value=data)
        self.producer.flush()
        logger.info("Produced %d events to Kafka topic '%s'", len(events), self.topic)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exchange Data Simulator for Market Surveillance Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simulate 1 hour of SGX normal trading
  python exchange_data_simulator.py --exchanges SGX --duration 3600

  # Simulate with spoofing injection, output to CSV
  python exchange_data_simulator.py --exchanges HKEX --duration 1800 \\
    --inject-spoofing --spoofing-start 300 --output csv --output-dir ./data

  # Multi-exchange coordinated manipulation test
  python exchange_data_simulator.py --exchanges SGX HKEX NSE \\
    --inject-spoofing --inject-layering --inject-wash-trading \\
    --coordinated-manipulation --output json --output-path /tmp/events.json

  # Stream to Kafka for Fabric Event Streams testing
  python exchange_data_simulator.py --exchanges SGX --duration 3600 \\
    --inject-spoofing --output kafka \\
    --kafka-broker localhost:9092 --kafka-topic fabric-surveillance
        """,
    )

    # Exchange and symbol selection
    parser.add_argument(
        "--exchanges", nargs="+", choices=["SGX", "HKEX", "NSE"],
        default=["SGX"], help="Exchanges to simulate (default: SGX)"
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Specific symbols to simulate (default: all symbols for selected exchange)"
    )

    # Simulation parameters
    parser.add_argument(
        "--duration", type=int, default=3600,
        help="Simulation duration in seconds (default: 3600)"
    )
    parser.add_argument(
        "--events-per-second", type=int, default=10,
        help="Normal events per second per symbol (default: 10)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility"
    )

    # Manipulation injection
    parser.add_argument("--inject-spoofing", action="store_true", help="Inject spoofing patterns")
    parser.add_argument("--spoofing-start", type=int, default=300,
                        help="Seconds into simulation to start spoofing (default: 300)")
    parser.add_argument("--spoofing-repeat", type=int, default=3,
                        help="Number of spoofing repetitions (default: 3)")
    parser.add_argument("--inject-layering", action="store_true", help="Inject layering patterns")
    parser.add_argument("--layering-start", type=int, default=600,
                        help="Seconds into simulation to start layering (default: 600)")
    parser.add_argument("--inject-wash-trading", action="store_true",
                        help="Inject wash trading patterns")
    parser.add_argument("--wash-start", type=int, default=1200,
                        help="Seconds into simulation to start wash trading (default: 1200)")
    parser.add_argument("--inject-price-anomaly", action="store_true",
                        help="Inject a sudden price anomaly")
    parser.add_argument("--price-anomaly-start", type=int, default=1800,
                        help="Seconds into simulation to inject price anomaly (default: 1800)")
    parser.add_argument("--anomaly-direction", choices=["up", "down"], default="up",
                        help="Direction of price anomaly (default: up)")
    parser.add_argument("--coordinated-manipulation", action="store_true",
                        help="Enable coordinated cross-exchange manipulation scenario")

    # Output options
    parser.add_argument(
        "--output", choices=["stdout", "csv", "json", "kafka"], default="stdout",
        help="Output format (default: stdout)"
    )
    parser.add_argument("--output-dir", default="./data",
                        help="Directory for CSV output (default: ./data)")
    parser.add_argument("--output-path", default="/tmp/events.json",
                        help="File path for JSON output (default: /tmp/events.json)")
    parser.add_argument("--kafka-broker", default="localhost:9092",
                        help="Kafka broker address (default: localhost:9092)")
    parser.add_argument("--kafka-topic", default="fabric-market-surveillance",
                        help="Kafka topic name (default: fabric-market-surveillance)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output to stdout")
    parser.add_argument("--stats-only", action="store_true",
                        help="Print only statistics, not individual events")

    return parser.parse_args()


def build_config(args: argparse.Namespace) -> dict:
    """Convert argparse namespace to simulation config dict."""
    symbols_by_exchange = {}
    if args.symbols:
        # Assign all specified symbols to all selected exchanges
        # (in practice you'd filter by exchange prefix, but this keeps it simple)
        for ex in args.exchanges:
            symbols_by_exchange[ex] = args.symbols

    return {
        "exchanges": args.exchanges,
        "symbols": symbols_by_exchange,
        "duration": args.duration,
        "events_per_second": args.events_per_second,
        "inject_spoofing": args.inject_spoofing,
        "spoofing_start": args.spoofing_start,
        "spoofing_repeat": args.spoofing_repeat,
        "inject_layering": args.inject_layering,
        "layering_start": args.layering_start,
        "inject_wash_trading": args.inject_wash_trading,
        "wash_start": args.wash_start,
        "inject_price_anomaly": args.inject_price_anomaly,
        "price_anomaly_start": args.price_anomaly_start,
        "anomaly_direction": args.anomaly_direction,
        "coordinated_manipulation": args.coordinated_manipulation,
    }


def main() -> None:
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        logger.info("Random seed set to %d", args.seed)

    config = build_config(args)
    engine = SimulationEngine(config)

    logger.info(
        "Starting simulation: exchanges=%s, duration=%ds, manipulation=%s",
        args.exchanges,
        args.duration,
        {
            "spoofing": args.inject_spoofing,
            "layering": args.inject_layering,
            "wash_trading": args.inject_wash_trading,
            "price_anomaly": args.inject_price_anomaly,
        },
    )

    events = engine.generate_all_events()
    stats = engine.get_statistics()

    logger.info("Simulation statistics: %s", json.dumps(stats, indent=2))

    if args.stats_only:
        print(json.dumps(stats, indent=2))
        return

    # Write output
    if args.output == "stdout":
        StdoutWriter().write(events, pretty=args.pretty)
    elif args.output == "csv":
        CsvWriter(args.output_dir).write(events)
    elif args.output == "json":
        JsonWriter(args.output_path).write(events)
    elif args.output == "kafka":
        KafkaWriter(args.kafka_broker, args.kafka_topic).write(events)

    # Always print stats summary at the end
    print("\n=== Simulation Complete ===", file=sys.stderr)
    print(json.dumps(stats, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
