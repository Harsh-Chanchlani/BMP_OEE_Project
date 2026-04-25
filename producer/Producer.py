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
# Ranges based on real-world fab benchmarks (SEMI E10 / OEE industry data)
# Availability: unplanned downtime, PM, changeovers
# Performance:  speed losses, micro-stoppages, reduced throughput
# Quality:      yield loss, rework, scrap
MACHINE_PROFILES = {
    # EUV Lithography — flagship tool, consistently high performance
    "LITHO_ASML_01":  {"avail": (92, 98), "perf": (88, 96), "qual": (98, 99.8), "recipe": "EUV_7nm_Logic",          "nominal_wph": 110},
    # Plasma Etch — solid performer with occasional chamber dips
    "ETCH_LAM_02":    {"avail": (87, 95), "perf": (84, 93), "qual": (95, 99),   "recipe": "Poly_Etch_A1",           "nominal_wph": 85},
    # CVD Deposition — reliable, slightly lower ceiling due to PM schedule
    "DEP_AMAT_03":    {"avail": (85, 94), "perf": (83, 92), "qual": (94, 98),   "recipe": "CVD_Nitride_HighK",      "nominal_wph": 75},
    # CMP — good availability, tight quality control
    "CMP_EBARA_04":   {"avail": (88, 95), "perf": (85, 94), "qual": (93, 98),   "recipe": "Copper_Planarization",   "nominal_wph": 95},
    # Inspection — near-continuous uptime, highest quality gate
    "INSPECT_KLA_05": {"avail": (93, 99), "perf": (90, 97), "qual": (98, 99.9), "recipe": "Brightfield_Inspection", "nominal_wph": 140},
}

FAB_LOSS_EVENTS = [
    # LITHO: reticle haze — rare, small quality dip
    {"name": "Reticle Haze",           "comp": "quality",      "sev": (3, 7),   "prob": 0.004, "tools": ["LITHO_ASML_01"]},
    # LITHO/INSPECT: vibration — minor performance blip
    {"name": "Vibration Spike",        "comp": "performance",  "sev": (3, 8),   "prob": 0.005, "tools": ["LITHO_ASML_01", "INSPECT_KLA_05"]},
    # ETCH/DEP: vacuum leak — occasional moderate performance dip
    {"name": "Vacuum Leak",            "comp": "performance",  "sev": (6, 14),  "prob": 0.007, "tools": ["ETCH_LAM_02", "DEP_AMAT_03"]},
    # ETCH/DEP: chamber seasoning — infrequent availability dip
    {"name": "Chamber Seasoning",      "comp": "availability", "sev": (8, 16),  "prob": 0.008, "tools": ["ETCH_LAM_02", "DEP_AMAT_03"]},
    # DEP: particle contamination — rare quality event
    {"name": "Particle Contamination", "comp": "quality",      "sev": (3, 8),   "prob": 0.004, "tools": ["DEP_AMAT_03"]},
    # CMP: slurry imbalance — minor quality variation
    {"name": "Slurry Imbalance",       "comp": "quality",      "sev": (3, 7),   "prob": 0.006, "tools": ["CMP_EBARA_04"]},
    # CMP: pad wear — gradual small performance dip
    {"name": "Pad Wear",               "comp": "performance",  "sev": (4, 10),  "prob": 0.005, "tools": ["CMP_EBARA_04"]},
    # ALL: PM overrun — very rare, small availability bleed
    {"name": "PM Overrun",             "comp": "availability", "sev": (5, 12),  "prob": 0.003, "tools": ["LITHO_ASML_01", "ETCH_LAM_02", "DEP_AMAT_03", "CMP_EBARA_04", "INSPECT_KLA_05"]},
]

def shift_for_hour(h: int) -> str:
    if 6 <= h <= 13:  return "morning"
    if 14 <= h <= 21: return "afternoon"
    return "night"


class FabSimulator:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self.profile = MACHINE_PROFILES.get(machine_id, {"avail": (80, 90), "perf": (80, 90), "qual": (95, 100), "recipe": "Standard_Recipe"})
        self.msg_count = 0
        self.active_loss = None
        self.loss_remaining = 0
        self.current_lot = f"LOT-{random.randint(1000, 9999)}"
        # MTBF/MTTR state tracking
        self.failure_start_time = None
        self.prev_failure_end_time = None
        self.last_mttr = None
        self.last_mtbf = None

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
            if self.loss_remaining <= 0:
                # Loss ends — compute MTTR
                if self.failure_start_time is not None:
                    self.last_mttr = round((time.time() - self.failure_start_time) / 60, 2)
                    self.prev_failure_end_time = time.time()
                self.active_loss = None
                self.failure_start_time = None
        else:
            for le in FAB_LOSS_EVENTS:
                if self.machine_id in le["tools"] and random.random() < le["prob"]:
                    self.active_loss = le.copy()
                    self.active_loss["sev_val"] = random.uniform(*le["sev"])
                    self.loss_remaining = random.randint(4, 10)
                    # Loss begins — compute MTBF if we have a previous failure end
                    if self.prev_failure_end_time is not None:
                        self.last_mtbf = round((time.time() - self.prev_failure_end_time) / 60, 2)
                    self.failure_start_time = time.time()
                    break

        avail = round(max(0, min(100, avail)), 2)
        perf = round(max(0, min(100, perf)), 2)
        qual = round(max(0, min(100, qual)), 2)
        oee = round((avail * perf * qual) / 10000, 2)

        nominal_wph = self.profile.get("nominal_wph", 100)
        wph = max(0, round(nominal_wph * perf / 100, 1))
        shift = shift_for_hour(datetime.now().hour)

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
            "message_number": self.msg_count,
            "wph": wph,
            "shift": shift,
        }
        if self.active_loss:
            data["loss_event"] = {"name": self.active_loss["name"], "component": self.active_loss["comp"]}
        if self.last_mttr is not None:
            data["mttr_minutes"] = self.last_mttr
        if self.last_mtbf is not None:
            data["mtbf_minutes"] = self.last_mtbf
        
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
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\n⏹️ Stopped.")
finally:
    producer.flush()