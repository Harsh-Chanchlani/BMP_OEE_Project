from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, window, avg, from_unixtime, year, month, dayofmonth, hour
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
import pyspark
import psycopg2
import os
import json
import uuid
from datetime import datetime
from confluent_kafka import Producer as ConfluentProducer

def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

def load_kafka_properties(path):
    if not os.path.exists(path):
        return
    props = {}
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    mapping = {
        "bootstrap.servers": "KAFKA_BOOTSTRAP_SERVERS",
        "sasl.username": "KAFKA_SASL_USERNAME",
        "sasl.password": "KAFKA_SASL_PASSWORD",
    }
    for src_key, env_key in mapping.items():
        if src_key in props:
            os.environ.setdefault(env_key, props[src_key])

load_env_file(".env")
load_kafka_properties("ccloud-python-client/client.properties")

# DB Config
DB_NAME = os.getenv("PGDATABASE", "oee_db")
DB_USER = os.getenv("PGUSER", "harshchanchlani")
DB_PASSWORD = os.getenv("PGPASSWORD", "")
DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5432")

# Kafka Config
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
kafka_username = os.getenv("KAFKA_SASL_USERNAME", "")
kafka_password = os.getenv("KAFKA_SASL_PASSWORD", "")

# Upgrade 3B: Initialize alert producer once at module level
alert_config = {
    'bootstrap.servers': bootstrap_servers,
    'security.protocol': 'SASL_SSL',
    'sasl.mechanisms': 'PLAIN',
    'sasl.username': kafka_username,
    'sasl.password': kafka_password,
}
try:
    alert_producer = ConfluentProducer(alert_config)
except Exception as e:
    print(f"[WARN] Could not initialize alert producer: {e}")
    alert_producer = None

# Spark Packages
spark_version = ".".join(pyspark.__version__.split(".")[:3])
scala_binary_version = os.getenv("SPARK_SCALA_BINARY_VERSION", "2.12")
spark_kafka_pkg = f"org.apache.spark:spark-sql-kafka-0-10_{scala_binary_version}:{spark_version}"
spark_extra_packages = os.getenv("SPARK_EXTRA_PACKAGES", "")

packages = [spark_kafka_pkg]
if spark_extra_packages.strip():
    packages.extend([pkg.strip() for pkg in spark_extra_packages.split(",") if pkg.strip()])

spark = (
    SparkSession.builder
    .appName("OEEStreaming_Upgraded")
    .config("spark.jars.packages", ",".join(packages))
    .getOrCreate()
)

# Upgrade 4C: MinIO Config
DATALAKE_ENABLED = os.getenv("DATALAKE_ENABLED", "true").lower() == "true"
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
DATALAKE_BUCKET  = os.getenv("DATALAKE_BUCKET",  "oee-datalake")

if DATALAKE_ENABLED:
    spark._jsc.hadoopConfiguration().set("fs.s3a.endpoint", MINIO_ENDPOINT)
    spark._jsc.hadoopConfiguration().set("fs.s3a.access.key", MINIO_ACCESS_KEY)
    spark._jsc.hadoopConfiguration().set("fs.s3a.secret.key", MINIO_SECRET_KEY)
    spark._jsc.hadoopConfiguration().set("fs.s3a.path.style.access", "true")
    spark._jsc.hadoopConfiguration().set("fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")

kafka_options = {
    "kafka.bootstrap.servers": bootstrap_servers,
    "subscribe": "OEE_0",
    "startingOffsets": "latest",
    "kafka.security.protocol": "SASL_SSL",
    "kafka.sasl.mechanism": "PLAIN",
    "kafka.sasl.jaas.config": (
        'org.apache.kafka.common.security.plain.PlainLoginModule required '
        f'username="{kafka_username}" '
        f'password="{kafka_password}";'
    )
}

df = spark.readStream.format("kafka").options(**kafka_options).load()

schema = StructType([
    StructField("machine_id", StringType()),
    StructField("availability", DoubleType()),
    StructField("performance", DoubleType()),
    StructField("quality", DoubleType()),
    StructField("timestamp", DoubleType()),
    StructField("oee", DoubleType()),
    StructField("message_id", StringType())
])

parsed = df.selectExpr("CAST(value AS STRING)") \
    .select(from_json(col("value"), schema).alias("data")) \
    .select("data.*") \
    .withColumn("event_time", from_unixtime(col("timestamp")).cast("timestamp"))

# Aggregation for Postgres
windowed = parsed \
    .withWatermark("event_time", "2 minutes") \
    .groupBy(
        window(col("event_time"), "1 minute", "30 seconds"),
        col("machine_id")
    ) \
    .agg(avg("oee").alias("avg_oee"))

# Upgrade 3B thresholds
WARNING_THRESHOLD  = float(os.getenv("OEE_WARNING_THRESHOLD",  "70.0"))
CRITICAL_THRESHOLD = float(os.getenv("OEE_CRITICAL_THRESHOLD", "55.0"))
ALERT_TOPIC = os.getenv("ALERT_TOPIC", "OEE_ALERTS")

def write_to_postgres(batch_df, batch_id):
    rows = batch_df.collect()
    if not rows: return

    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
    cur = conn.cursor()

    for row in rows:
        # Upgrade 2D: Secondary schema validation
        if not isinstance(row.machine_id, str) or not row.machine_id:
            print(f"[WARN] Invalid machine_id: {row.machine_id}"); continue
        if not (0 <= row.avg_oee <= 100):
            print(f"[WARN] Invalid avg_oee: {row.avg_oee}"); continue

        # Insert OEE data
        cur.execute("""
            INSERT INTO oee_data (machine_id, window_start, window_end, avg_oee)
            VALUES (%s, %s, %s, %s)
        """, (row.machine_id, row.window.start, row.window.end, row.avg_oee))

        # Upgrade 3B: Alerting logic
        if row.avg_oee < WARNING_THRESHOLD:
            level = "CRITICAL" if row.avg_oee < CRITICAL_THRESHOLD else "WARNING"
            
            # DB Insert
            cur.execute("""
                INSERT INTO oee_alerts (machine_id, avg_oee, threshold, window_start, window_end, alert_level)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (row.machine_id, row.avg_oee, WARNING_THRESHOLD if level == "WARNING" else CRITICAL_THRESHOLD, 
                  row.window.start, row.window.end, level))
            
            # Kafka Produce
            if alert_producer:
                alert_payload = {
                    "machine_id": row.machine_id,
                    "avg_oee": round(row.avg_oee, 2),
                    "threshold": WARNING_THRESHOLD if level == "WARNING" else CRITICAL_THRESHOLD,
                    "alert_level": level,
                    "window_start": row.window.start.isoformat(),
                    "window_end": row.window.end.isoformat(),
                    "alert_id": str(uuid.uuid4())
                }
                try:
                    alert_producer.produce(ALERT_TOPIC, value=json.dumps(alert_payload).encode('utf-8'))
                    alert_producer.poll(0)
                except Exception as e:
                    print(f"[WARN] Alert produce failed: {e}")

    conn.commit()
    cur.close()
    conn.close()

# Postgres Sink
pg_query = windowed.writeStream \
    .outputMode("update") \
    .foreachBatch(write_to_postgres) \
    .trigger(processingTime="10 seconds") \
    .start()

# Upgrade 4C: Data Lake Parquet Sink
if DATALAKE_ENABLED:
    try:
        datalake_df = parsed.withColumn("year",  year("event_time")) \
                            .withColumn("month", month("event_time")) \
                            .withColumn("day",   dayofmonth("event_time")) \
                            .withColumn("hour",  hour("event_time"))

        datalake_query = datalake_df.writeStream \
            .outputMode("append") \
            .format("parquet") \
            .option("path", f"s3a://{DATALAKE_BUCKET}/raw/oee_events/") \
            .option("checkpointLocation", f"s3a://{DATALAKE_BUCKET}/checkpoints/raw/") \
            .partitionBy("year", "month", "day", "hour") \
            .trigger(processingTime="30 seconds") \
            .start()
    except Exception as e:
        print(f"[WARN] Datalake sink disabled: {e}")

spark.streams.awaitAnyTermination()