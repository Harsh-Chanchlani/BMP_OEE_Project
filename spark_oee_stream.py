from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, window, avg, from_unixtime
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
import psycopg2
import os

spark = SparkSession.builder \
    .appName("OEEStreaming") \
    .getOrCreate()

# ---------------- Kafka Config ----------------
bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "pkc-619z3.us-east1.gcp.confluent.cloud:9092")
kafka_username = os.getenv("KAFKA_SASL_USERNAME", "")
kafka_password = os.getenv("KAFKA_SASL_PASSWORD", "")

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
        dbname="oee_db",
        user="harshchanchlani",
        host="localhost",
        port="5432"
    )

    cursor = conn.cursor()

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