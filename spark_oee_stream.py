from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, window, avg, from_unixtime
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
import pyspark
import psycopg2
import os


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

DB_NAME = os.getenv("PGDATABASE", "oee_db")
DB_USER = os.getenv("PGUSER", "harshchanchlani")
DB_PASSWORD = os.getenv("PGPASSWORD", "")
DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5432")

spark_version = ".".join(pyspark.__version__.split(".")[:3])
scala_binary_version = os.getenv("SPARK_SCALA_BINARY_VERSION", "2.13")
default_kafka_pkg = (
    f"org.apache.spark:spark-sql-kafka-0-10_{scala_binary_version}:{spark_version}"
)
spark_kafka_pkg = os.getenv("SPARK_KAFKA_PACKAGE", default_kafka_pkg)
spark_extra_packages = os.getenv("SPARK_EXTRA_PACKAGES", "")

packages = [spark_kafka_pkg]
if spark_extra_packages.strip():
    packages.extend([pkg.strip() for pkg in spark_extra_packages.split(",") if pkg.strip()])

spark = (
    SparkSession.builder
    .appName("OEEStreaming")
    .config("spark.jars.packages", ",".join(packages))
    .getOrCreate()
)

# ---------------- Kafka Config ----------------
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "pkc-619z3.us-east1.gcp.confluent.cloud:9092")
kafka_username = os.getenv("KAFKA_SASL_USERNAME", "")
kafka_password = os.getenv("KAFKA_SASL_PASSWORD", "")

if not kafka_username or not kafka_password:
    raise RuntimeError(
        "Missing Kafka credentials. Set KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD "
        "in .env or environment variables."
    )

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

df = spark.readStream \
    .format("kafka") \
    .options(**kafka_options) \
    .load()

# ---------------- JSON Schema ----------------
schema = StructType([
    StructField("machine_id", StringType()),
    StructField("availability", DoubleType()),
    StructField("performance", DoubleType()),
    StructField("quality", DoubleType()),
    StructField("timestamp", DoubleType()),
    StructField("oee", DoubleType())
])

parsed = df.selectExpr("CAST(value AS STRING)") \
    .select(from_json(col("value"), schema).alias("data")) \
    .select("data.*")

# ---------------- Convert UNIX → Timestamp ----------------
parsed = parsed.withColumn(
    "event_time",
    from_unixtime(col("timestamp")).cast("timestamp")
)

# ---------------- Window Aggregation ----------------
windowed = parsed \
    .withWatermark("event_time", "2 minutes") \
    .groupBy(
        window(col("event_time"), "1 minute", "30 seconds"),
        col("machine_id")
    ) \
    .agg(avg("oee").alias("avg_oee"))

# ---------------- Write to Postgres ----------------
def write_to_postgres(batch_df, batch_id):

    rows = batch_df.collect()

    if len(rows) == 0:
        return

    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oee_data (
            id BIGSERIAL PRIMARY KEY,
            machine_id TEXT NOT NULL,
            window_start TIMESTAMP NOT NULL,
            window_end TIMESTAMP NOT NULL,
            avg_oee DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_oee_data_window_start
        ON oee_data (window_start)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_oee_data_machine_window
        ON oee_data (machine_id, window_start)
        """
    )

    for row in rows:
        cursor.execute("""
            INSERT INTO oee_data (machine_id, window_start, window_end, avg_oee)
            VALUES (%s, %s, %s, %s)
        """, (
            row.machine_id,
            row.window.start,
            row.window.end,
            row.avg_oee
        ))

    conn.commit()
    cursor.close()
    conn.close()

# --------------------------------------------
# Start Streaming Query
# --------------------------------------------
query = windowed.writeStream \
    .outputMode("update") \
    .foreachBatch(write_to_postgres) \
    .trigger(processingTime="10 seconds") \
    .start()

query.awaitTermination()