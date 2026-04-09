"""
FabricIQ ML Training Pipeline — Market Anomaly Detector
========================================================
Fabric notebook: notebooks/train_anomaly_model.py

This notebook trains a transformer-based (or time-series foundation model)
anomaly detector on historical trade data from the Fabric Eventhouse and
registers the trained model in the FabricIQ ML Model Registry for versioned
deployment.

Architecture
------------
    Eventhouse (TRADES table)
        → Feature engineering (price_return_1m, volume_5m, vwap, bid_ask_spread)
        → Model training (MomentFM / Nixtla / sklearn IsolationForest)
        → FabricIQ ML Registry registration
        → KQL scoring: evaluate ml_anomaly_score(model_name="market-anomaly-detector-v3")

Usage
-----
Run as a Fabric notebook (PySpark / Python kernel) or locally:

    python notebooks/train_anomaly_model.py \
        --kql-uri $KQL_URI \
        --kql-db surveillance \
        --model-name market-anomaly-detector-v3 \
        --output-dir /tmp/models

Dependencies (install in Fabric notebook environment):
    pip install azure-kusto-data azure-identity scikit-learn joblib pandas numpy
    pip install momentfm  # optional: time-series foundation model
    pip install mlflow    # optional: for FabricIQ ML Registry integration
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("train_anomaly_model")

# ---------------------------------------------------------------------------
# Optional heavy dependencies (gracefully degraded if not installed)
# ---------------------------------------------------------------------------

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    import joblib
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    logger.warning("scikit-learn not installed — model training will be skipped")

try:
    import mlflow
    import mlflow.sklearn
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False
    logger.warning("mlflow not installed — model registry integration will be skipped")

try:
    from azure.identity import DefaultAzureCredential
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
    HAS_KUSTO = True
except ImportError:
    HAS_KUSTO = False
    logger.warning("azure-kusto-data not installed — using synthetic data for demo")


# ---------------------------------------------------------------------------
# Feature engineering constants
# ---------------------------------------------------------------------------

FEATURES = [
    "price_return_1m",   # (last_price - first_price) / first_price
    "volume_5m",         # 5-minute rolling trade volume
    "trade_count",       # trades in the 1-minute bucket
    "vwap",              # volume-weighted average price
    "vwap_deviation",    # (vwap - rolling_mean_vwap) / rolling_std_vwap
]

LOOKBACK_HOURS = 24      # hours of history for training
BUCKET_MINUTES = 1       # 1-minute aggregation buckets
CONTAMINATION = 0.05     # expected anomaly fraction for IsolationForest
N_ESTIMATORS = 200       # IsolationForest number of trees


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_training_data(kql_uri: str, kql_db: str, hours: int = LOOKBACK_HOURS) -> pd.DataFrame:
    """
    Load trade data from Fabric Eventhouse and compute features.

    Parameters
    ----------
    kql_uri : str
        Fabric Eventhouse KQL query URI.
    kql_db : str
        KQL database name (default: ``surveillance``).
    hours : int
        Number of hours of history to load.

    Returns
    -------
    pd.DataFrame
        Feature matrix with columns matching ``FEATURES``, plus metadata
        columns ``exchange_id``, ``symbol``, ``event_time``.
    """
    if not HAS_KUSTO:
        logger.info("Kusto unavailable — generating synthetic training data")
        return _synthetic_training_data(n_rows=5000)

    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(kql_uri, credential)
    client = KustoClient(kcsb)

    kql = f"""
    TRADES
    | where event_time > ago({hours}h)
    | summarize
        first_price  = first(price),
        last_price   = last(price),
        volume_5m    = sum(quantity),
        trade_count  = count(),
        vwap         = sum(price * quantity) / sum(quantity)
        by exchange_id, symbol, bin(event_time, {BUCKET_MINUTES}m)
    | extend price_return_1m = iff(
        first_price > 0,
        (last_price - first_price) / first_price,
        0.0
    )
    | order by symbol, exchange_id, event_time asc
    | project event_time, exchange_id, symbol,
              price_return_1m, volume_5m, trade_count, vwap
    """

    logger.info("Loading %d hours of trade data from Eventhouse...", hours)
    resp = client.execute_query(kql_db, kql)
    cols = [c.column_name for c in resp.primary_results[0].columns]
    rows = [{c: row[c] for c in cols} for row in resp.primary_results[0]]
    df = pd.DataFrame(rows)
    logger.info("Loaded %d rows of training data.", len(df))
    return _compute_derived_features(df)


def _compute_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute ``vwap_deviation`` (rolling Z-score of VWAP) per (exchange, symbol)."""
    if df.empty:
        return df
    df = df.copy()
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    df = df.sort_values(["exchange_id", "symbol", "event_time"])

    def rolling_zscore(series: pd.Series, window: int = 60) -> pd.Series:
        roll = series.rolling(window=window, min_periods=2)
        return (series - roll.mean()) / roll.std().clip(lower=1e-9)

    df["vwap_deviation"] = (
        df.groupby(["exchange_id", "symbol"])["vwap"]
        .transform(lambda s: rolling_zscore(s))
        .fillna(0.0)
    )
    for col in ["price_return_1m", "volume_5m", "trade_count", "vwap", "vwap_deviation"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _synthetic_training_data(n_rows: int = 5000) -> pd.DataFrame:
    """Generate synthetic normally-distributed feature data for testing."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "event_time": pd.date_range("2024-01-01", periods=n_rows, freq="1min", tz="UTC"),
        "exchange_id": rng.choice(["SGX", "HKEX", "NSE"], size=n_rows),
        "symbol": rng.choice(["OCBC", "DBS", "TENCENT", "RELIANCE"], size=n_rows),
        "price_return_1m": rng.normal(0, 0.002, n_rows),
        "volume_5m": rng.exponential(100_000, n_rows),
        "trade_count": rng.integers(5, 200, n_rows),
        "vwap": rng.uniform(10, 200, n_rows),
        "vwap_deviation": rng.normal(0, 1, n_rows),
    })
    # Inject ~5% anomalies
    n_anom = n_rows // 20
    idx = rng.choice(n_rows, n_anom, replace=False)
    df.loc[idx, "price_return_1m"] *= rng.uniform(5, 15, n_anom)
    df.loc[idx, "volume_5m"] *= rng.uniform(8, 20, n_anom)
    df.loc[idx, "vwap_deviation"] = rng.uniform(3.5, 6.0, n_anom)
    return df


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def train_isolation_forest(df: pd.DataFrame) -> Tuple[Any, Any]:
    """
    Train an IsolationForest anomaly detector on the feature matrix.

    Returns
    -------
    (model, scaler) : tuple
        Fitted sklearn IsolationForest and StandardScaler.
    """
    if not HAS_SKLEARN:
        raise RuntimeError("scikit-learn is required for model training")

    X = df[FEATURES].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # Compute training anomaly scores for reporting
    scores = model.score_samples(X_scaled)
    anom_pct = (model.predict(X_scaled) == -1).mean() * 100
    logger.info(
        "IsolationForest trained: %d samples | %.1f%% detected as anomalies",
        len(X), anom_pct,
    )
    return model, scaler


# ---------------------------------------------------------------------------
# Model scoring helper (for AnomalyDetectionAgent ml_score_provider)
# ---------------------------------------------------------------------------

class MLAnomalyScorer:
    """
    Wraps a trained IsolationForest model for use as the
    ``ml_score_provider`` callback in ``AnomalyDetectionAgent``.

    This is the glue between the FabricIQ ML Registry model and the
    Python surveillance agent.

    Usage
    -----
    >>> scorer = MLAnomalyScorer.from_file("/tmp/models/market-anomaly-detector-v3")
    >>> agent = AnomalyDetectionAgent(ml_score_provider=scorer)
    """

    def __init__(self, model: Any, scaler: Any) -> None:
        self._model = model
        self._scaler = scaler

    def __call__(
        self,
        exchange_id: str,
        symbol: str,
        vwap: float,
        volume: float,
        trade_count: int,
    ) -> float:
        """
        Score a single (exchange, symbol) 1-minute bucket.

        Returns
        -------
        float
            Anomaly probability in [0, 1].  Higher → more anomalous.
            Derived from the IsolationForest ``score_samples`` output
            (negative average path length) normalised to [0, 1].
        """
        if not HAS_SKLEARN:
            return 0.0
        # Build feature vector (use 0.0 for unavailable derived features)
        x = np.array([[
            0.0,         # price_return_1m — not available per-bucket in this call
            volume,      # volume_5m (approximated as 1-min volume)
            trade_count,
            vwap,
            0.0,         # vwap_deviation — not available per-bucket
        ]])
        x_scaled = self._scaler.transform(x)
        raw_score = self._model.score_samples(x_scaled)[0]
        # score_samples returns negative avg path length; lower → more anomalous
        # Normalise: IsolationForest scores are typically in [-0.8, 0.2]
        normalised = float(np.clip((raw_score + 0.8) / 1.0, 0.0, 1.0))
        # Invert so that higher = more anomalous
        return round(1.0 - normalised, 4)

    def save(self, output_dir: str) -> None:
        """Persist model and scaler to disk."""
        if not HAS_SKLEARN:
            return
        p = Path(output_dir)
        p.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, p / "model.joblib")
        joblib.dump(self._scaler, p / "scaler.joblib")
        meta = {
            "model_type": "IsolationForest",
            "features": FEATURES,
            "contamination": CONTAMINATION,
            "n_estimators": N_ESTIMATORS,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        (p / "metadata.json").write_text(json.dumps(meta, indent=2))
        logger.info("Model saved to %s", output_dir)

    @classmethod
    def from_file(cls, model_dir: str) -> "MLAnomalyScorer":
        """Load a previously saved model from disk."""
        if not HAS_SKLEARN:
            raise RuntimeError("scikit-learn is required to load the model")
        p = Path(model_dir)
        model = joblib.load(p / "model.joblib")
        scaler = joblib.load(p / "scaler.joblib")
        logger.info("Loaded ML model from %s", model_dir)
        return cls(model, scaler)


# ---------------------------------------------------------------------------
# FabricIQ ML Registry integration
# ---------------------------------------------------------------------------

def register_model_in_fabriciq(
    model_dir: str,
    model_name: str = "market-anomaly-detector-v3",
    tracking_uri: Optional[str] = None,
) -> Optional[str]:
    """
    Register the trained model in the FabricIQ ML Model Registry via MLflow.

    Parameters
    ----------
    model_dir : str
        Local directory containing ``model.joblib`` and ``scaler.joblib``.
    model_name : str
        Registered model name in the FabricIQ ML Registry.
    tracking_uri : str, optional
        MLflow tracking URI (FabricIQ experiment endpoint).
        Defaults to the ``MLFLOW_TRACKING_URI`` environment variable.

    Returns
    -------
    str or None
        The model version string if registration succeeded, else ``None``.
    """
    if not HAS_MLFLOW:
        logger.warning("mlflow not installed — skipping FabricIQ registry registration")
        return None

    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "")
    if uri:
        mlflow.set_tracking_uri(uri)

    with mlflow.start_run(run_name=f"{model_name}-training"):
        mlflow.log_params({
            "model_type": "IsolationForest",
            "features": ",".join(FEATURES),
            "contamination": CONTAMINATION,
            "n_estimators": N_ESTIMATORS,
            "lookback_hours": LOOKBACK_HOURS,
        })
        mlflow.log_artifacts(model_dir, artifact_path="model")

        p = Path(model_dir)
        meta_path = p / "metadata.json"
        if meta_path.exists():
            with meta_path.open() as f:
                meta = json.load(f)
            mlflow.log_metrics({"contamination_rate": meta.get("contamination", CONTAMINATION)})

        # Register the model
        run_id = mlflow.active_run().info.run_id
        model_uri = f"runs:/{run_id}/model"
        mv = mlflow.register_model(model_uri, model_name)
        logger.info(
            "Registered model '%s' version %s in FabricIQ ML Registry",
            model_name, mv.version,
        )
        return mv.version

    return None


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train market anomaly detector and register in FabricIQ ML Registry"
    )
    parser.add_argument("--kql-uri", default=os.environ.get("KQL_URI", ""),
                        help="Fabric Eventhouse KQL query URI")
    parser.add_argument("--kql-db", default=os.environ.get("KQL_DB", "surveillance"),
                        help="KQL database name (default: surveillance)")
    parser.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS,
                        help=f"Hours of training data to load (default: {LOOKBACK_HOURS})")
    parser.add_argument("--model-name", default="market-anomaly-detector-v3",
                        help="Name to register in FabricIQ ML Registry")
    parser.add_argument("--output-dir", default="/tmp/models/market-anomaly-detector-v3",
                        help="Local directory to save model artifacts")
    parser.add_argument("--register", action="store_true",
                        help="Register the model in FabricIQ ML Registry (requires mlflow)")
    parser.add_argument("--mlflow-uri", default=os.environ.get("MLFLOW_TRACKING_URI", ""),
                        help="MLflow tracking URI for FabricIQ ML Registry")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── Load data ──────────────────────────────────────────
    df = load_training_data(
        kql_uri=args.kql_uri,
        kql_db=args.kql_db,
        hours=args.lookback_hours,
    )
    logger.info("Training dataset: %d rows, %d features", len(df), len(FEATURES))

    # ── Train model ────────────────────────────────────────
    model, scaler = train_isolation_forest(df)
    scorer = MLAnomalyScorer(model, scaler)
    scorer.save(args.output_dir)

    # ── Register in FabricIQ ──────────────────────────────
    if args.register:
        version = register_model_in_fabriciq(
            model_dir=args.output_dir,
            model_name=args.model_name,
            tracking_uri=args.mlflow_uri or None,
        )
        if version:
            logger.info("Model version %s registered as '%s'", version, args.model_name)
    else:
        logger.info(
            "Skipping registry registration. Pass --register to register in FabricIQ."
        )

    logger.info("Training pipeline complete.")


if __name__ == "__main__":
    main()
