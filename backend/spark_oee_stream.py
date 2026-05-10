"""
OEE Spark Structured Streaming Processor
Confluent Cloud → Spark → Postgres + Alert topic

PySpark 3.5.1 with spark-sql-kafka-0-10_2.12:3.5.1
"""

import os
import sys
import json
import uuid
import statistics
import psycopg2
import psycopg2.extras
from datetime import datetime
from confluent_kafka import Producer as ConfluentProducer

# ── Config loaders ────────────────────────────────────────────────────────────
def load_env_file(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def load_kafka_properties(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "ccloud-python-client", "client.properties")
    if not os.path.exists(path):
        return
    props = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    mapping = {
        "bootstrap.servers": "KAFKA_BOOTSTRAP_SERVERS",
        "sasl.username":     "KAFKA_SASL_USERNAME",
        "sasl.password":     "KAFKA_SASL_PASSWORD",
    }
    for src, env in mapping.items():
        if src in props:
            os.environ.setdefault(env, props[src])

load_env_file()
load_kafka_properties()

# ── Environment ───────────────────────────────────────────────────────────────
BOOTSTRAP   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
SASL_USER   = os.getenv("KAFKA_SASL_USERNAME", "")
SASL_PASS   = os.getenv("KAFKA_SASL_PASSWORD", "")
TOPIC       = os.getenv("OEE_TOPIC",   "OEE_0")
ALERT_TOPIC = os.getenv("ALERT_TOPIC", "OEE_ALERTS")
WARN_THR    = float(os.getenv("OEE_WARNING_THRESHOLD",  "55.0"))
CRIT_THR    = float(os.getenv("OEE_CRITICAL_THRESHOLD", "40.0"))

DB_CONF = dict(
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

# ── Alert producer (module-level, reused across batches) ──────────────────────
try:
    alert_producer = ConfluentProducer(KAFKA_CONF)
    print("[INFO] Alert producer initialized")
except Exception as e:
    print(f"[WARN] Alert producer init failed: {e}")
    alert_producer = None

# ── Spark session ─────────────────────────────────────────────────────────────
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    from_json, col, window, avg, from_unixtime,
    year, month, dayofmonth, hour
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, LongType
)

SCALA_VER  = os.getenv("SPARK_SCALA_BINARY_VERSION", "2.12")
SPARK_VER  = "3.5.1"
KAFKA_PKG  = f"org.apache.spark:spark-sql-kafka-0-10_{SCALA_VER}:{SPARK_VER}"

# Extra packages (e.g. S3/MinIO support) can be added via env var
extra = os.getenv("SPARK_EXTRA_PACKAGES", "").strip()
packages = ",".join([KAFKA_PKG] + [p for p in extra.split(",") if p])

spark = (
    SparkSession.builder
    .appName("OEE_Streaming")
    .config("spark.jars.packages", packages)
    .config("spark.sql.shuffle.partitions", "4")   # keep small for local/single-node
    .config("spark.ui.enabled", "false")            # disable Spark UI to save memory
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")

# ── Kafka source ──────────────────────────────────────────────────────────────
kafka_options = {
    "kafka.bootstrap.servers":  BOOTSTRAP,
    "subscribe":                TOPIC,
    "startingOffsets":          "latest",
    "kafka.security.protocol":  "SASL_SSL",
    "kafka.sasl.mechanism":     "PLAIN",
    "kafka.sasl.jaas.config": (
        "org.apache.kafka.common.security.plain.PlainLoginModule required "
        f'username="{SASL_USER}" password="{SASL_PASS}";'
    ),
    "failOnDataLoss": "false",
}

raw_df = spark.readStream.format("kafka").options(**kafka_options).load()

# ── Schema & parsing ──────────────────────────────────────────────────────────
msg_schema = StructType([
    StructField("machine_id",   StringType()),
    StructField("availability", DoubleType()),
    StructField("performance",  DoubleType()),
    StructField("quality",      DoubleType()),
    StructField("oee",          DoubleType()),
    StructField("timestamp",    DoubleType()),
    StructField("message_id",   StringType()),
    StructField("lot_id",       StringType()),
    StructField("recipe_name",  StringType()),
    StructField("chamber_id",   StringType()),
    StructField("shift",        StringType()),
    StructField("wph",          DoubleType()),
    StructField("loss_event",   StructType([
        StructField("name",      StringType()),
        StructField("component", StringType()),
    ])),
])

parsed = (
    raw_df
    .selectExpr("CAST(value AS STRING) as json_str")
    .select(from_json(col("json_str"), msg_schema).alias("d"))
    .select("d.*")
    .withColumn("event_time", from_unixtime(col("timestamp")).cast("timestamp"))
)

# ── Windowed aggregation ──────────────────────────────────────────────────────
windowed = (
    parsed
    .withWatermark("event_time", "2 minutes")
    .groupBy(
        window(col("event_time"), "1 minute", "30 seconds"),
        col("machine_id")
    )
    .agg(
        avg("oee").alias("avg_oee"),
        avg("availability").alias("avg_availability"),
        avg("performance").alias("avg_performance"),
        avg("quality").alias("avg_quality"),
    )
)

# ── Loss categories upsert ────────────────────────────────────────────────────
# Maps loss event component → Six Big Losses category
_LOSS_TYPE_MAP = {
    "availability": "Equipment Failure",
    "performance":  "Reduced Speed",
    "quality":      "Process Defects",
}

def _upsert_loss_categories(conn, raw_rows):
    """Write loss events from raw Kafka rows into loss_categories table."""
    cur = conn.cursor()
    for row in raw_rows:
        try:
            if not row.loss_event or not row.loss_event.name:
                continue
            component  = row.loss_event.component or "availability"
            loss_type  = _LOSS_TYPE_MAP.get(component, "Equipment Failure")
            # Estimate loss_percentage as the deviation from 100 on the affected component
            if component == "availability":
                loss_pct = round(max(0, 100 - (row.availability or 0)), 2)
            elif component == "performance":
                loss_pct = round(max(0, 100 - (row.performance or 0)), 2)
            else:
                loss_pct = round(max(0, 100 - (row.quality or 0)), 2)
            ts = datetime.utcfromtimestamp(row.timestamp) if row.timestamp else datetime.utcnow()
            cur.execute("""
                INSERT INTO loss_categories
                  (machine_id, timestamp, loss_type, loss_component, loss_percentage, description)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (row.machine_id, ts, loss_type, component, loss_pct, row.loss_event.name))
        except Exception as e:
            print(f"[WARN] _upsert_loss_categories failed for row: {e}")


# ── Shift helper ─────────────────────────────────────────────────────────────
def _shift_for_hour(h: int) -> str:
    if 6 <= h <= 13:  return "morning"
    if 14 <= h <= 21: return "afternoon"
    return "night"


# ── Shift performance upsert ──────────────────────────────────────────────────
def _upsert_shift_performance(conn, rows):
    """Aggregate OEE rows by (machine_id, shift_date, shift) and upsert into shift_performance."""
    from collections import defaultdict
    groups = defaultdict(list)
    for row in rows:
        shift_date = row.window.start.date()
        shift = _shift_for_hour(row.window.start.hour)
        key = (row.machine_id, shift_date, shift)
        groups[key].append(row.avg_oee)

    cur = conn.cursor()
    for (machine_id, shift_date, shift), oee_values in groups.items():
        valid = [v for v in oee_values if v is not None]
        if not valid:
            continue
        avg_oee = round(statistics.mean(valid), 4)
        min_oee = round(min(valid), 4)
        max_oee = round(max(valid), 4)
        data_points = len(valid)

        # Gather APQ values for the same group
        apq_rows = [r for r in rows
                    if r.machine_id == machine_id
                    and r.window.start.date() == shift_date
                    and _shift_for_hour(r.window.start.hour) == shift]
        avg_avail = round(statistics.mean([r.avg_availability for r in apq_rows if r.avg_availability is not None] or [0]), 4)
        avg_perf  = round(statistics.mean([r.avg_performance  for r in apq_rows if r.avg_performance  is not None] or [0]), 4)
        avg_qual  = round(statistics.mean([r.avg_quality      for r in apq_rows if r.avg_quality      is not None] or [0]), 4)

        cur.execute("""
            INSERT INTO shift_performance
              (machine_id, shift_date, shift, avg_oee, avg_availability,
               avg_performance, avg_quality, min_oee, max_oee, data_points)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (machine_id, shift_date, shift) DO UPDATE SET
                avg_oee          = EXCLUDED.avg_oee,
                avg_availability = EXCLUDED.avg_availability,
                avg_performance  = EXCLUDED.avg_performance,
                avg_quality      = EXCLUDED.avg_quality,
                min_oee          = EXCLUDED.min_oee,
                max_oee          = EXCLUDED.max_oee,
                data_points      = EXCLUDED.data_points
        """, (machine_id, shift_date, shift, avg_oee, avg_avail,
              avg_perf, avg_qual, min_oee, max_oee, data_points))


# ── SPC computation ───────────────────────────────────────────────────────────
def _compute_spc(conn, machine_id, batch_ts):
    """Compute SPC statistics for a machine using last 24h of oee_data."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT avg_oee FROM oee_data
            WHERE machine_id = %s
              AND window_start >= NOW() - INTERVAL '24 hours'
            ORDER BY window_start;
        """, (machine_id,))
        values = [r[0] for r in cur.fetchall() if r[0] is not None]
        if len(values) < 10:
            return
        mean = statistics.mean(values)
        std  = statistics.stdev(values)
        ucl  = mean + 3 * std
        lcl  = mean - 3 * std
        cur.execute("""
            INSERT INTO spc_data
              (machine_id, calculated_at, metric, mean_value, std_dev, ucl, lcl, sample_size)
            VALUES (%s, %s, 'oee', %s, %s, %s, %s, %s)
        """, (machine_id, batch_ts, round(mean, 4), round(std, 4),
              round(ucl, 4), round(lcl, 4), len(values)))
    except Exception as e:
        print(f"[WARN] _compute_spc failed for {machine_id}: {e}")


# ── Anomaly detection ─────────────────────────────────────────────────────────
def _detect_anomalies(conn, rows, ap, batch_ts):
    """Detect OEE anomalies (> 2 std below mean) and insert alerts + publish to Kafka.
    
    Uses SPC statistics calculated strictly before batch_ts to avoid circular dependency
    where _compute_spc contaminates the mean with the current batch's data.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    for row in rows:
        try:
            cur.execute("""
                SELECT mean_value, std_dev FROM spc_data
                WHERE machine_id = %s AND metric = 'oee'
                  AND calculated_at < %s
                ORDER BY calculated_at DESC LIMIT 1;
            """, (row.machine_id, batch_ts))
            spc = cur.fetchone()
            if not spc:
                continue
            threshold = spc["mean_value"] - 2 * spc["std_dev"]
            if row.avg_oee < threshold:
                msg = (f"ANOMALY: {row.machine_id} OEE={round(row.avg_oee,2)} "
                       f"< mean({round(spc['mean_value'],2)}) - 2*std({round(spc['std_dev'],2)})")
                cur2 = conn.cursor()
                cur2.execute("""
                    INSERT INTO oee_alerts
                      (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
                    VALUES (%s, %s, %s, %s, %s, 'ANOMALY')
                """, (row.machine_id, round(row.avg_oee, 4), round(threshold, 4),
                      row.window.start, row.window.end))
                if ap:
                    payload = {
                        "machine_id":   row.machine_id,
                        "avg_oee":      round(row.avg_oee, 2),
                        "threshold":    round(threshold, 2),
                        "alert_level":  "ANOMALY",
                        "window_start": row.window.start.isoformat(),
                        "window_end":   row.window.end.isoformat(),
                        "alert_id":     str(uuid.uuid4()),
                    }
                    try:
                        ap.produce(ALERT_TOPIC, value=json.dumps(payload).encode())
                        ap.poll(0)
                    except Exception as e:
                        print(f"[WARN] Anomaly alert produce failed: {e}")
        except Exception as e:
            print(f"[WARN] _detect_anomalies failed for {row.machine_id}: {e}")


# ── Raw batch writer: loss categories + raw OEE events ───────────────────────
def write_raw_batch(batch_df, batch_id):
    """Write raw OEE events and loss events from raw parsed messages."""
    rows = batch_df.collect()
    if not rows:
        return
    conn = psycopg2.connect(**DB_CONF)
    try:
        _upsert_loss_categories(conn, rows)
        _insert_raw_oee_events(conn, rows)
        conn.commit()
    except Exception as e:
        print(f"[WARN] write_raw_batch error: {e}")
    finally:
        conn.close()


def _insert_raw_oee_events(conn, raw_rows):
    """Insert individual raw OEE readings into oee_raw_events for ML/ARIMA use."""
    cur = conn.cursor()
    for row in raw_rows:
        try:
            if not row.machine_id or row.oee is None:
                continue
            if not (0 <= row.oee <= 100):
                continue
            event_time = datetime.utcfromtimestamp(row.timestamp) if row.timestamp else datetime.utcnow()
            loss_name = row.loss_event.name      if row.loss_event else None
            loss_comp = row.loss_event.component if row.loss_event else None
            cur.execute("""
                INSERT INTO oee_raw_events
                  (machine_id, event_time, oee, availability, performance, quality,
                   lot_id, recipe_name, chamber_id, shift, wph,
                   loss_event_name, loss_event_component, message_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                row.machine_id, event_time,
                round(row.oee, 4),
                round(row.availability or 0, 4),
                round(row.performance  or 0, 4),
                round(row.quality      or 0, 4),
                getattr(row, "lot_id",      None),
                getattr(row, "recipe_name", None),
                getattr(row, "chamber_id",  None),
                getattr(row, "shift",       None),
                getattr(row, "wph",         None),
                loss_name, loss_comp,
                getattr(row, "message_id",  None),
            ))
        except Exception as e:
            print(f"[WARN] _insert_raw_oee_events failed for row: {e}")


# ── Batch writer: Postgres + Alerts ──────────────────────────────────────────
def write_batch(batch_df, batch_id):
    rows = batch_df.collect()
    if not rows:
        return

    conn = psycopg2.connect(**DB_CONF)
    cur  = conn.cursor()
    written = 0

    for row in rows:
        # Basic validation
        if not isinstance(row.machine_id, str) or not row.machine_id:
            continue
        if not (0 <= row.avg_oee <= 100):
            continue

        w_start = row.window.start
        w_end   = row.window.end

        # Upsert OEE window
        cur.execute("""
            INSERT INTO oee_data (machine_id, window_start, window_end, avg_oee,
                                  avg_availability, avg_performance, avg_quality)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (machine_id, window_start, window_end)
            DO UPDATE SET
                avg_oee          = EXCLUDED.avg_oee,
                avg_availability = EXCLUDED.avg_availability,
                avg_performance  = EXCLUDED.avg_performance,
                avg_quality      = EXCLUDED.avg_quality
        """, (
            row.machine_id, w_start, w_end,
            round(row.avg_oee, 4),
            round(row.avg_availability or 0, 4),
            round(row.avg_performance  or 0, 4),
            round(row.avg_quality      or 0, 4),
        ))
        written += 1

        # Alerting
        if row.avg_oee < WARN_THR:
            level     = "CRITICAL" if row.avg_oee < CRIT_THR else "WARNING"
            threshold = CRIT_THR   if level == "CRITICAL"    else WARN_THR

            cur.execute("""
                INSERT INTO oee_alerts
                  (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (row.machine_id, round(row.avg_oee, 4), threshold, w_start, w_end, level))

            if alert_producer:
                payload = {
                    "machine_id":   row.machine_id,
                    "avg_oee":      round(row.avg_oee, 2),
                    "threshold":    threshold,
                    "alert_level":  level,
                    "window_start": w_start.isoformat(),
                    "window_end":   w_end.isoformat(),
                    "alert_id":     str(uuid.uuid4()),
                }
                try:
                    alert_producer.produce(ALERT_TOPIC, value=json.dumps(payload).encode())
                    alert_producer.poll(0)
                except Exception as e:
                    print(f"[WARN] Alert produce failed: {e}")

    conn.commit()

    # ── Analytics helpers ─────────────────────────────────────────────────────
    batch_ts = datetime.utcnow()
    machine_ids = {row.machine_id for row in rows if isinstance(row.machine_id, str) and row.machine_id}
    for machine_id in machine_ids:
        _compute_spc(conn, machine_id, batch_ts)
    _upsert_shift_performance(conn, rows)
    _detect_anomalies(conn, rows, alert_producer, batch_ts)
    conn.commit()

    cur.close()
    conn.close()

    if written:
        print(f"[Spark] Batch {batch_id}: wrote {written} window(s) at "
              f"{datetime.now().strftime('%H:%M:%S')}")

# ── Ensure schema supports new columns ───────────────────────────────────────
def ensure_schema():
    try:
        conn = psycopg2.connect(**DB_CONF)
        cur  = conn.cursor()
        for col_name in ("avg_availability", "avg_performance", "avg_quality"):
            cur.execute(f"""
                ALTER TABLE oee_data
                ADD COLUMN IF NOT EXISTS {col_name} DOUBLE PRECISION;
            """)
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
    except Exception as e:
        print(f"[WARN] Schema migration: {e}")

ensure_schema()

# ── Start streaming query ─────────────────────────────────────────────────────
print(f"🚀 OEE Spark Streaming started")
print(f"   Topic: {TOPIC} → Postgres oee_data")
print(f"   Windows: 1 min / 30s slide | Trigger: 10s")

query = (
    windowed.writeStream
    .outputMode("update")
    .foreachBatch(write_batch)
    .trigger(processingTime="10 seconds")
    .option("checkpointLocation", "/tmp/oee_spark_checkpoint")
    .start()
)

# Second stream: raw messages → loss_categories
raw_query = (
    parsed.writeStream
    .outputMode("append")
    .foreachBatch(write_raw_batch)
    .trigger(processingTime="10 seconds")
    .option("checkpointLocation", "/tmp/oee_spark_raw_checkpoint")
    .start()
)

query.awaitTermination()
