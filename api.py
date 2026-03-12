from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import os

app = FastAPI()

# Allow React dev server to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE", "oee_db"),
        user=os.getenv("PGUSER", "harshchanchlani"),
        password=os.getenv("PGPASSWORD", ""),
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
    )

@app.get("/api/machines")
def get_machines():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT machine_id FROM oee_data ORDER BY machine_id;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [r[0] for r in rows]

@app.get("/api/oee/latest")
def get_latest(machine: str = Query(...)):
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
    return dict(row) if row else {}

@app.get("/api/oee/history")
def get_history(machine: str = Query(...), limit: int = 30):
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
    # Reverse so oldest → newest for chart
    return [dict(r) for r in reversed(rows)]

@app.get("/api/oee/stats")
def get_stats(machine: str = Query(...)):
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
          AND window_start >= NOW() - INTERVAL '15 minutes';
    """, (machine,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else {}
