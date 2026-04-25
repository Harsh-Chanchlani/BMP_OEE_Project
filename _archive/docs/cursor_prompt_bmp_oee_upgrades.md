# Cursor Implementation Prompt — BMP OEE Project Full Upgrade

## Context — What Already Exists

This is a Python/FastAPI/PySpark project for real-time OEE (Overall Equipment
Effectiveness) monitoring. The current repo contains:

- **`Producer.py`** — Confluent Kafka producer. Simulates a single machine
  (`M2_MAC_SIM`), emits `{machine_id, availability, performance, quality,
  timestamp, oee}` as JSON to topic `OEE_0` every 2 seconds. Uses SASL/SSL to
  Confluent Cloud GCP (`pkc-619z3.us-east1.gcp.confluent.cloud:9092`).
  Credentials loaded from `.env` or
  `ccloud-python-client/client.properties`.

- **`spark_oee_stream.py`** — PySpark Structured Streaming consumer.  Reads
  `OEE_0`, parses JSON, converts UNIX timestamp → event_time, applies a
  1-minute sliding window (30 s slide, 2 min watermark), computes `avg_oee`
  per `machine_id`, writes each micro-batch to PostgreSQL table `oee_data`
  via `foreachBatch` + `psycopg2`. Trigger fires every 10 seconds.

- **`api.py`** — FastAPI app. Four endpoints: `GET /api/machines`, `GET
  /api/oee/latest?machine=`, `GET /api/oee/history?machine=&limit=30`, `GET
  /api/oee/stats?machine=`. CORS allowed for `localhost:5173` and
  `localhost:3000`. **No auth, no WebSocket.**

- **`db/init_oee_schema.sql`** — Creates `oee_data` table with columns
  `id (BIGSERIAL PK)`, `machine_id TEXT`, `window_start TIMESTAMP`,
  `window_end TIMESTAMP`, `avg_oee DOUBLE PRECISION`, `created_at TIMESTAMP`.
  Two indexes: `idx_oee_data_window_start`, `idx_oee_data_machine_window`.

- **`.env.example`** — Contains `KAFKA_BOOTSTRAP_SERVERS`,
  `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`, `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `GRAFANA_ADMIN_USER`,
  `GRAFANA_ADMIN_PASSWORD`.

- **`oee-dashboard/`** — React + Vite frontend (~60% of codebase JS/CSS/HTML).
  Currently polls the REST API.

- **`grafana/dashboards/oee-overview.json`** — Grafana dashboard reading
  directly from PostgreSQL.

---

## Your Task — Implement All 6 Upgrades

Implement every upgrade below **without breaking any existing functionality**.
Do not remove any existing endpoint, env variable, or table column. Only add
new things on top.

---

## UPGRADE 1 — Multi-Machine Support

### 1A. Modify `Producer.py`

Replace the hardcoded single-machine loop with a multi-machine simulation.

- Read a machine list from env var `MACHINE_IDS` (comma-separated string,
  default `"M1_MILL,M2_MAC_SIM,M3_LATHE,M4_PRESS,M5_WELD"`).
- Parse it into a Python list: `machines = os.getenv("MACHINE_IDS",
  "M1_MILL,M2_MAC_SIM,M3_LATHE,M4_PRESS,M5_WELD").split(",")`.
- In the main `while True` loop, iterate over all machines and produce one
  message per machine per iteration (so all machines emit every 2 seconds).
- Use `machine_id` as the Kafka message **key** (encode as UTF-8 bytes) so
  Confluent routes the same machine to the same partition consistently.
- Each machine should have slightly different random ranges to simulate
  real variance. Use a `MACHINE_PROFILES` dict:

```python
MACHINE_PROFILES = {
    "M1_MILL":    {"avail": (80, 95), "perf": (75, 98), "qual": (85, 100)},
    "M2_MAC_SIM": {"avail": (70, 95), "perf": (70, 98), "qual": (80, 100)},
    "M3_LATHE":   {"avail": (60, 90), "perf": (65, 95), "qual": (78,  99)},
    "M4_PRESS":   {"avail": (85, 98), "perf": (80, 99), "qual": (90, 100)},
    "M5_WELD":    {"avail": (55, 88), "perf": (60, 92), "qual": (75,  98)},
}
```

For any machine not in `MACHINE_PROFILES`, fall back to `(70, 95)` ranges.

- Keep all existing `.env` loading and Kafka config logic unchanged.
- Add a `message_id` field (UUID4 string) to each message for idempotency
  tracking.

### 1B. Add `MACHINE_IDS` to `.env.example`

```
MACHINE_IDS=M1_MILL,M2_MAC_SIM,M3_LATHE,M4_PRESS,M5_WELD
```

---

## UPGRADE 2 — Schema Validation + Dead Letter Queue (DLQ)

### 2A. Create `schema/oee_message_schema.json`

Define a strict JSON Schema (draft-07) for the OEE message:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OEEMessage",
  "type": "object",
  "required": ["machine_id", "availability", "performance", "quality",
               "timestamp", "oee", "message_id"],
  "additionalProperties": false,
  "properties": {
    "machine_id":    { "type": "string", "minLength": 1, "maxLength": 64 },
    "availability":  { "type": "number", "minimum": 0, "maximum": 100 },
    "performance":   { "type": "number", "minimum": 0, "maximum": 100 },
    "quality":       { "type": "number", "minimum": 0, "maximum": 100 },
    "oee":           { "type": "number", "minimum": 0, "maximum": 100 },
    "timestamp":     { "type": "number", "minimum": 0 },
    "message_id":    { "type": "string", "format": "uuid" }
  }
}
```

### 2B. Create `schema_validator.py`

A standalone module that validates a raw JSON bytes/string message against
`schema/oee_message_schema.json`. Requirements:

- Import `jsonschema` (add to `requirements.txt`).
- Load the schema once at module import time (cache it).
- Expose a single function: `validate_message(raw: bytes) -> dict` that:
  - Decodes bytes as UTF-8.
  - Parses JSON.
  - Validates against the schema.
  - Returns the parsed dict on success.
  - Raises `SchemaValidationError(message: str, raw: bytes)` on any failure
    (JSON parse error, schema violation, or decode error).
- Define `SchemaValidationError` as a custom exception in the same file.

### 2C. Create `dlq_producer.py`

A module that produces failed messages to a DLQ Kafka topic. Requirements:

- Read `DLQ_TOPIC` from env (default `"OEE_0_DLQ"`).
- Reuse the same Confluent Kafka config (bootstrap servers, SASL/SSL) from
  env vars.
- Expose `send_to_dlq(raw: bytes, reason: str, source_topic: str)` which
  produces a JSON envelope:
  ```json
  {
    "original_message": "<raw bytes decoded as UTF-8, or base64 if not decodable>",
    "failure_reason": "<reason string>",
    "source_topic": "<topic name>",
    "failed_at": "<ISO-8601 UTC timestamp>"
  }
  ```
- Use a persistent producer instance (module-level singleton). Flush on
  `atexit`.

### 2D. Modify `spark_oee_stream.py` to use schema validation

In the `write_to_postgres` `foreachBatch` function, before inserting rows,
check that each row's `machine_id` is a non-empty string and `avg_oee` is
between 0 and 100. If not, skip the row and log a warning. This is a
secondary guard — primary validation happens at the producer side.

> **Note on Confluent Schema Registry vs local validation:** Confluent Schema
> Registry requires a paid plan for the hosted version. To keep this
> completely free, implement schema validation **client-side** in
> `Producer.py` (validate before producing) and add a separate
> `validator_consumer.py` service (see 2E) that reads OEE_0 and acts as
> the Schema Registry equivalent.

### 2E. Create `validator_consumer.py`

A Kafka consumer that runs as a separate process, acts as the Schema Registry
equivalent, and feeds the DLQ:

- Subscribe to `OEE_0`.
- For each message:
  - Call `validate_message(raw)` from `schema_validator.py`.
  - On success: log `[VALID] machine_id=... message_id=...`.
  - On `SchemaValidationError`: call `send_to_dlq(raw, reason, "OEE_0")`,
    log `[DLQ] reason=...`.
- Use a dedicated consumer group `oee-schema-validator`.
- Respect KAFKA env vars for Confluent Cloud SASL/SSL.
- Handle graceful shutdown on `KeyboardInterrupt`.

### 2F. Create the DLQ topic

Add a shell script `scripts/create_topics.sh` that uses the Confluent CLI to
create both `OEE_0` (if not exists) and `OEE_0_DLQ`:

```bash
#!/usr/bin/env bash
confluent kafka topic create OEE_0       --partitions 5 --if-not-exists
confluent kafka topic create OEE_0_DLQ   --partitions 1 --if-not-exists
confluent kafka topic create OEE_ALERTS  --partitions 1 --if-not-exists
```

### 2G. Add `MACHINE_IDS` and `DLQ_TOPIC` to `.env.example`

```
DLQ_TOPIC=OEE_0_DLQ
ALERT_TOPIC=OEE_ALERTS
```

---

## UPGRADE 3 — Real-Time Alert Engine

### 3A. Add `alerts` table to `db/init_oee_schema.sql`

Append (do not replace) this SQL:

```sql
CREATE TABLE IF NOT EXISTS oee_alerts (
    id          BIGSERIAL PRIMARY KEY,
    machine_id  TEXT NOT NULL,
    avg_oee     DOUBLE PRECISION NOT NULL,
    threshold   DOUBLE PRECISION NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end   TIMESTAMP NOT NULL,
    alert_level TEXT NOT NULL,        -- 'WARNING' or 'CRITICAL'
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oee_alerts_machine_time
    ON oee_alerts (machine_id, window_start);
CREATE INDEX IF NOT EXISTS idx_oee_alerts_unacked
    ON oee_alerts (acknowledged) WHERE acknowledged = FALSE;
```

### 3B. Modify `spark_oee_stream.py` — add alert branch inside `foreachBatch`

Inside the existing `write_to_postgres` function, after writing to `oee_data`,
add the following alert logic. Read thresholds from env:

```python
OEE_WARNING_THRESHOLD  = float(os.getenv("OEE_WARNING_THRESHOLD",  "70.0"))
OEE_CRITICAL_THRESHOLD = float(os.getenv("OEE_CRITICAL_THRESHOLD", "55.0"))
```

For each row where `row.avg_oee` is below `OEE_WARNING_THRESHOLD`:
- Determine `alert_level`: `"CRITICAL"` if below `OEE_CRITICAL_THRESHOLD`,
  else `"WARNING"`.
- Insert into `oee_alerts` table using the same `conn`/`cursor`.
- Produce an alert message to Kafka topic `ALERT_TOPIC`
  (env var, default `"OEE_ALERTS"`) using a lightweight Confluent producer
  (use `confluent_kafka.Producer`, not PySpark). Message payload:
  ```json
  {
    "machine_id": "...",
    "avg_oee": 52.3,
    "threshold": 55.0,
    "alert_level": "CRITICAL",
    "window_start": "2024-01-01T10:00:00",
    "window_end": "2024-01-01T10:01:00",
    "alert_id": "<UUID4>"
  }
  ```
- Initialize the alert Kafka producer once at module level (not inside
  `foreachBatch`). Call `alert_producer.poll(0)` after each produce.

### 3C. Create `alert_consumer.py`

A standalone process that consumes `OEE_ALERTS` and dispatches notifications:

- Subscribe to `OEE_ALERTS` with group `oee-alert-dispatcher`.
- For each alert message, support three configurable notification channels
  (all optional, enabled by env vars):
  1. **Console** (always on): print a colored log line using ANSI codes.
     Red for CRITICAL, Yellow for WARNING.
  2. **Webhook** (if `ALERT_WEBHOOK_URL` is set): POST the alert JSON to
     that URL using `httpx` (async-safe, or use `requests`).
  3. **Email** (if `ALERT_EMAIL_TO` and `SMTP_HOST` are set): send a plain
     text email using `smtplib` with subject
     `[OEE ALERT] {alert_level} — {machine_id} @ {avg_oee:.1f}%`.
- Graceful shutdown on `KeyboardInterrupt`.

### 3D. Add alert env vars to `.env.example`

```
OEE_WARNING_THRESHOLD=70.0
OEE_CRITICAL_THRESHOLD=55.0
ALERT_TOPIC=OEE_ALERTS
ALERT_WEBHOOK_URL=
ALERT_EMAIL_TO=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
```

---

## UPGRADE 4 — Data Lake with MinIO (Free, Local, S3-Compatible)

Use **MinIO** as the data lake. It is completely free, runs locally in Docker,
and exposes a 100% S3-compatible API — no AWS account needed. Raw OEE events
are written as Parquet files partitioned by date and hour.

### 4A. Create `docker-compose.yml` (or add MinIO service to existing one)

```yaml
version: "3.9"
services:
  minio:
    image: minio/minio:latest
    container_name: oee_minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin123}
    ports:
      - "9000:9000"   # S3 API endpoint
      - "9001:9001"   # MinIO web console
    volumes:
      - minio_data:/data

volumes:
  minio_data:
```

### 4B. Create `scripts/init_minio_bucket.py`

A one-time setup script that creates the `oee-datalake` bucket in MinIO:

```python
import boto3, os
s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
)
bucket = os.getenv("DATALAKE_BUCKET", "oee-datalake")
existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
if bucket not in existing:
    s3.create_bucket(Bucket=bucket)
    print(f"Created bucket: {bucket}")
else:
    print(f"Bucket already exists: {bucket}")
```

### 4C. Modify `spark_oee_stream.py` — add raw-event Parquet sink

This is a **second streaming query** running in parallel to the existing
PostgreSQL sink. It reads the same `parsed` DataFrame (the raw per-event
stream, not the windowed aggregates) and writes to MinIO as Parquet.

Add after the existing `windowed` query definition:

```python
DATALAKE_ENABLED = os.getenv("DATALAKE_ENABLED", "true").lower() == "true"
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
DATALAKE_BUCKET  = os.getenv("DATALAKE_BUCKET",  "oee-datalake")

if DATALAKE_ENABLED:
    spark._jsc.hadoopConfiguration().set(
        "fs.s3a.endpoint", MINIO_ENDPOINT)
    spark._jsc.hadoopConfiguration().set(
        "fs.s3a.access.key", MINIO_ACCESS_KEY)
    spark._jsc.hadoopConfiguration().set(
        "fs.s3a.secret.key", MINIO_SECRET_KEY)
    spark._jsc.hadoopConfiguration().set(
        "fs.s3a.path.style.access", "true")
    spark._jsc.hadoopConfiguration().set(
        "fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")

    from pyspark.sql.functions import year, month, dayofmonth, hour

    datalake_df = parsed.withColumn("year",  year("event_time")) \
                        .withColumn("month", month("event_time")) \
                        .withColumn("day",   dayofmonth("event_time")) \
                        .withColumn("hour",  hour("event_time"))

    datalake_query = datalake_df.writeStream \
        .outputMode("append") \
        .format("parquet") \
        .option("path", f"s3a://{DATALAKE_BUCKET}/raw/oee_events/") \
        .option("checkpointLocation", f"s3a://{DATALAKE_BUCKET}/checkpoints/raw/") \
        .partitionBy("year", "month", "day", "hour") \
        .trigger(processingTime="30 seconds") \
        .start()
```

Add `SPARK_EXTRA_PACKAGES` in `.env.example` with the Hadoop AWS connector:

```
SPARK_EXTRA_PACKAGES=org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262
```

### 4D. Add datalake env vars to `.env.example`

```
DATALAKE_ENABLED=true
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
DATALAKE_BUCKET=oee-datalake
```

### 4E. Add MinIO browse endpoint to `api.py`

```python
@app.get("/api/datalake/partitions")
def list_datalake_partitions(token: str = Depends(require_auth)):
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    )
    bucket = os.getenv("DATALAKE_BUCKET", "oee-datalake")
    result = s3.list_objects_v2(Bucket=bucket, Prefix="raw/oee_events/",
                                Delimiter="/")
    prefixes = [p["Prefix"] for p in result.get("CommonPrefixes", [])]
    return {"partitions": prefixes}
```

---

## UPGRADE 5 — JWT Authentication

### 5A. Create `auth.py`

A standalone auth module used by `api.py`. Requirements:

- Dependencies: `python-jose[cryptography]`, `passlib[bcrypt]` (add to
  `requirements.txt`).
- Read `JWT_SECRET_KEY` from env (raise `RuntimeError` if missing in
  production — if `APP_ENV=production`).
- Read `JWT_ALGORITHM` (default `"HS256"`), `JWT_EXPIRE_MINUTES` (default
  `60`).
- Implement these functions:

```python
def hash_password(plain: str) -> str: ...
def verify_password(plain: str, hashed: str) -> bool: ...
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str: ...
def decode_access_token(token: str) -> dict: ...
    # raises HTTPException(401) on expired or invalid token
```

- Define a Pydantic model `TokenData(username: str)`.

### 5B. Create `db/users_schema.sql`

SQL to create a `users` table for storing API credentials:

```sql
CREATE TABLE IF NOT EXISTS api_users (
    id           BIGSERIAL PRIMARY KEY,
    username     TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer',  -- 'viewer' | 'admin'
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### 5C. Create `scripts/create_api_user.py`

A CLI helper script to create users manually:

```python
# Usage: python scripts/create_api_user.py --username admin --password secret --role admin
import argparse, psycopg2, os, sys
sys.path.insert(0, ".")
from auth import hash_password
# parse args, connect to pg, insert row, print success
```

### 5D. Modify `api.py` — add auth endpoints + protect all existing routes

Add these imports at the top:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from auth import verify_password, create_access_token, decode_access_token
from pydantic import BaseModel
```

Add these models:

```python
class Token(BaseModel):
    access_token: str
    token_type: str

class UserInfo(BaseModel):
    username: str
    role: str
```

Add a dependency function:

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def require_auth(token: str = Depends(oauth2_scheme)) -> dict:
    return decode_access_token(token)

def require_admin(token: dict = Depends(require_auth)) -> dict:
    if token.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return token
```

Add these new endpoints:

```python
@app.post("/api/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends()):
    # look up user from api_users table
    # verify password with verify_password()
    # return create_access_token({"sub": username, "role": role})

@app.get("/api/auth/me", response_model=UserInfo)
def me(token: dict = Depends(require_auth)):
    return {"username": token["sub"], "role": token.get("role", "viewer")}
```

Protect **all existing endpoints** by adding
`token: dict = Depends(require_auth)` as a parameter. Do NOT break the
existing query parameters — just add the dependency alongside them.

Example diff for `get_machines`:
```python
# Before
@app.get("/api/machines")
def get_machines():

# After
@app.get("/api/machines")
def get_machines(token: dict = Depends(require_auth)):
```

Apply the same pattern to `/api/oee/latest`, `/api/oee/history`,
`/api/oee/stats`.

### 5E. Add auth env vars to `.env.example`

```
JWT_SECRET_KEY=CHANGE_ME_USE_OPENSSL_RAND_HEX_32
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
APP_ENV=development
```

---

## UPGRADE 6 — WebSocket Server (Live Push to Frontend)

### 6A. Modify `api.py` — add WebSocket broadcast infrastructure

Add these imports:

```python
from fastapi import WebSocket, WebSocketDisconnect
import asyncio, json
from typing import Set
```

Add a `ConnectionManager` class **above** the FastAPI app instantiation:

```python
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, payload: dict):
        dead = set()
        for ws in self.active:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self.active -= dead

manager = ConnectionManager()
```

### 6B. Add WebSocket endpoint to `api.py`

```python
@app.websocket("/ws/oee")
async def websocket_oee(websocket: WebSocket):
    """
    Authenticated WebSocket endpoint.
    Client must send {"token": "<jwt>"} as the first message after connecting.
    After auth, the server pushes OEE updates every PUSH_INTERVAL_SECONDS.
    """
    await websocket.accept()
    try:
        # Step 1: Wait for auth message (timeout 10s)
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return

        token_str = auth_msg.get("token", "")
        try:
            token_data = decode_access_token(token_str)
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

        manager.active.add(websocket)

        # Step 2: Push loop
        PUSH_INTERVAL = float(os.getenv("WS_PUSH_INTERVAL_SECONDS", "5"))
        while True:
            await asyncio.sleep(PUSH_INTERVAL)
            conn = get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT DISTINCT ON (machine_id)
                    machine_id, window_start, window_end, avg_oee
                FROM oee_data
                ORDER BY machine_id, window_end DESC;
            """)
            rows = [dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()

            # Convert datetime objects to ISO strings
            for r in rows:
                r["window_start"] = r["window_start"].isoformat()
                r["window_end"]   = r["window_end"].isoformat()

            await websocket.send_json({
                "type": "oee_update",
                "data": rows,
                "pushed_at": __import__("datetime").datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

### 6C. Add `/ws/alerts` WebSocket for live alert streaming

```python
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    Pushes unacknowledged alerts. Same JWT auth flow as /ws/oee.
    """
    await websocket.accept()
    try:
        auth_msg  = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        token_str = auth_msg.get("token", "")
        try:
            decode_access_token(token_str)
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

        PUSH_INTERVAL = float(os.getenv("WS_PUSH_INTERVAL_SECONDS", "5"))
        while True:
            await asyncio.sleep(PUSH_INTERVAL)
            conn = get_conn()
            cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, machine_id, avg_oee, threshold,
                       alert_level, window_start, window_end, created_at
                FROM oee_alerts
                WHERE acknowledged = FALSE
                ORDER BY created_at DESC
                LIMIT 50;
            """)
            alerts = [dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()

            for a in alerts:
                a["window_start"] = a["window_start"].isoformat()
                a["window_end"]   = a["window_end"].isoformat()
                a["created_at"]   = a["created_at"].isoformat()

            await websocket.send_json({"type": "alerts_update", "data": alerts})

    except WebSocketDisconnect:
        pass
```

### 6D. Add alert acknowledge endpoint

```python
@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, token: dict = Depends(require_auth)):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE oee_alerts SET acknowledged = TRUE WHERE id = %s;",
        (alert_id,)
    )
    conn.commit(); cur.close(); conn.close()
    return {"acknowledged": True, "alert_id": alert_id}

@app.get("/api/alerts")
def get_alerts(
    machine: str = Query(None),
    unacked_only: bool = Query(False),
    limit: int = Query(50),
    token: dict = Depends(require_auth),
):
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    clauses = []
    params  = []
    if machine:
        clauses.append("machine_id = %s");  params.append(machine)
    if unacked_only:
        clauses.append("acknowledged = FALSE")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(f"""
        SELECT id, machine_id, avg_oee, threshold, alert_level,
               window_start, window_end, acknowledged, created_at
        FROM oee_alerts {where}
        ORDER BY created_at DESC LIMIT %s;
    """, params + [limit])
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows
```

### 6E. Add WebSocket env var to `.env.example`

```
WS_PUSH_INTERVAL_SECONDS=5
```

---

## UPGRADE 7 — React Frontend WebSocket Integration (in `oee-dashboard/`)

Update the React frontend to use the new WebSocket and auth endpoints. Do NOT
rewrite the dashboard from scratch — add on top of what exists.

### 7A. Create `oee-dashboard/src/api/auth.js`

```js
const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function login(username, password) {
  const form = new URLSearchParams({ username, password });
  const res = await fetch(`${BASE}/api/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) throw new Error("Login failed");
  const data = await res.json();
  localStorage.setItem("oee_token", data.access_token);
  return data.access_token;
}

export function getToken() {
  return localStorage.getItem("oee_token");
}

export function logout() {
  localStorage.removeItem("oee_token");
}

export function authHeader() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
```

### 7B. Create `oee-dashboard/src/hooks/useOeeWebSocket.js`

```js
import { useEffect, useRef, useState } from "react";
import { getToken } from "../api/auth";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";

export function useOeeWebSocket() {
  const [oeeData, setOeeData]     = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/oee`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token: getToken() }));
      setConnected(true);
    };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "oee_update") setOeeData(msg.data);
    };

    ws.onclose  = () => setConnected(false);
    ws.onerror  = () => setConnected(false);

    return () => ws.close();
  }, []);

  return { oeeData, connected };
}
```

### 7C. Create `oee-dashboard/src/hooks/useAlertsWebSocket.js`

Mirror of `useOeeWebSocket` but connects to `/ws/alerts` and returns
`{ alerts, connected }`.

### 7D. Update `oee-dashboard/.env.example` (or create it if missing)

```
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

---

## Final File Structure After All Upgrades

```
BMP_OEE_Project/
├── Producer.py                      ← MODIFIED (multi-machine, message_id)
├── spark_oee_stream.py              ← MODIFIED (alerts branch + MinIO sink)
├── api.py                           ← MODIFIED (JWT, WebSocket, alerts)
├── auth.py                          ← NEW
├── schema_validator.py              ← NEW
├── dlq_producer.py                  ← NEW
├── validator_consumer.py            ← NEW
├── alert_consumer.py                ← NEW
├── schema/
│   └── oee_message_schema.json      ← NEW
├── db/
│   ├── init_oee_schema.sql          ← MODIFIED (adds oee_alerts table)
│   └── users_schema.sql             ← NEW
├── scripts/
│   ├── create_topics.sh             ← NEW
│   ├── init_minio_bucket.py         ← NEW
│   └── create_api_user.py           ← NEW
├── docker-compose.yml               ← NEW (MinIO service)
├── requirements.txt                 ← MODIFIED (new deps listed below)
├── .env.example                     ← MODIFIED (all new env vars)
├── oee-dashboard/
│   ├── src/
│   │   ├── api/auth.js              ← NEW
│   │   └── hooks/
│   │       ├── useOeeWebSocket.js   ← NEW
│   │       └── useAlertsWebSocket.js← NEW
│   └── .env.example                 ← NEW/MODIFIED
├── grafana/dashboards/
│   └── oee-overview.json            ← unchanged
└── ccloud-python-client/            ← unchanged
```

---

## `requirements.txt` — Full List (new additions)

Add these packages (keep whatever is already in requirements.txt):

```
# Existing (keep)
confluent-kafka
pyspark
psycopg2-binary
fastapi
uvicorn[standard]

# New
jsonschema>=4.21.0          # schema validation
python-jose[cryptography]   # JWT
passlib[bcrypt]             # password hashing
python-multipart            # FastAPI OAuth2 form parsing
boto3>=1.34.0               # MinIO / S3 client
httpx>=0.27.0               # alert webhook HTTP client
websockets>=12.0            # WebSocket support (uvicorn already bundles this)
```

---

## Critical Implementation Notes for Cursor

1. **Do not remove any existing code.** Every existing endpoint, function,
   and env var must still work after the changes.

2. **Connection reuse in `api.py`:** The existing `get_conn()` creates a new
   psycopg2 connection per call. This is fine for REST but will be called in
   a tight loop inside the WebSocket push handlers. Add a try/finally in
   the WebSocket handlers to ensure `conn.close()` is always called.

3. **`spark_oee_stream.py` Kafka producer for alerts:** The alert producer
   inside `spark_oee_stream.py` must be initialized at module level — not
   inside `foreachBatch` — because `foreachBatch` may run in a Spark
   executor context. Use a module-level `confluent_kafka.Producer` instance.
   Add a try/except so that alert producer failures never crash the main
   PostgreSQL write.

4. **MinIO Parquet sink uses Hadoop S3A connector.** The required JAR
   is loaded via `SPARK_EXTRA_PACKAGES`. If the JAR is not available,
   `DATALAKE_ENABLED=false` must disable the entire datalake query without
   error. Wrap the datalake query start in:
   ```python
   if DATALAKE_ENABLED:
       try:
           datalake_query = ...
       except Exception as e:
           print(f"[WARN] Datalake sink disabled: {e}")
   ```

5. **WebSocket and REST endpoints in the same FastAPI app** work fine with
   `uvicorn`. No separate server needed. Run with:
   `uvicorn api:app --host 0.0.0.0 --port 8000 --reload`

6. **JWT secret in `.env.example`** uses a placeholder. The `create_api_user.py`
   script should print a warning if `JWT_SECRET_KEY` is the default placeholder
   string `"CHANGE_ME_USE_OPENSSL_RAND_HEX_32"`.

7. **`validator_consumer.py` and `alert_consumer.py`** both run as separate
   Python processes. Add a `scripts/start_all.sh` that shows how to start
   all processes in separate terminals:
   ```bash
   # Terminal 1: IoT simulator
   python Producer.py
   # Terminal 2: Spark streaming (processing + datalake)
   python spark_oee_stream.py
   # Terminal 3: Schema validator / DLQ router
   python validator_consumer.py
   # Terminal 4: Alert dispatcher
   python alert_consumer.py
   # Terminal 5: API + WebSocket server
   uvicorn api:app --host 0.0.0.0 --port 8000 --reload
   # Terminal 6: React frontend
   cd oee-dashboard && npm run dev
   ```

8. **PostgreSQL async:** The current `api.py` uses synchronous `psycopg2`.
   The WebSocket push handlers use `asyncio.sleep`. Do NOT switch to
   `asyncpg` — keep `psycopg2` and use `asyncio.to_thread(get_conn)` inside
   the async WebSocket handlers to avoid blocking the event loop.
   Specifically replace each blocking DB call in the WS handlers with:
   ```python
   def _fetch_latest():
       conn = get_conn()
       ...
       conn.close()
       return rows

   rows = await asyncio.to_thread(_fetch_latest)
   ```

9. **CORS for WebSocket:** WebSocket connections are not subject to CORS in
   the browser security model, but add the React dev server origin to the
   FastAPI `CORSMiddleware` `allow_origins` list anyway for REST calls:
   `"http://localhost:5173"` is already present; also add
   `"http://localhost:5174"` as a fallback for Vite port conflicts.

10. **Schema validation in `Producer.py`:** After computing `data["oee"]`,
    call `validate_message(json.dumps(data).encode())`. If it raises
    `SchemaValidationError`, log the error and skip that machine's message
    (do not call `send_to_dlq` from Producer — the DLQ is only written by
    `validator_consumer.py`).
