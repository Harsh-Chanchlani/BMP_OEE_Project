"""
ARIMA OEE Forecaster
=====================
Runs as a separate background process (not part of Spark).
Every N minutes it:
  1. Pulls the last 200 raw OEE readings per machine from oee_raw_events.
  2. Fits an ARIMA model using pmdarima.auto_arima (auto-selects p, d, q).
  3. Forecasts the next FORECAST_STEPS windows ahead.
  4. Writes predictions to the oee_predictions table.

Why ARIMA works for OEE:
  - OEE is a time series with autocorrelation (a loss event at t=0 affects t=1, t=2 …)
  - ARIMA captures both trend (d parameter) and short-range autocorrelation (p, q)
  - auto_arima selects the best order by minimising AIC so you don't need to tune manually

Requirements:
  pip install pmdarima

Run:
  python backend/arima_forecaster.py

Or add to scripts/start_mac.sh as a background process.
"""

import os
import time
from datetime import datetime, timedelta, timezone

def _utcnow():
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)

import psycopg2
import psycopg2.extras

# Fail loudly at import time — not silently inside a function
try:
    import pmdarima as pm
    import numpy as np
except ImportError:
    raise ImportError(
        "\n\n[arima_forecaster] pmdarima is not installed.\n"
        "Run:  pip install pmdarima\n"
        "Then restart the forecaster.\n"
    )

# ── config ────────────────────────────────────────────────────────────────────

def _load_env(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Use DATABASE_URL (Neon) if set, otherwise fall back to local PG env vars
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
DB_CONF = _DATABASE_URL if _DATABASE_URL else dict(
    dbname   = os.getenv("PGDATABASE", "oee_db"),
    user     = os.getenv("PGUSER",     "harshchanchlani"),
    password = os.getenv("PGPASSWORD", ""),
    host     = os.getenv("PGHOST",     "localhost"),
    port     = os.getenv("PGPORT",     "5432"),
)

# How many raw readings to use for fitting (more = better fit, slower)
HISTORY_POINTS = int(os.getenv("ARIMA_HISTORY_POINTS", "200"))

# How many future windows to forecast (each window ≈ 0.5 s of producer time)
FORECAST_STEPS = int(os.getenv("ARIMA_FORECAST_STEPS", "10"))

# How often to re-fit and write new forecasts (seconds)
RUN_INTERVAL_SECONDS = int(os.getenv("ARIMA_RUN_INTERVAL_SECONDS", "60"))


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_machines(conn) -> list[str]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT machine_id FROM oee_raw_events ORDER BY machine_id;")
    return [r[0] for r in cur.fetchall()]


def _get_history(conn, machine_id: str) -> list[tuple]:
    """
    Return the last HISTORY_POINTS (event_time, oee) pairs for a machine,
    ordered oldest → newest so ARIMA sees the series in chronological order.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT event_time, oee
        FROM (
            SELECT event_time, oee
            FROM oee_raw_events
            WHERE machine_id = %s
            ORDER BY event_time DESC
            LIMIT %s
        ) sub
        ORDER BY event_time ASC;
    """, (machine_id, HISTORY_POINTS))
    return cur.fetchall()


def _write_predictions(conn, machine_id: str, prediction_time: datetime,
                       forecasts: list[float], conf_lower: list[float],
                       conf_upper: list[float], window_interval_seconds: float):
    """
    Write ARIMA forecast rows to oee_predictions.
    target_time steps forward from NOW by window_interval_seconds per step
    so the forecast always points into the future.
    """
    cur = conn.cursor()
    # Always anchor from now so targets are in the future
    now = _utcnow()
    for i, (pred, lo, hi) in enumerate(zip(forecasts, conf_lower, conf_upper)):
        target_time = now + timedelta(seconds=window_interval_seconds * (i + 1))
        cur.execute("""
            INSERT INTO oee_predictions
              (machine_id, prediction_time, target_time,
               predicted_oee, confidence_lower, confidence_upper, model_type)
            VALUES (%s, %s, %s, %s, %s, %s, 'arima_auto')
        """, (
            machine_id,
            prediction_time,
            target_time,
            round(max(0, min(100, pred)), 2),
            round(max(0, min(100, lo)),   2),
            round(max(0, min(100, hi)),   2),
        ))
    conn.commit()


# ── ARIMA fitting ─────────────────────────────────────────────────────────────

def _fit_and_forecast(oee_values: list[float]) -> tuple[list, list, list] | None:
    """
    Fit an ARIMA model to oee_values and return (forecasts, lower_ci, upper_ci).

    auto_arima automatically selects the best (p, d, q) order by minimising AIC.
    We constrain the search space to keep it fast:
      - max_p=4, max_q=2  (OEE autocorrelation is short-range)
      - d=None            (auto_arima will difference if needed)
      - seasonal=False    (no daily seasonality in a 0.5 s series)

    Returns None if fitting fails (not enough data, numerical issues, etc.)
    """
    try:
        series = np.array(oee_values, dtype=float)

        model = pm.auto_arima(
            series,
            start_p=1, max_p=4,
            start_q=0, max_q=2,
            d=None,           # auto-detect differencing order
            seasonal=False,
            information_criterion="aic",
            stepwise=True,    # faster than exhaustive search
            suppress_warnings=True,
            error_action="ignore",
        )

        forecast, conf_int = model.predict(
            n_periods=FORECAST_STEPS,
            return_conf_int=True,
            alpha=0.05,       # 95 % confidence interval
        )

        return (
            forecast.tolist(),
            conf_int[:, 0].tolist(),
            conf_int[:, 1].tolist(),
        )

    except Exception as exc:
        print(f"  [ARIMA] Fitting failed: {exc}")
        return None


# ── main loop ─────────────────────────────────────────────────────────────────

def run_once():
    """Fit ARIMA for every machine and write forecasts to DB."""
    conn = psycopg2.connect(DB_CONF) if isinstance(DB_CONF, str) else psycopg2.connect(**DB_CONF)
    try:
        machines = _get_machines(conn)
        if not machines:
            print("  [ARIMA] No machines found in oee_raw_events yet.")
            return

        prediction_time = _utcnow()

        for machine_id in machines:
            rows = _get_history(conn, machine_id)

            if len(rows) < 30:
                print(f"  [ARIMA] {machine_id}: only {len(rows)} points — need ≥ 30, skipping.")
                continue

            oee_values = [r[1] for r in rows]

            # Use 30s window slide interval for target_time spacing
            # (matches Spark's 30-second slide, not the 0.5s raw event interval)
            WINDOW_SLIDE_SECONDS = 30.0

            result = _fit_and_forecast(oee_values)
            if result is None:
                continue

            forecasts, conf_lower, conf_upper = result
            _write_predictions(
                conn, machine_id, prediction_time,
                forecasts, conf_lower, conf_upper,
                WINDOW_SLIDE_SECONDS,
            )

            print(
                f"  [ARIMA] {machine_id}: "
                f"fitted on {len(oee_values)} pts → "
                f"next {FORECAST_STEPS} forecasts written "
                f"(first: {forecasts[0]:.1f}%)"
            )

    finally:
        conn.close()


if __name__ == "__main__":
    print("🔮 ARIMA Forecaster started")
    print(f"   History  : {HISTORY_POINTS} points per machine")
    print(f"   Horizon  : {FORECAST_STEPS} steps ahead")
    print(f"   Interval : every {RUN_INTERVAL_SECONDS} s\n")

    while True:
        try:
            run_once()
        except Exception as exc:
            print(f"  [ARIMA] Unexpected error: {exc}")
        time.sleep(RUN_INTERVAL_SECONDS)
