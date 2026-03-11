from confluent_kafka import Producer
import json
import time
import random
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
            # Keep explicit shell exports higher priority than .env defaults.
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

# 1. Confluent Cloud configuration from environment variables
config = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'pkc-619z3.us-east1.gcp.confluent.cloud:9092'),
    'security.protocol': 'SASL_SSL',
    'sasl.mechanisms': 'PLAIN',
    'sasl.username': os.getenv('KAFKA_SASL_USERNAME', ''),
    'sasl.password': os.getenv('KAFKA_SASL_PASSWORD', ''),
}

if not config["sasl.username"] or not config["sasl.password"]:
    raise RuntimeError(
        "Missing Kafka credentials. Set KAFKA_SASL_USERNAME and "
        "KAFKA_SASL_PASSWORD in .env or environment variables."
    )

# 2. Initialize Producer
producer = Producer(config)
topic = "OEE_0"

def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}]")

print(f"Streaming OEE data to {topic}...")

try:
    while True:
        # Simulate OEE Data
        data = {
            "machine_id": "M2_MAC_SIM",
            "availability": round(random.uniform(85, 95), 2),
            "performance": round(random.uniform(90, 98), 2),
            "quality": round(random.uniform(98, 100), 2),
            "timestamp": time.time()
        }
        # Calculate OEE locally as we planned
        data["oee"] = round((data["availability"] * data["performance"] * data["quality"]) / 10000, 2)

        # Produce to Confluent
        producer.produce(topic, json.dumps(data).encode('utf-8'), callback=delivery_report)
        producer.poll(0) # Serve delivery callbacks
        time.sleep(2)    # Send every 2 seconds
        
except KeyboardInterrupt:
    print("Streaming stopped.")
finally:
    producer.flush()