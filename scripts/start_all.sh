#!/usr/bin/env bash
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
