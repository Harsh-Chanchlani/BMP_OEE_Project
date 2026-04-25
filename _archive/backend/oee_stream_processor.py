"""
OEE Stream Processor — pure Python replacement for spark_oee_stream.py
Consumes from Confluent Kafka, does 1-min sliding window aggregation,
writes to Postgres, and produces alerts to OEE_ALERTS topic.
No Spark / JVM required.
"""

import os
import sys
import json
import uuid
import time
import signal
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from confluent_kafka import Consumer, Producer, KafkaError

# ── Config ────────────────────────────────────────────────────────────────────
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

BOOTSTRAP    = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
SASL_USER    = os.getenv("KAFKA_SASL_USERNAME", "")
SASL_PASS    = os.getenv("KAFKA_SASL_PASSWORD", "")
SOURCE_TOPIC = os.getenv("OEE_TOPIC",    "OEE_0")
ALERT_TOPIC  = os.getenv("ALERT_TOPIC",  "OEE_ALERTS")
WARNING_THR  = float(os.getenv("OEE_WARNING_THRESHOLD",  "70.0"))
CRITICAL_THR = float(os.getenv("OEE_CRITICAL_THRESHOLD", "55.0"))

# Window config: 1-min windows, 30-sec slide, flush every 10 sec
WINDOW_SECS  = 60
SLIDE_SECS   = 30
FLUSH_EVERY  = 10   # seconds between DB flushes

DB_CONF = dict(
    dbname   = os.getenv("PGDATABASE", "oee_db"),
    user     = os.getenv("PGUSER",     "harshchanchlani"),
    password = os.getenv("PGPASSWORD", ""),
    host     = os.getenv("PGHOST",     "localhost"),
    port     = os.getenv("PGPORT",     "5432"),
)

KAFKA_CONF = {
    "bootstrap.servers":  BOOTSTRAP,
    "security.protocol":  "SASL_SSL",
    "sasl.mechanisms":    "PLAIN",
    "sasl.username":      SASL_USER,
    "sasl.password":      SASL_PASS,
}

# ── Windowed aggregator ───────────────────────────────────────────────────────
class WindowAggregator:
    """
    Keeps a rolling buffer of (event_time, machine_id, oee) tuples.
    On flush, computes avg OEE per machine per 30-sec-aligned window.
    """
    def __init__(self):
        self.buffer = []   # list of (ts_float, machine_id, oee)

    def add(self, ts: float, machine_id: str, oee: float):
        self.buffer.append((ts, machine_id, oee))

    def flush(self):
        """Return list of (machine_id, window_start, window_end, avg_oee)."""
        now = time.time()
        cutoff = now - WINDOW_SECS * 4   # keep 4 windows of history
        self.buffer = [(t, m, o) for t, m, o in self.buffer if t >= cutoff]

        if not self.buffer:
            return []

        # Build windows aligned to SLIDE_SECS boundaries
        windows = defaultdict(list)
        for ts, machine_id, oee in self.buffer:
            # Find all slide windows this event belongs to
            slot = int(ts // SLIDE_SECS) * SLIDE_SECS
            for w_start in range(slot - WINDOW_SECS + SLIDE_SECS, slot + SLIDE_SECS, SLIDE_SECS):
                w_end = w_start + WINDOW_SECS
                if w_start <= ts < w_end:
                    windows[(machine_id, w_start, w_end)].append(oee)

        results = []
        for (machine_id, w_start, w_end), oees in windows.items():
            avg_oee = round(sum(oees) / len(oees), 4)
            results.append((
                machine_id,
                datetime.fromtimestamp(w_start, tz=timezone.utc).replace(tzinfo=None),
                datetime.fromtimestamp(w_end,   tz=timezone.utc).replace(tzinfo=None),
                avg_oee,
            ))
        return results

# ── DB writer ─────────────────────────────────────────────────────────────────
def write_to_postgres(rows, alert_producer):
    if not rows:
        return
    conn = psycopg2.connect(**DB_CONF)
    cur  = conn.cursor()
    written = 0
    for machine_id, w_start, w_end, avg_oee in rows:
        if not isinstance(machine_id, str) or not machine_id:
            continue
        if not (0 <= avg_oee <= 100):
            continue

        # Upsert to avoid duplicate windows
        cur.execute("""
            INSERT INTO oee_data (machine_id, window_start, window_end, avg_oee)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (machine_id, window_start, window_end) DO UPDATE
              SET avg_oee = EXCLUDED.avg_oee
        """, (machine_id, w_start, w_end, avg_oee))
        written += 1

        # Alerting
        if avg_oee < WARNING_THR:
            level     = "CRITICAL" if avg_oee < CRITICAL_THR else "WARNING"
            threshold = CRITICAL_THR if level == "CRITICAL" else WARNING_THR
            cur.execute("""
                INSERT INTO oee_alerts
                  (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (machine_id, avg_oee, threshold, w_start, w_end, level))

            if alert_producer:
                payload = {
                    "machine_id":   machine_id,
                    "avg_oee":      avg_oee,
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
        print(f"[DB] Wrote {written} window(s) at {datetime.now().strftime('%H:%M:%S')}")

# ── Ensure upsert constraint exists ──────────────────────────────────────────
def ensure_unique_constraint():
    try:
        conn = psycopg2.connect(**DB_CONF)
        cur  = conn.cursor()
        cur.execute("""
            DO $$
            BEGIN
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
        print(f"[WARN] Could not add unique constraint: {e}")

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    ensure_unique_constraint()

    consumer_conf = {**KAFKA_CONF,
        "group.id":          "oee-stream-processor",
        "auto.offset.reset": "latest",
    }
    consumer = Consumer(consumer_conf)
    consumer.subscribe([SOURCE_TOPIC])

    alert_producer = None
    try:
        alert_producer = Producer(KAFKA_CONF)
    except Exception as e:
        print(f"[WARN] Alert producer init failed: {e}")

    agg          = WindowAggregator()
    last_flush   = time.time()
    running      = True

    def shutdown(sig, frame):
        nonlocal running
        print("\n[INFO] Shutting down...")
        running = False

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"🚀 OEE Stream Processor started (Confluent Cloud, no Spark)")
    print(f"   Topic: {SOURCE_TOPIC} → Postgres oee_data")
    print(f"   Windows: {WINDOW_SECS}s / {SLIDE_SECS}s slide | Flush every {FLUSH_EVERY}s")

    while running:
        msg = consumer.poll(1.0)

        if msg is not None:
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"[ERROR] {msg.error()}")
            else:
                try:
                    data = json.loads(msg.value().decode("utf-8"))
                    ts   = float(data.get("timestamp", time.time()))
                    mid  = data.get("machine_id", "")
                    oee  = float(data.get("oee", 0))
                    if mid and 0 <= oee <= 100:
                        agg.add(ts, mid, oee)
                except Exception as e:
                    print(f"[WARN] Parse error: {e}")

        # Flush to DB every FLUSH_EVERY seconds
        if time.time() - last_flush >= FLUSH_EVERY:
            rows = agg.flush()
            write_to_postgres(rows, alert_producer)
            last_flush = time.time()

    consumer.close()
    if alert_producer:
        alert_producer.flush()
    print("[INFO] Stopped.")

if __name__ == "__main__":
    main()
