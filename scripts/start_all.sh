#!/usr/bin/env bash
# Simple backend startup script

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "🚀 Starting OEE Backend..."
echo ""

# Start Producer
echo "📊 Starting Producer..."
python producer/Producer.py &
PRODUCER_PID=$!
sleep 2

# Start Spark Processor
echo "⚡ Starting Spark Processor..."
python backend/spark_oee_stream.py &
SPARK_PID=$!
sleep 3

# Start API Server
echo "🔌 Starting API Server (http://localhost:8000)..."
echo ""
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

echo "✅ All services started!"
echo "Press Ctrl+C to stop"
echo ""

# Handle Ctrl+C
trap "kill $PRODUCER_PID $SPARK_PID $API_PID 2>/dev/null; echo ''; echo '🛑 All services stopped'; exit 0" INT

# Wait for all processes
wait
