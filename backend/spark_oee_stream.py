"""
OEE Spark Structured Streaming Processor
Confluent Cloud → Spark → Postgres + Alert topic

PySpark 3.5.1 with spark-sql-kafka-0-10_2.12:3.5.1
"""

import os
import sys
import json
import uuid
import psycopg2
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
WARN_THR    = float(os.getenv("OEE_WARNING_THRESHOLD",  "70.0"))
CRIT_THR    = float(os.getenv("OEE_CRITICAL_THRESHOLD", "55.0"))

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

query.awaitTermination()
