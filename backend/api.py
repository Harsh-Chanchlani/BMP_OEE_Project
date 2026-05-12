from fastapi import FastAPI, Query, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import os
import asyncio
import json
from datetime import datetime
from typing import Set, List, Optional
import boto3

def load_env_file(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

load_env_file()

import sys
sys.path.insert(0, os.path.dirname(__file__))
from auth import verify_password, create_access_token, decode_access_token

app = FastAPI(title="BMP OEE API")

# Update CORS for multiple origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DB Utility ---
def get_conn():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE", "oee_db"),
        user=os.getenv("PGUSER", "harshchanchlani"),
        password=os.getenv("PGPASSWORD", ""),
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
    )

# --- Auth Infrastructure ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

class Token(BaseModel):
    access_token: str
    token_type: str

class UserInfo(BaseModel):
    username: str
    role: str

def require_auth(token: str = Depends(oauth2_scheme)) -> dict:
    return decode_access_token(token)

def require_admin(token: dict = Depends(require_auth)) -> dict:
    if token.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return token

# --- WebSocket Infrastructure ---
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

# --- Auth Endpoints ---
class RegisterRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/register", status_code=201)
def register(req: RegisterRequest):
    from auth import hash_password
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO api_users (username, hashed_password, role) VALUES (%s, %s, 'viewer')",
            (req.username, hash_password(req.password))
        )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    finally:
        cur.close(); conn.close()
    return {"message": "User created successfully"}

@app.post("/api/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends()):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username, hashed_password, role FROM api_users WHERE username = %s AND is_active = TRUE", (form.username,))
    user = cur.fetchone()
    cur.close(); conn.close()

    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = create_access_token(data={"sub": user["username"], "role": user["role"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=UserInfo)
def me(token: dict = Depends(require_auth)):
    return {"username": token["sub"], "role": token.get("role", "viewer")}

# --- Protected REST Endpoints ---
@app.get("/api/machines")
def get_machines(token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT machine_id FROM oee_data ORDER BY machine_id;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [r[0] for r in rows]

@app.get("/api/oee/latest")
def get_latest(machine: str = Query(...), token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT machine_id, window_start, window_end, avg_oee
        FROM oee_data
        WHERE machine_id = %s
        ORDER BY window_end DESC
        LIMIT 1;
    """, (machine,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if row:
        row["window_start"] = row["window_start"].isoformat()
        row["window_end"] = row["window_end"].isoformat()
    return dict(row) if row else {}

@app.get("/api/oee/history")
def get_history(machine: str = Query(...), limit: int = 30, token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT machine_id, window_start, window_end, avg_oee
        FROM oee_data
        WHERE machine_id = %s
        ORDER BY window_start DESC
        LIMIT %s;
    """, (machine, limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    for r in rows:
        r["window_start"] = r["window_start"].isoformat()
        r["window_end"] = r["window_end"].isoformat()
    return [dict(r) for r in reversed(rows)]

@app.get("/api/oee/stats")
def get_stats(machine: str = Query(...), token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT
            AVG(avg_oee)  AS avg_oee,
            MIN(avg_oee)  AS min_oee,
            MAX(avg_oee)  AS max_oee,
            COUNT(*)      AS total_windows
        FROM oee_data
        WHERE machine_id = %s
          AND window_start >= NOW() - INTERVAL '24 hours';
    """, (machine,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else {}

@app.get("/api/datalake/partitions")
def list_datalake_partitions(token: str = Depends(require_auth)):
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    )
    bucket = os.getenv("DATALAKE_BUCKET", "oee-datalake")
    result = s3.list_objects_v2(Bucket=bucket, Prefix="raw/oee_events/", Delimiter="/")
    prefixes = [p["Prefix"] for p in result.get("CommonPrefixes", [])]
    return {"partitions": prefixes}

# --- Alerts REST Endpoints ---
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
    for r in rows:
        r["window_start"] = r["window_start"].isoformat()
        r["window_end"]   = r["window_end"].isoformat()
        r["created_at"]   = r["created_at"].isoformat()
    cur.close(); conn.close()
    return rows

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, token: dict = Depends(require_auth)):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("UPDATE oee_alerts SET acknowledged = TRUE WHERE id = %s;", (alert_id,))
    conn.commit(); cur.close(); conn.close()
    return {"acknowledged": True, "alert_id": alert_id}

# --- New Analytics Endpoints ---
@app.get("/api/oee/apq")
def get_apq(machine: Optional[str] = Query(None), limit: int = Query(30), token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if machine:
        cur.execute("""
            SELECT machine_id, window_start, window_end,
                   avg_availability, avg_performance, avg_quality
            FROM oee_data
            WHERE machine_id = %s
            ORDER BY window_start ASC
            LIMIT %s;
        """, (machine, limit))
    else:
        cur.execute("""
            SELECT DISTINCT ON (machine_id)
                machine_id, window_start, window_end,
                avg_availability, avg_performance, avg_quality
            FROM oee_data
            ORDER BY machine_id, window_end DESC;
        """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["window_start"] = r["window_start"].isoformat()
        r["window_end"]   = r["window_end"].isoformat()
    return rows

@app.get("/api/machines/compare")
def get_machines_compare(token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT DISTINCT ON (machine_id)
            machine_id, avg_oee, avg_availability, avg_performance, avg_quality, window_end
        FROM oee_data
        ORDER BY machine_id, window_end DESC;
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["window_end"] = r["window_end"].isoformat()
    rows.sort(key=lambda r: r["avg_oee"] if r["avg_oee"] is not None else 0)
    return rows

@app.get("/api/spc")
def get_spc(machine: Optional[str] = Query(None), token: dict = Depends(require_auth)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if machine:
        cur.execute("""
            SELECT machine_id, mean_value, std_dev, ucl, lcl, sample_size, calculated_at
            FROM spc_data
            WHERE machine_id = %s AND metric = 'oee'
            ORDER BY calculated_at DESC
            LIMIT 1;
        """, (machine,))
    else:
        cur.execute("""
            SELECT DISTINCT ON (machine_id)
                machine_id, mean_value, std_dev, ucl, lcl, sample_size, calculated_at
            FROM spc_data
            WHERE metric = 'oee'
            ORDER BY machine_id, calculated_at DESC;
        """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["calculated_at"] = r["calculated_at"].isoformat()
    return rows

@app.get("/api/shifts")
def get_shifts(
    machine: Optional[str] = Query(None),
    days: int = Query(7),
    token: dict = Depends(require_auth),
):
    days = min(days, 30)
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if machine:
        cur.execute("""
            SELECT machine_id, shift_date, shift, avg_oee, avg_availability,
                   avg_performance, avg_quality, min_oee, max_oee, data_points
            FROM shift_performance
            WHERE machine_id = %s
              AND shift_date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY shift_date DESC, shift ASC;
        """, (machine, days))
    else:
        cur.execute("""
            SELECT DISTINCT ON (machine_id, shift)
                machine_id, shift_date, shift, avg_oee, avg_availability,
                avg_performance, avg_quality, min_oee, max_oee, data_points
            FROM shift_performance
            WHERE shift_date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY machine_id, shift, shift_date DESC;
        """, (days,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["shift_date"] = r["shift_date"].isoformat()
    return rows

@app.get("/api/oee/forecast")
def get_forecast(machine: str = Query(...), token: dict = Depends(require_auth)):
    """
    Return the latest ARIMA forecast batch for a machine.
    Always returns the most recent prediction_time batch (10 steps).
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT target_time, predicted_oee, confidence_lower, confidence_upper,
               model_type, prediction_time
        FROM oee_predictions
        WHERE machine_id = %s
          AND prediction_time = (
              SELECT MAX(prediction_time)
              FROM oee_predictions
              WHERE machine_id = %s
          )
        ORDER BY target_time ASC;
    """, (machine, machine))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["target_time"]     = r["target_time"].isoformat()
        r["prediction_time"] = r["prediction_time"].isoformat()
    return rows


@app.get("/api/oee/forecast_vs_actual")
def get_forecast_vs_actual(machine: str = Query(...), token: dict = Depends(require_auth)):
    """
    For each historical prediction batch, find the actual OEE window that
    covers that target_time and return both values side by side.

    This powers the "predicted vs actual" comparison chart — you can see
    exactly where the forecast was right or wrong.

    Returns rows ordered by target_time with:
      - target_time: when the prediction was for
      - predicted_oee: what ARIMA said OEE would be
      - actual_oee: what oee_data actually recorded (null if no window yet)
      - confidence_lower / confidence_upper: 95% CI
      - prediction_time: when the forecast was made
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Join predictions against oee_data windows that contain the target_time.
    # Use the last 24h of predictions to keep the chart readable.
    cur.execute("""
        SELECT
            p.target_time,
            p.predicted_oee,
            p.confidence_lower,
            p.confidence_upper,
            p.prediction_time,
            d.avg_oee AS actual_oee,
            d.window_start,
            d.window_end
        FROM oee_predictions p
        LEFT JOIN oee_data d
            ON d.machine_id = p.machine_id
            AND p.target_time >= d.window_start
            AND p.target_time <  d.window_end
        WHERE p.machine_id = %s
          AND p.prediction_time >= NOW() - INTERVAL '24 hours'
        ORDER BY p.target_time ASC;
    """, (machine,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["target_time"]     = r["target_time"].isoformat()
        r["prediction_time"] = r["prediction_time"].isoformat()
        if r["window_start"]: r["window_start"] = r["window_start"].isoformat()
        if r["window_end"]:   r["window_end"]   = r["window_end"].isoformat()
    return rows

@app.get("/api/losses")
def get_losses(machine: Optional[str] = Query(None), token: dict = Depends(require_auth)):
    """
    Return aggregated loss data from the loss_categories table.
    Implements Kennedy's Time-Loss model (Chapter 3, Figure 3.4):
      - loss_minutes: total minutes lost per loss type (primary metric for Pareto)
      - total_loss_percentage: average loss % per loss type (secondary context)

    Kennedy emphasises that actionable improvement is driven by analysing
    actual TIME LOST, not just percentages. The Pareto chart should be sorted
    by minutes lost so teams focus on the biggest time consumers first.

    Returns rows with:
      - loss_type: one of the 7 Kennedy losses
      - loss_component: OEE component affected (availability/performance/quality)
      - loss_minutes: total minutes lost to this loss type in the last 24 hours
      - total_loss_percentage: average loss percentage for context
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if machine:
        cur.execute("""
            SELECT loss_type, loss_component,
                   SUM(loss_minutes)      AS loss_minutes,
                   AVG(loss_percentage)   AS total_loss_percentage
            FROM loss_categories
            WHERE machine_id = %s
              AND timestamp >= NOW() - INTERVAL '24 hours'
            GROUP BY loss_type, loss_component
            ORDER BY loss_minutes DESC;
        """, (machine,))
    else:
        cur.execute("""
            SELECT loss_type, loss_component,
                   SUM(loss_minutes)      AS loss_minutes,
                   AVG(loss_percentage)   AS total_loss_percentage
            FROM loss_categories
            WHERE timestamp >= NOW() - INTERVAL '24 hours'
            GROUP BY loss_type, loss_component
            ORDER BY loss_minutes DESC;
        """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    # Ensure numeric types are JSON-serialisable
    for r in rows:
        r["loss_minutes"]           = float(r["loss_minutes"] or 0)
        r["total_loss_percentage"]  = float(r["total_loss_percentage"] or 0)
    return rows

# --- WebSocket Endpoints ---
@app.websocket("/ws/oee")
async def websocket_oee(websocket: WebSocket):
    await websocket.accept()
    try:
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
            token_data = decode_access_token(auth_msg.get("token", ""))
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

        manager.active.add(websocket)
        PUSH_INTERVAL = float(os.getenv("WS_PUSH_INTERVAL_SECONDS", "5"))
        
        while True:
            await asyncio.sleep(PUSH_INTERVAL)
            
            def fetch_oee():
                conn = get_conn()
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT machine_id, window_start, window_end, avg_oee
                    FROM oee_data
                    WHERE window_start >= NOW() - INTERVAL '30 minutes'
                    ORDER BY machine_id, window_end ASC;
                """)
                rows = [dict(r) for r in cur.fetchall()]
                cur.close(); conn.close()
                for r in rows:
                    r["window_start"] = r["window_start"].isoformat()
                    r["window_end"]   = r["window_end"].isoformat()
                return rows

            rows = await asyncio.to_thread(fetch_oee)
            await websocket.send_json({
                "type": "oee_update",
                "data": rows,
                "pushed_at": datetime.utcnow().isoformat()
            })
    except (WebSocketDisconnect, asyncio.CancelledError):
        manager.disconnect(websocket)

@app.get("/api/oee/raw")
def get_raw_events(machine: str = Query(...), limit: int = Query(15), token: dict = Depends(require_auth)):
    """Return raw per-event OEE readings for a machine (most recent, up to limit)."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT machine_id, event_time, oee, availability, performance, quality,
               lot_id, loss_event_name, loss_event_component
        FROM oee_raw_events
        WHERE machine_id = %s
        ORDER BY event_time DESC
        LIMIT %s;
    """, (machine, limit))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    for r in rows:
        r["event_time"] = r["event_time"].isoformat()
    # Return in ascending order for charting
    return list(reversed(rows))


@app.websocket("/ws/oee_raw")
async def websocket_oee_raw(websocket: WebSocket):
    """Stream raw individual OEE events (last 30 min) for real-time per-event plotting."""
    await websocket.accept()
    try:
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
            decode_access_token(auth_msg.get("token", ""))
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

        PUSH_INTERVAL = float(os.getenv("WS_PUSH_INTERVAL_SECONDS", "5"))
        while True:
            await asyncio.sleep(PUSH_INTERVAL)

            def fetch_raw():
                conn = get_conn()
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT machine_id, event_time, oee, availability, performance, quality,
                           lot_id, loss_event_name, loss_event_component
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY event_time DESC) AS rn
                        FROM oee_raw_events
                    ) ranked
                    WHERE rn <= 15
                    ORDER BY machine_id, event_time ASC;
                """)
                rows = [dict(r) for r in cur.fetchall()]
                cur.close(); conn.close()
                for r in rows:
                    r["event_time"] = r["event_time"].isoformat()
                return rows

            rows = await asyncio.to_thread(fetch_raw)
            await websocket.send_json({
                "type": "oee_raw_update",
                "data": rows,
                "pushed_at": datetime.utcnow().isoformat()
            })
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await websocket.accept()
    try:
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
            decode_access_token(auth_msg.get("token", ""))
        except Exception:
            await websocket.close(code=4003, reason="Invalid token")
            return

        PUSH_INTERVAL = float(os.getenv("WS_PUSH_INTERVAL_SECONDS", "5"))
        while True:
            await asyncio.sleep(PUSH_INTERVAL)

            def fetch_alerts():
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
                return alerts

            alerts = await asyncio.to_thread(fetch_alerts)
            await websocket.send_json({"type": "alerts_update", "data": alerts})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
