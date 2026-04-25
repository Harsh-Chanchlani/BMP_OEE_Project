#!/usr/bin/env bash

# macOS-optimized backend startup script
# Simple, fast, and Mac-friendly

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/venv"
LOG_DIR="$PROJECT_ROOT/logs"

# Create logs directory
mkdir -p "$LOG_DIR"

# Activate virtual environment
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
else
    echo "❌ Virtual environment not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   OEE Backend - macOS Startup${NC}        ${BLUE}║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Stopping all services...${NC}"
    kill $PRODUCER_PID $SPARK_PID $API_PID 2>/dev/null || true
    echo -e "${GREEN}✅ All services stopped${NC}"
    echo ""
}

trap cleanup EXIT INT TERM

# Start Producer
echo -e "${GREEN}📊 Starting Producer...${NC}"
python "$PROJECT_ROOT/producer/Producer.py" > "$LOG_DIR/producer.log" 2>&1 &
PRODUCER_PID=$!
sleep 2

# Start Spark Processor
echo -e "${GREEN}⚡ Starting Spark Processor...${NC}"
python "$PROJECT_ROOT/backend/spark_oee_stream.py" > "$LOG_DIR/spark_processor.log" 2>&1 &
SPARK_PID=$!
sleep 3

# Start API Server
echo -e "${GREEN}🔌 Starting API Server...${NC}"
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload > "$LOG_DIR/api_server.log" 2>&1 &
API_PID=$!
sleep 2

echo ""
echo -e "${GREEN}✅ All services started!${NC}"
echo ""
echo -e "${BLUE}Services running:${NC}"
echo -e "  ${GREEN}•${NC} Producer (PID: $PRODUCER_PID)"
echo -e "  ${GREEN}•${NC} Spark Processor (PID: $SPARK_PID)"
echo -e "  ${GREEN}•${NC} API Server (PID: $API_PID) → ${BLUE}http://localhost:8000${NC}"
echo ""
echo -e "${BLUE}View logs:${NC}"
echo -e "  tail -f logs/producer.log"
echo -e "  tail -f logs/spark_processor.log"
echo -e "  tail -f logs/api_server.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Keep script running
wait
