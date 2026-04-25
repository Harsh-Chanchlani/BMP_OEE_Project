import json
import os
import atexit
from datetime import datetime
import base64
from confluent_kafka import Producer

def load_env_file(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

def load_kafka_properties(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "ccloud-python-client", "client.properties")
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

load_env_file()
load_kafka_properties()

# Kafka Configuration
config = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', ''),
    'security.protocol': 'SASL_SSL',
    'sasl.mechanisms': 'PLAIN',
    'sasl.username': os.getenv('KAFKA_SASL_USERNAME', ''),
    'sasl.password': os.getenv('KAFKA_SASL_PASSWORD', ''),
}

# Persistent producer instance
_producer = Producer(config)

def flush_producer():
    _producer.flush()

atexit.register(flush_producer)

def send_to_dlq(raw: bytes, reason: str, source_topic: str):
    dlq_topic = os.getenv("DLQ_TOPIC", "OEE_0_DLQ")
    
    try:
        original_message = raw.decode("utf-8")
    except UnicodeDecodeError:
        original_message = base64.b64encode(raw).decode("utf-8")
    
    envelope = {
        "original_message": original_message,
        "failure_reason": reason,
        "source_topic": source_topic,
        "failed_at": datetime.utcnow().isoformat()
    }
    
    _producer.produce(
        dlq_topic,
        value=json.dumps(envelope).encode("utf-8")
    )
    _producer.poll(0)
