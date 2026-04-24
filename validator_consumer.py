import os
import json
import signal
import sys
from confluent_kafka import Consumer, KafkaError
from schema_validator import validate_message, SchemaValidationError
from dlq_producer import send_to_dlq

def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

def load_kafka_properties(path="ccloud-python-client/client.properties"):
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

def main():
    config = {
        'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', ''),
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': os.getenv('KAFKA_SASL_USERNAME', ''),
        'sasl.password': os.getenv('KAFKA_SASL_PASSWORD', ''),
        'group.id': 'oee-schema-validator',
        'auto.offset.reset': 'earliest'
    }

    consumer = Consumer(config)
    consumer.subscribe(['OEE_0'])

    print("🚀 OEE Schema Validator Consumer Started (Confluent Cloud)")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    print(f"Error: {msg.error()}")
                    break

            raw_value = msg.value()
            try:
                parsed = validate_message(raw_value)
                print(f"[VALID] machine_id={parsed.get('machine_id')} message_id={parsed.get('message_id')}")
            except SchemaValidationError as e:
                send_to_dlq(raw_value, str(e), "OEE_0")
                print(f"[DLQ] reason={str(e)}")

    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()

if __name__ == "__main__":
    main()
