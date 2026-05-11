#!/usr/bin/env bash

# macOS backend startup script
# Starts: Producer, Spark Processor, ARIMA Forecaster, API Server

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/venv"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
else
    echo "❌ Virtual environment not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        OEE Backend — macOS             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Stopping all services...${NC}"
    kill $PRODUCER_PID $SPARK_PID $ARIMA_PID $API_PID 2>/dev/null || true
    echo -e "${GREEN}✅ All services stopped${NC}"
}
trap cleanup EXIT INT TERM

# ── Producer ──────────────────────────────────────────────────────────────────
# Logs only errors + a summary line every 50 cycles (~25 s).
# The old per-message logging filled logs/producer.log with 8000+ lines.
echo -e "${GREEN}📊 Starting Producer...${NC}"
python "$PROJECT_ROOT/producer/Producer.py" >> "$LOG_DIR/producer.log" 2>&1 &
PRODUCER_PID=$!
sleep 2

# ── Spark Processor ───────────────────────────────────────────────────────────
# Stream A (raw events): triggers every 3 s — keeps real-time chart fresh.
# Stream B (windowed):   triggers every 10 s — computes 1-min rolling averages.
echo -e "${GREEN}⚡ Starting Spark Processor...${NC}"
python "$PROJECT_ROOT/backend/spark_oee_stream.py" >> "$LOG_DIR/spark_processor.log" 2>&1 &
SPARK_PID=$!
sleep 3

# ── ARIMA Forecaster ──────────────────────────────────────────────────────────
# Runs every 60 s. Fits ARIMA per machine on last 200 raw readings.
# Writes predictions to oee_predictions table.
# Requires: pip install pmdarima
echo -e "${GREEN}🔮 Starting ARIMA Forecaster...${NC}"
python "$PROJECT_ROOT/backend/arima_forecaster.py" >> "$LOG_DIR/arima_forecaster.log" 2>&1 &
ARIMA_PID=$!
sleep 1

# ── API Server ────────────────────────────────────────────────────────────────
echo -e "${GREEN}🔌 Starting API Server...${NC}"
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload >> "$LOG_DIR/api_server.log" 2>&1 &
API_PID=$!
sleep 2

echo ""
echo -e "${GREEN}✅ All services started!${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo -e "  ${GREEN}•${NC} Producer         (PID: $PRODUCER_PID)  → logs/producer.log"
echo -e "  ${GREEN}•${NC} Spark Processor  (PID: $SPARK_PID)     → logs/spark_processor.log"
echo -e "  ${GREEN}•${NC} ARIMA Forecaster (PID: $ARIMA_PID)     → logs/arima_forecaster.log"
echo -e "  ${GREEN}•${NC} API Server       (PID: $API_PID)       → http://localhost:8000"
echo ""
echo -e "${BLUE}Useful log tails:${NC}"
echo -e "  tail -f logs/producer.log"
echo -e "  tail -f logs/spark_processor.log"
echo -e "  tail -f logs/arima_forecaster.log"
echo -e "  tail -f logs/api_server.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

wait
