"""
OEE Spark Structured Streaming Processor
==========================================
Confluent Cloud (Kafka) → PySpark → PostgreSQL

What this script does, step by step:
  1. Reads raw OEE messages from Kafka topic OEE_0.
  2. Parses and validates each message.
  3. Runs TWO parallel Spark streaming queries:

     Stream A — Raw events writer
       Every 10 s: writes each individual message to oee_raw_events.
       Also writes the active loss category to loss_categories.

     Stream B — Windowed aggregation writer
       Every 10 s: groups events into 1-minute windows (30 s slide),
       computes avg A / P / Q / OEE per machine per window, then:
         • Upserts into oee_data
         • Fires WARNING / CRITICAL threshold alerts → oee_alerts + Kafka
         • Computes SPC (mean ± 3σ) from last 24 h → spc_data
         • Detects statistical anomalies (OEE < mean − 2σ) → oee_alerts
         • Aggregates shift performance → shift_performance

OEE Formula (Kennedy):
  Availability = Run Time / Planned Production Time  × 100
  Performance  = (Ideal Cycle Time × Total Pieces) / Run Time  × 100
  Quality      = Good Pieces / Total Pieces  × 100
  OEE          = (A × P × Q) / 10 000

Note: The producer already computes A/P/Q/OEE from raw inputs.
      Spark re-uses those values and averages them over the window.
      The raw inputs (planned_time, downtime, pieces) are also stored
      so OEE can be re-derived from first principles if needed.
"""

import json
import os
import statistics
import time
import uuid
from datetime import datetime, timezone

def _utcnow():
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)

import psycopg2
import psycopg2.extras
from confluent_kafka import Producer as ConfluentProducer


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

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


def _load_kafka_props(path=None):
    path = path or os.path.join(
        os.path.dirname(__file__), "..", "ccloud-python-client", "client.properties"
    )
    if not os.path.exists(path):
        return
    props = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    for src, env in [
        ("bootstrap.servers", "KAFKA_BOOTSTRAP_SERVERS"),
        ("sasl.username",     "KAFKA_SASL_USERNAME"),
        ("sasl.password",     "KAFKA_SASL_PASSWORD"),
    ]:
        if src in props:
            os.environ.setdefault(env, props[src])


_load_env()
_load_kafka_props()

BOOTSTRAP   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
SASL_USER   = os.getenv("KAFKA_SASL_USERNAME", "")
SASL_PASS   = os.getenv("KAFKA_SASL_PASSWORD", "")
OEE_TOPIC   = os.getenv("OEE_TOPIC",   "OEE_0")
ALERT_TOPIC = os.getenv("ALERT_TOPIC", "OEE_ALERTS")

# Alert thresholds (% OEE)
WARN_THRESHOLD = float(os.getenv("OEE_WARNING_THRESHOLD",  "55.0"))
CRIT_THRESHOLD = float(os.getenv("OEE_CRITICAL_THRESHOLD", "40.0"))

# Use DATABASE_URL (Neon) if set, otherwise fall back to local PG env vars
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
DB_CONF = _DATABASE_URL if _DATABASE_URL else dict(
    dbname   = os.getenv("PGDATABASE", "oee_db"),
    user     = os.getenv("PGUSER",     "harshchanchlani"),
    password = os.getenv("PGPASSWORD", ""),
    host     = os.getenv("PGHOST",     "localhost"),
    port     = os.getenv("PGPORT",     "5432"),
)

KAFKA_CONF = {
    "bootstrap.servers": BOOTSTRAP,
    "security.protocol": "SASL_SSL",
    "sasl.mechanisms":   "PLAIN",
    "sasl.username":     SASL_USER,
    "sasl.password":     SASL_PASS,
}


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT KAFKA PRODUCER  (module-level, reused across batches)
# ═══════════════════════════════════════════════════════════════════════════════
try:
    alert_producer = ConfluentProducer(KAFKA_CONF)
    print("[INFO] Alert Kafka producer ready.")
except Exception as exc:
    print(f"[WARN] Alert producer init failed: {exc}")
    alert_producer = None


# ═══════════════════════════════════════════════════════════════════════════════
# SPARK SESSION
# ═══════════════════════════════════════════════════════════════════════════════
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    avg, col, from_json, from_unixtime, window,
)
from pyspark.sql.types import (
    DoubleType, StringType, StructField, StructType,
)

SCALA_VER = os.getenv("SPARK_SCALA_BINARY_VERSION", "2.12")
SPARK_VER = "3.5.1"
KAFKA_PKG  = f"org.apache.spark:spark-sql-kafka-0-10_{SCALA_VER}:{SPARK_VER}"

extra_pkgs = os.getenv("SPARK_EXTRA_PACKAGES", "").strip()
all_pkgs   = ",".join([KAFKA_PKG] + [p for p in extra_pkgs.split(",") if p])

spark = (
    SparkSession.builder
    .appName("OEE_Streaming")
    .config("spark.jars.packages",          all_pkgs)
    .config("spark.sql.shuffle.partitions", "4")    # small for single-node
    .config("spark.ui.enabled",             "false") # save memory
    # Force UTC throughout — from_unixtime() uses the session timezone.
    # Without this, timestamps are stored in the JVM's local timezone and
    # displayed incorrectly in the browser (e.g. 11 AM instead of 5:40 PM).
    .config("spark.sql.session.timeZone",   "UTC")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")


# ═══════════════════════════════════════════════════════════════════════════════
# KAFKA SOURCE
# ═══════════════════════════════════════════════════════════════════════════════
kafka_options = {
    "kafka.bootstrap.servers": BOOTSTRAP,
    "subscribe":               OEE_TOPIC,
    "startingOffsets":         "latest",
    "kafka.security.protocol": "SASL_SSL",
    "kafka.sasl.mechanism":    "PLAIN",
    "kafka.sasl.jaas.config": (
        "org.apache.kafka.common.security.plain.PlainLoginModule required "
        f'username="{SASL_USER}" password="{SASL_PASS}";'
    ),
    "failOnDataLoss": "false",
}

raw_kafka_df = spark.readStream.format("kafka").options(**kafka_options).load()


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE SCHEMA  (must match producer/Producer.py and schema/oee_message_schema.json)
# ═══════════════════════════════════════════════════════════════════════════════
MSG_SCHEMA = StructType([
    StructField("machine_id",                  StringType()),
    StructField("message_id",                  StringType()),
    StructField("timestamp",                   DoubleType()),
    StructField("shift",                       StringType()),
    StructField("lot_id",                      StringType()),
    # Raw production inputs
    StructField("planned_production_time_min", DoubleType()),
    StructField("downtime_min",                DoubleType()),
    StructField("ideal_cycle_time_min",        DoubleType()),
    StructField("total_pieces_run",            DoubleType()),
    StructField("good_pieces",                 DoubleType()),
    # Derived OEE components (computed by producer)
    StructField("availability",                DoubleType()),
    StructField("performance",                 DoubleType()),
    StructField("quality",                     DoubleType()),
    StructField("oee",                         DoubleType()),
    # Active loss category
    StructField("loss_category", StructType([
        StructField("name",      StringType()),
        StructField("type",      StringType()),
        StructField("component", StringType()),
    ])),
])

# Parse JSON → typed columns, add event_time for windowing
parsed_df = (
    raw_kafka_df
    .selectExpr("CAST(value AS STRING) AS json_str")
    .select(from_json(col("json_str"), MSG_SCHEMA).alias("d"))
    .select("d.*")
    .withColumn("event_time", from_unixtime(col("timestamp")).cast("timestamp"))
)


# ═══════════════════════════════════════════════════════════════════════════════
# WINDOWED AGGREGATION
# 1-minute window, 30-second slide, 2-minute watermark
# ═══════════════════════════════════════════════════════════════════════════════
windowed_df = (
    parsed_df
    .withWatermark("event_time", "2 minutes")
    .groupBy(
        window(col("event_time"), "1 minute", "30 seconds"),
        col("machine_id"),
    )
    .agg(
        avg("oee").alias("avg_oee"),
        avg("availability").alias("avg_availability"),
        avg("performance").alias("avg_performance"),
        avg("quality").alias("avg_quality"),
    )
)


# ═══════════════════════════════════════════════════════════════════════════════
# DB HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _db_connect():
    """
    Connect to Neon (or local PG) with generous timeouts.
    Neon serverless instances cold-start in ~1-3s and can have higher
    network latency than a local DB, so we raise all timeout values.
    """
    connect_timeout = int(os.getenv("PG_CONNECT_TIMEOUT", "30"))   # seconds to establish TCP
    options = (
        f"-c statement_timeout={os.getenv('PG_STATEMENT_TIMEOUT', '60000')} "   # ms per statement
        f"-c lock_timeout={os.getenv('PG_LOCK_TIMEOUT', '30000')} "             # ms waiting for locks
        f"-c idle_in_transaction_session_timeout={os.getenv('PG_IDLE_TX_TIMEOUT', '60000')}"  # ms idle in tx
    )
    if isinstance(DB_CONF, str):
        return psycopg2.connect(
            DB_CONF,
            connect_timeout=connect_timeout,
            options=options,
        )
    return psycopg2.connect(
        **DB_CONF,
        connect_timeout=connect_timeout,
        options=options,
    )


def _db_connect_with_retry(max_attempts: int = 5, base_delay: float = 2.0):
    """
    Retry wrapper for _db_connect().
    Neon serverless can take a few seconds to wake from idle, so we retry
    with exponential back-off before giving up.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _db_connect()
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))   # 2s, 4s, 8s, 16s
                print(f"[WARN] DB connect attempt {attempt}/{max_attempts} failed: {exc} — retrying in {delay:.0f}s")
                time.sleep(delay)
    raise last_exc
    if 6 <= h < 14:
        return "morning"
    if 14 <= h < 22:
        return "afternoon"
    return "night"


# ── Stream A helpers ──────────────────────────────────────────────────────────

def _write_raw_events(conn, rows: list):
    """
    Insert individual OEE readings into oee_raw_events using executemany()
    — single round-trip to Neon instead of one per row.
    """
    params = []
    for r in rows:
        if not r.machine_id or r.oee is None:
            continue
        if not (0 <= r.oee <= 100):
            continue
        event_time = (
            datetime.fromtimestamp(r.timestamp, tz=timezone.utc)
            if r.timestamp else _utcnow()
        )
        loss_name = r.loss_category.name      if r.loss_category else "none"
        loss_comp = r.loss_category.component if r.loss_category else "none"
        params.append((
            r.machine_id, event_time,
            round(r.oee,          4),
            round(r.availability  or 0, 4),
            round(r.performance   or 0, 4),
            round(r.quality       or 0, 4),
            getattr(r, "lot_id", None),
            getattr(r, "shift",  None),
            loss_name, loss_comp,
            getattr(r, "message_id", None),
        ))
    if not params:
        return
    cur = conn.cursor()
    cur.executemany("""
        INSERT INTO oee_raw_events
          (machine_id, event_time, oee, availability, performance, quality,
           lot_id, shift, loss_event_name, loss_event_component, message_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, params)
    cur.close()


def _write_loss_categories(conn, rows: list):
    """
    Write active loss events to loss_categories (Kennedy's 7 OEE Losses table).
    Only writes rows where a real loss is active (type != 'none').

    Kennedy's Time-Loss model (Chapter 3):
      loss_minutes = actual time lost to this loss in this window
      loss_percentage = how much the affected component deviated from 100%

    For each raw event (0.5s window):
      - availability loss: downtime_min is the actual time lost
      - performance loss: time lost = planned_window × (1 - speed_ratio)
      - quality loss: time lost = (defect_pieces / ideal_speed) in minutes
    """
    cur = conn.cursor()
    for r in rows:
        if not r.loss_category or r.loss_category.type == "none":
            continue
        comp    = r.loss_category.component
        planned = getattr(r, "planned_production_time_min", 0.5) or 0.5

        # ── Loss percentage: deviation of the affected component from 100% ──
        if comp == "availability":
            loss_pct = round(max(0, 100 - (r.availability or 0)), 2)
            # Time lost = downtime_min (the actual recorded downtime for this window)
            loss_min = round(max(0, getattr(r, "downtime_min", 0) or 0), 4)
        elif comp == "performance":
            loss_pct = round(max(0, 100 - (r.performance or 0)), 2)
            # Time lost = planned window × performance loss fraction
            loss_min = round(planned * (loss_pct / 100.0), 4)
        else:  # quality
            loss_pct = round(max(0, 100 - (r.quality or 0)), 2)
            # Time lost = quality loss fraction × planned window
            loss_min = round(planned * (loss_pct / 100.0), 4)

        ts = (
            datetime.fromtimestamp(r.timestamp, tz=timezone.utc)
            if r.timestamp else _utcnow()
        )
        cur.execute("""
            INSERT INTO loss_categories
              (machine_id, timestamp, loss_type, loss_component,
               loss_percentage, loss_minutes, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            r.machine_id, ts,
            r.loss_category.type,
            comp,
            loss_pct,
            loss_min,
            r.loss_category.name,
        ))


# ── Stream B helpers ──────────────────────────────────────────────────────────

def _upsert_oee_windows(conn, rows: list) -> int:
    """
    Upsert windowed OEE aggregates into oee_data.
    Returns the number of rows written.
    """
    cur = conn.cursor()
    written = 0
    for r in rows:
        if not isinstance(r.machine_id, str) or not r.machine_id:
            continue
        if r.avg_oee is None or not (0 <= r.avg_oee <= 100):
            continue
        cur.execute("""
            INSERT INTO oee_data
              (machine_id, window_start, window_end,
               avg_oee, avg_availability, avg_performance, avg_quality)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (machine_id, window_start, window_end) DO UPDATE SET
                avg_oee          = EXCLUDED.avg_oee,
                avg_availability = EXCLUDED.avg_availability,
                avg_performance  = EXCLUDED.avg_performance,
                avg_quality      = EXCLUDED.avg_quality
        """, (
            r.machine_id,
            r.window.start,
            r.window.end,
            round(r.avg_oee,          4),
            round(r.avg_availability  or 0, 4),
            round(r.avg_performance   or 0, 4),
            round(r.avg_quality       or 0, 4),
        ))
        written += 1
    return written


def _fire_threshold_alerts(conn, rows: list):
    """
    Insert WARNING / CRITICAL alerts when avg_oee falls below thresholds.
    Also publishes the alert to the Kafka ALERT_TOPIC.
    """
    cur = conn.cursor()
    for r in rows:
        if r.avg_oee is None or r.avg_oee >= WARN_THRESHOLD:
            continue

        level     = "CRITICAL" if r.avg_oee < CRIT_THRESHOLD else "WARNING"
        threshold = CRIT_THRESHOLD if level == "CRITICAL" else WARN_THRESHOLD

        cur.execute("""
            INSERT INTO oee_alerts
              (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            r.machine_id,
            round(r.avg_oee, 4),
            threshold,
            r.window.start,
            r.window.end,
            level,
        ))

        if alert_producer:
            payload = {
                "machine_id":   r.machine_id,
                "avg_oee":      round(r.avg_oee, 2),
                "threshold":    threshold,
                "alert_level":  level,
                "window_start": r.window.start.isoformat(),
                "window_end":   r.window.end.isoformat(),
                "alert_id":     str(uuid.uuid4()),
            }
            try:
                alert_producer.produce(ALERT_TOPIC, value=json.dumps(payload).encode())
                alert_producer.poll(0)
            except Exception as exc:
                print(f"[WARN] Kafka alert produce failed: {exc}")


def _compute_spc(conn, machine_id: str, batch_ts: datetime):
    """
    Compute SPC statistics (mean, std, UCL, LCL) for a machine
    using the last 24 hours of windowed OEE data.

    UCL = mean + 3 × std  (Upper Control Limit)
    LCL = mean − 3 × std  (Lower Control Limit)

    Requires at least 10 data points to be meaningful.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT avg_oee FROM oee_data
        WHERE machine_id = %s
          AND window_start >= NOW() - INTERVAL '24 hours'
        ORDER BY window_start;
    """, (machine_id,))
    values = [r[0] for r in cur.fetchall() if r[0] is not None]

    if len(values) < 10:
        return  # not enough data yet

    mean = statistics.mean(values)
    std  = statistics.stdev(values)
    ucl  = mean + 3 * std
    lcl  = mean - 3 * std

    cur.execute("""
        INSERT INTO spc_data
          (machine_id, calculated_at, metric, mean_value, std_dev, ucl, lcl, sample_size)
        VALUES (%s, %s, 'oee', %s, %s, %s, %s, %s)
    """, (
        machine_id, batch_ts,
        round(mean, 4), round(std, 4),
        round(ucl,  4), round(lcl, 4),
        len(values),
    ))


def _detect_spc_anomalies(conn, rows: list, batch_ts: datetime):
    """
    Flag windows where OEE is more than 2 standard deviations below the mean
    (using SPC stats computed *before* this batch to avoid circular dependency).

    Inserts an ANOMALY alert into oee_alerts and publishes to Kafka.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    for r in rows:
        if r.avg_oee is None:
            continue
        # Use the most recent SPC stats calculated before this batch
        cur.execute("""
            SELECT mean_value, std_dev FROM spc_data
            WHERE machine_id = %s AND metric = 'oee'
              AND calculated_at < %s
            ORDER BY calculated_at DESC LIMIT 1;
        """, (r.machine_id, batch_ts))
        spc = cur.fetchone()
        if not spc:
            continue

        anomaly_threshold = spc["mean_value"] - 2 * spc["std_dev"]
        if r.avg_oee >= anomaly_threshold:
            continue

        # Insert anomaly alert
        cur2 = conn.cursor()
        cur2.execute("""
            INSERT INTO oee_alerts
              (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
            VALUES (%s, %s, %s, %s, %s, 'ANOMALY')
        """, (
            r.machine_id,
            round(r.avg_oee, 4),
            round(anomaly_threshold, 4),
            r.window.start,
            r.window.end,
        ))

        if alert_producer:
            payload = {
                "machine_id":   r.machine_id,
                "avg_oee":      round(r.avg_oee, 2),
                "threshold":    round(anomaly_threshold, 2),
                "alert_level":  "ANOMALY",
                "window_start": r.window.start.isoformat(),
                "window_end":   r.window.end.isoformat(),
                "alert_id":     str(uuid.uuid4()),
            }
            try:
                alert_producer.produce(ALERT_TOPIC, value=json.dumps(payload).encode())
                alert_producer.poll(0)
            except Exception as exc:
                print(f"[WARN] Kafka anomaly alert failed: {exc}")


def _upsert_shift_performance(conn, rows: list):
    """
    Aggregate windowed OEE rows by (machine_id, shift_date, shift)
    and upsert into shift_performance.
    """
    from collections import defaultdict

    # Group rows by (machine_id, shift_date, shift)
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r.avg_oee is None:
            continue
        shift_date = r.window.start.date()
        shift      = _shift_for_hour(r.window.start.hour)
        groups[(r.machine_id, shift_date, shift)].append(r)

    cur = conn.cursor()
    for (machine_id, shift_date, shift), group_rows in groups.items():
        oee_vals  = [r.avg_oee         for r in group_rows if r.avg_oee         is not None]
        avail_vals = [r.avg_availability for r in group_rows if r.avg_availability is not None]
        perf_vals  = [r.avg_performance  for r in group_rows if r.avg_performance  is not None]
        qual_vals  = [r.avg_quality      for r in group_rows if r.avg_quality      is not None]

        if not oee_vals:
            continue

        cur.execute("""
            INSERT INTO shift_performance
              (machine_id, shift_date, shift,
               avg_oee, avg_availability, avg_performance, avg_quality,
               min_oee, max_oee, data_points)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (machine_id, shift_date, shift) DO UPDATE SET
                avg_oee          = EXCLUDED.avg_oee,
                avg_availability = EXCLUDED.avg_availability,
                avg_performance  = EXCLUDED.avg_performance,
                avg_quality      = EXCLUDED.avg_quality,
                min_oee          = EXCLUDED.min_oee,
                max_oee          = EXCLUDED.max_oee,
                data_points      = EXCLUDED.data_points
        """, (
            machine_id, shift_date, shift,
            round(statistics.mean(oee_vals),   4),
            round(statistics.mean(avail_vals) if avail_vals else 0, 4),
            round(statistics.mean(perf_vals)  if perf_vals  else 0, 4),
            round(statistics.mean(qual_vals)  if qual_vals  else 0, 4),
            round(min(oee_vals), 4),
            round(max(oee_vals), 4),
            len(oee_vals),
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# STREAM A — foreachBatch: raw events + loss categories
# ═══════════════════════════════════════════════════════════════════════════════
def write_raw_batch(batch_df, batch_id):
    """Called every 3 s with raw parsed messages."""
    rows = batch_df.collect()
    if not rows:
        return
    conn = _db_connect_with_retry()
    try:
        _write_raw_events(conn, rows)
        _write_loss_categories(conn, rows)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] write_raw_batch (batch {batch_id}): {exc}")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# STREAM B — foreachBatch: windowed OEE + alerts + SPC + shifts
# ═══════════════════════════════════════════════════════════════════════════════
def write_windowed_batch(batch_df, batch_id):
    """Called every 10 s with windowed aggregates."""
    rows = batch_df.collect()
    if not rows:
        return

    conn      = _db_connect_with_retry()
    batch_ts  = _utcnow()

    try:
        # 1. Write windowed OEE averages
        written = _upsert_oee_windows(conn, rows)

        # 2. Fire threshold-based alerts (WARNING / CRITICAL)
        _fire_threshold_alerts(conn, rows)

        conn.commit()  # commit OEE data + threshold alerts before SPC

        # 3. Compute SPC for each machine (uses data already committed above)
        machine_ids = {r.machine_id for r in rows if r.machine_id}
        for mid in machine_ids:
            _compute_spc(conn, mid, batch_ts)

        # 4. Detect statistical anomalies using SPC stats from *before* this batch
        _detect_spc_anomalies(conn, rows, batch_ts)

        # 5. Aggregate shift performance
        _upsert_shift_performance(conn, rows)

        conn.commit()

        if written:
            print(
                f"[Spark] Batch {batch_id}: {written} window(s) written "
                f"at {datetime.now().strftime('%H:%M:%S')}"
            )

    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] write_windowed_batch (batch {batch_id}): {exc}")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA MIGRATION  (idempotent — safe to run on every start)
# ═══════════════════════════════════════════════════════════════════════════════
def _ensure_schema():
    """Add any missing columns and constraints to existing tables."""
    try:
        conn = _db_connect_with_retry()
        cur  = conn.cursor()

        # Ensure APQ columns exist on oee_data
        for col_name in ("avg_availability", "avg_performance", "avg_quality"):
            cur.execute(f"""
                ALTER TABLE oee_data
                ADD COLUMN IF NOT EXISTS {col_name} DOUBLE PRECISION;
            """)

        # Ensure unique constraint for upsert
        cur.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'oee_data_machine_window_unique'
              ) THEN
                ALTER TABLE oee_data
                  ADD CONSTRAINT oee_data_machine_window_unique
                  UNIQUE (machine_id, window_start, window_end);
              END IF;
            END$$;
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("[INFO] Schema migration complete.")
    except Exception as exc:
        print(f"[WARN] Schema migration: {exc}")


_ensure_schema()


# ═══════════════════════════════════════════════════════════════════════════════
# START STREAMING QUERIES
# ═══════════════════════════════════════════════════════════════════════════════
print("🚀 OEE Spark Streaming started")
print(f"   Source topic : {OEE_TOPIC}")
print(f"   Alert topic  : {ALERT_TOPIC}")
print(f"   Window       : 1 min / 30 s slide | Trigger: 10 s")
print(f"   Thresholds   : WARNING < {WARN_THRESHOLD}%  CRITICAL < {CRIT_THRESHOLD}%\n")

# Stream A — raw events
# Trigger every 3 s so the real-time OEE chart has minimal lag.
# Kafka buffers messages safely between triggers — nothing is lost.
stream_raw = (
    parsed_df.writeStream
    .outputMode("append")
    .foreachBatch(write_raw_batch)
    .trigger(processingTime="3 seconds")
    .option("checkpointLocation", "/tmp/oee_checkpoint_raw")
    .start()
)

# Stream B — windowed aggregates
stream_windowed = (
    windowed_df.writeStream
    .outputMode("update")
    .foreachBatch(write_windowed_batch)
    .trigger(processingTime="10 seconds")
    .option("checkpointLocation", "/tmp/oee_checkpoint_windowed")
    .start()
)

stream_windowed.awaitTermination()
