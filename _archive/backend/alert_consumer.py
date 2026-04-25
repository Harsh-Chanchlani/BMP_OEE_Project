import os
import json
import smtplib
from email.mime.text import MIMEText
import httpx
from confluent_kafka import Consumer, KafkaError

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

def send_console_alert(alert):
    color = "\033[91m" if alert["alert_level"] == "CRITICAL" else "\033[93m"
    reset = "\033[0m"
    print(f"{color}[{alert['alert_level']}] Machine {alert['machine_id']} OEE at {alert['avg_oee']:.1f}% (Threshold: {alert['threshold']:.1f}%){reset}")

async def send_webhook_alert(alert):
    url = os.getenv("ALERT_WEBHOOK_URL")
    if url:
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=alert)
            except Exception as e:
                print(f"Webhook error: {e}")

def send_email_alert(alert):
    to_email = os.getenv("ALERT_EMAIL_TO")
    smtp_host = os.getenv("SMTP_HOST")
    if to_email and smtp_host:
        msg = MIMEText(f"Alert: {alert['alert_level']}\nMachine: {alert['machine_id']}\nOEE: {alert['avg_oee']:.1f}%\nWindow: {alert['window_start']} to {alert['window_end']}")
        msg["Subject"] = f"[OEE ALERT] {alert['alert_level']} — {alert['machine_id']} @ {alert['avg_oee']:.1f}%"
        msg["From"] = os.getenv("SMTP_USER", "oee-system@example.com")
        msg["To"] = to_email
        
        try:
            with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", 587))) as server:
                server.starttls()
                server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
                server.send_message(msg)
        except Exception as e:
            print(f"Email error: {e}")

async def main():
    config = {
        'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', ''),
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': os.getenv('KAFKA_SASL_USERNAME', ''),
        'sasl.password': os.getenv('KAFKA_SASL_PASSWORD', ''),
        'group.id': 'oee-alert-dispatcher',
        'auto.offset.reset': 'earliest'
    }

    consumer = Consumer(config)
    consumer.subscribe([os.getenv("ALERT_TOPIC", "OEE_ALERTS")])

    print("🚀 OEE Alert Dispatcher Started (Confluent Cloud)")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None: continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF: continue
                else: print(f"Error: {msg.error()}"); break

            alert = json.loads(msg.value().decode('utf-8'))
            send_console_alert(alert)
            await send_webhook_alert(alert)
            send_email_alert(alert)

    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
