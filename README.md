# OEE BMP Project

This project streams machine OEE data from Kafka, aggregates it in Spark Structured Streaming, stores it in PostgreSQL, and visualizes it in Grafana.

## Architecture

1. `Producer.py` publishes simulated OEE messages to Kafka topic `OEE_0` every 2 seconds.
2. `spark_oee_stream.py` reads the Kafka stream, parses JSON, computes 1-minute window averages (`avg_oee`) per machine, and writes to PostgreSQL table `oee_data`.
3. Grafana reads `oee_data` from PostgreSQL and shows live OEE dashboards.

## Data Shape

Kafka message fields:
- `machine_id`
- `availability`
- `performance`
- `quality`
- `timestamp` (unix seconds)
- `oee`

Spark output table columns:
- `machine_id`
- `window_start`
- `window_end`
- `avg_oee`

## 1) Prepare Environment

Create a `.env` file from `.env.example` and set your real values.

```bash
cp .env.example .env
```

## 2) Create PostgreSQL Table

Run the schema script once:

```bash
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -f db/init_oee_schema.sql
```

Note: `spark_oee_stream.py` also creates this table automatically if it does not exist.

## 3) Start Data Pipeline

In terminal 1:

```bash
source venv/bin/activate
set -a; source .env; set +a
python Producer.py
```

In terminal 2:

```bash
source venv/bin/activate
set -a; source .env; set +a
python spark_oee_stream.py
```

## 4) Start Grafana (No Docker)

Install and run Grafana locally on macOS:

```bash
brew install grafana
brew services start grafana
```

Open `http://localhost:3000` and login with default credentials:
- user: `admin`
- password: `admin`

After first login, configure datasource and dashboard:

1. Add PostgreSQL datasource:
	- Connections -> Add new connection -> PostgreSQL
	- Host URL: `localhost:5432`
	- Database: `oee_db`
	- User: your local PostgreSQL user (example: `harshchanchlani`)
	- Password: your PostgreSQL password (if any)
	- SSL mode: `disable`
2. Import dashboard JSON:
	- Dashboards -> New -> Import
	- Upload file: `grafana/dashboards/oee-overview.json`
	- Select your PostgreSQL datasource when prompted

## Dashboard Panels

- Latest OEE (stat)
- 15-min Avg OEE (stat)
- OEE Trend (time series)
- Recent Window Aggregates (table)

## Spark Kafka Connector Note

`spark_oee_stream.py` auto-loads the Spark Kafka connector package based on your installed PySpark version.

If you need to override package coordinates manually, set:
- `SPARK_SCALA_BINARY_VERSION` (default `2.13`)
- `SPARK_KAFKA_PACKAGE` (example: `org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1`)

## Stop Grafana

```bash
brew services stop grafana
```
