#!/usr/bin/env python3
"""
Simple backend startup script
Runs: Producer, Spark Processor, and FastAPI
"""

import subprocess
import sys
import os
import signal
import time

processes = []

def signal_handler(sig, frame):
    print("\n\n🛑 Stopping all services...")
    for p in processes:
        try:
            p.terminate()
            p.wait(timeout=5)
        except:
            p.kill()
    print("✅ All services stopped")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Get project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(project_root)

# Activate venv
venv_activate = f"source venv/bin/activate && " if os.path.exists("venv") else ""

print("🚀 Starting OEE Backend...\n")

# Start Producer
print("📊 Starting Producer...")
p1 = subprocess.Popen(f"{venv_activate}python producer/Producer.py", shell=True)
processes.append(p1)
time.sleep(2)

# Start Spark Processor
print("⚡ Starting Spark Processor...")
p2 = subprocess.Popen(f"{venv_activate}python backend/spark_oee_stream.py", shell=True)
processes.append(p2)
time.sleep(3)

# Start API Server
print("🔌 Starting API Server (http://localhost:8000)...\n")
p3 = subprocess.Popen(f"{venv_activate}uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload", shell=True)
processes.append(p3)

print("✅ All services started!")
print("Press Ctrl+C to stop\n")

# Keep running
for p in processes:
    p.wait()
