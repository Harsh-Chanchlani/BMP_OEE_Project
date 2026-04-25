"""
Semiconductor Chip Fab OEE Data Producer
Simulates a high-tech wafer fabrication environment with SECS/GEM-style telemetry.
"""

from confluent_kafka import Producer
import json
import time
import random
import os
import sys
import uuid
from datetime import datetime

# Add backend to path for shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from schema_validator import validate_message, SchemaValidationError

def load_env_file(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path): return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

def load_kafka_properties(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "ccloud-python-client", "client.properties")
    if not os.path.exists(path): return
    props = {}
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    mapping = {
        "bootstrap.servers": "KAFKA_BOOTSTRAP_SERVERS",
        "sasl.username": "KAFKA_SASL_USERNAME",
        "sasl.password": "KAFKA_SASL_PASSWORD",
    }
    for src_key, env_key in mapping.items():
        if src_key in props: os.environ.setdefault(env_key, props[src_key])

load_env_file()
load_kafka_properties()

# Semiconductor Tool Profiles (Chip Fab)
# High precision, high PM frequency, extreme sensitivity
MACHINE_PROFILES = {
    "LITHO_ASML_01":  {"avail": (90, 98), "perf": (85, 95), "qual": (98, 100), "recipe": "EUV_7nm_Logic"},
    "ETCH_LAM_02":    {"avail": (80, 92), "perf": (70, 90), "qual": (95, 99),  "recipe": "Poly_Etch_A1"},
    "DEP_AMAT_03":    {"avail": (75, 88), "perf": (75, 92), "qual": (94, 98),  "recipe": "CVD_Nitride_HighK"},
    "CMP_EBARA_04":   {"avail": (85, 95), "perf": (80, 95), "qual": (92, 97),  "recipe": "Copper_Planarization"},
    "INSPECT_KLA_05": {"avail": (92, 99), "perf": (90, 98), "qual": (99, 100), "recipe": "Brightfield_Inspection"},
}

FAB_LOSS_EVENTS = [
    {"name": "Reticle Haze", "comp": "quality", "sev": (5, 15), "prob": 0.01, "tools": ["LITHO_ASML_01"]},
    {"name": "Vacuum Leak", "comp": "performance", "sev": (10, 25), "prob": 0.02, "tools": ["ETCH_LAM_02", "DEP_AMAT_03"]},
    {"name": "Slurry Imbalance", "comp": "quality", "sev": (3, 10), "prob": 0.03, "tools": ["CMP_EBARA_04"]},
    {"name": "Chamber Seasoning", "comp": "availability", "sev": (20, 40), "prob": 0.04, "tools": ["ETCH_LAM_02", "DEP_AMAT_03"]},
    {"name": "Vibration Spike", "comp": "performance", "sev": (5, 10), "prob": 0.02, "tools": ["LITHO_ASML_01", "INSPECT_KLA_05"]},
]

class FabSimulator:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self.profile = MACHINE_PROFILES.get(machine_id, {"avail": (80, 90), "perf": (80, 90), "qual": (95, 100), "recipe": "Standard_Recipe"})
        self.msg_count = 0
        self.active_loss = None
        self.loss_remaining = 0
        self.current_lot = f"LOT-{random.randint(1000, 9999)}"

    def generate(self):
        now = time.time()
        # Periodic lot change every 50 messages
        if self.msg_count % 50 == 0:
            self.current_lot = f"LOT-{random.randint(1000, 9999)}"

        avail = random.uniform(*self.profile["avail"])
        perf = random.uniform(*self.profile["perf"])
        qual = random.uniform(*self.profile["qual"])

        # Check for loss events
        if self.active_loss:
            loss = self.active_loss
            if loss["comp"] == "availability": avail -= loss["sev_val"]
            elif loss["comp"] == "performance": perf -= loss["sev_val"]
            elif loss["comp"] == "quality": qual -= loss["sev_val"]
            self.loss_remaining -= 1
            if self.loss_remaining <= 0: self.active_loss = None
        else:
            for le in FAB_LOSS_EVENTS:
                if self.machine_id in le["tools"] and random.random() < le["prob"]:
                    self.active_loss = le.copy()
                    self.active_loss["sev_val"] = random.uniform(*le["sev"])
                    self.loss_remaining = random.randint(5, 15)
                    break

        avail = round(max(0, min(100, avail)), 2)
        perf = round(max(0, min(100, perf)), 2)
        qual = round(max(0, min(100, qual)), 2)
        oee = round((avail * perf * qual) / 10000, 2)

        data = {
            "machine_id": self.machine_id,
            "availability": avail,
            "performance": perf,
            "quality": qual,
            "oee": oee,
            "timestamp": now,
            "message_id": str(uuid.uuid4()),
            "lot_id": self.current_lot,
            "recipe_name": self.profile["recipe"],
            "chamber_id": f"CH-{random.randint(1, 4)}",
            "message_number": self.msg_count
        }
        if self.active_loss:
            data["loss_event"] = {"name": self.active_loss["name"], "component": self.active_loss["comp"]}
        
        self.msg_count += 1
        return data

# Kafka Init
config = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', ''),
    'security.protocol': 'SASL_SSL',
    'sasl.mechanisms': 'PLAIN',
    'sasl.username': os.getenv('KAFKA_SASL_USERNAME', ''),
    'sasl.password': os.getenv('KAFKA_SASL_PASSWORD', ''),
}
producer = Producer(config)
topic = "OEE_0"

machines = list(MACHINE_PROFILES.keys())
simulators = {m: FabSimulator(m) for m in machines}

def delivery_report(err, msg):
    if err: print(f"❌ Delivery failed: {err}")
    else: pass

print(f"🚀 Semiconductor Fab Producer Started (Confluent Cloud)")
print(f"   Tools: {', '.join(machines)}")

try:
    while True:
        for m_id, sim in simulators.items():
            data = sim.generate()
            try:
                payload = json.dumps(data).encode('utf-8')
                validate_message(payload) # Use shared validator
                producer.produce(topic, key=m_id.encode('utf-8'), value=payload, callback=delivery_report)
                
                # Console output for visibility
                loss_str = f" ⚠️ {data['loss_event']['name']}" if "loss_event" in data else ""
                print(f"✓ {m_id:15} | OEE: {data['oee']:5.2f}% | Lot: {data['lot_id']}{loss_str}")
            except SchemaValidationError as e:
                print(f"⚠️ Validation error for {m_id}: {e}")
        
        producer.poll(0)
        time.sleep(2)
except KeyboardInterrupt:
    print("\n⏹️ Stopped.")
finally:
    producer.flush()