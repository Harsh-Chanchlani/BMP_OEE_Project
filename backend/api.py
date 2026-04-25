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
                    SELECT DISTINCT ON (machine_id)
                        machine_id, window_start, window_end, avg_oee
                    FROM oee_data
                    ORDER BY machine_id, window_end DESC;
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
