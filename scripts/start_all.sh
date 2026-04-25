#!/usr/bin/env bash
# Run each in a separate terminal from the project root

# Terminal 1: IoT simulator / producer
python producer/Producer.py

# Terminal 2: Spark structured streaming (windowed aggregation → Postgres + alerts)
python backend/spark_oee_stream.py

# Terminal 3: Schema validator / DLQ router
python backend/validator_consumer.py

# Terminal 4: Alert dispatcher (email / webhook)
python backend/alert_consumer.py

# Terminal 5: FastAPI + WebSocket server
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 6: React frontend
cd oee-dashboard && npm run dev
