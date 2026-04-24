"""
Enhanced OEE Data Producer
==========================
Generates realistic OEE data with:
- Shift-based patterns (morning/afternoon/night performance variations)
- Periodic downtime events simulation
- Six Big Losses event generation
- Component-level data (availability, performance, quality)
- Multiple machine support
"""

from confluent_kafka import Producer
import json
import time
import random
import math
import os
from datetime import datetime


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


# ============================================
# SHIFT DEFINITIONS
# ============================================
def get_current_shift(hour: int) -> str:
    """Determine shift based on hour (0-23)."""
    if 6 <= hour < 14:
        return "morning"
    elif 14 <= hour < 22:
        return "afternoon"
    else:
        return "night"


def get_shift_multipliers(shift: str) -> dict:
    """
    Shift-based performance patterns.
    Morning: Best performance (fresh workers, optimal conditions)
    Afternoon: Slight decline (fatigue setting in)
    Night: Lower performance (reduced supervision, fatigue)
    """
    multipliers = {
        "morning": {
            "availability": (0.85, 0.98),
            "performance": (0.82, 0.98),
            "quality": (0.90, 0.99),
        },
        "afternoon": {
            "availability": (0.80, 0.95),
            "performance": (0.78, 0.95),
            "quality": (0.85, 0.98),
        },
        "night": {
            "availability": (0.70, 0.92),
            "performance": (0.70, 0.92),
            "quality": (0.80, 0.96),
        },
    }
    return multipliers.get(shift, multipliers["morning"])


# ============================================
# DOWNTIME & LOSS SIMULATION
# ============================================
SIX_BIG_LOSSES = {
    "equipment_failure": {
        "component": "availability",
        "severity_range": (15, 40),
        "probability": 0.02,
        "description": "Unplanned equipment breakdown"
    },
    "setup_adjustment": {
        "component": "availability",
        "severity_range": (5, 20),
        "probability": 0.03,
        "description": "Setup and changeover time"
    },
    "idling": {
        "component": "performance",
        "severity_range": (5, 15),
        "probability": 0.05,
        "description": "Idling and minor stoppages"
    },
    "reduced_speed": {
        "component": "performance",
        "severity_range": (10, 25),
        "probability": 0.04,
        "description": "Running below optimal speed"
    },
    "defects": {
        "component": "quality",
        "severity_range": (3, 15),
        "probability": 0.03,
        "description": "Production defects and rework"
    },
    "reduced_yield": {
        "component": "quality",
        "severity_range": (2, 10),
        "probability": 0.04,
        "description": "Startup losses and reduced yield"
    }
}


class OEEDataGenerator:
    """Generate realistic OEE data with patterns and anomalies."""
    
    def __init__(self, machine_id: str):
        self.machine_id = machine_id
        self.message_count = 0
        self.active_loss = None
        self.loss_remaining_cycles = 0
        self.baseline = {
            "availability": 88.0,
            "performance": 85.0,
            "quality": 92.0
        }
        
    def _apply_time_pattern(self, value: float, timestamp: float) -> float:
        """Add sinusoidal pattern to simulate natural variations."""
        hour_cycle = math.sin(2 * math.pi * timestamp / (3600 * 4))  # 4-hour cycle
        minute_cycle = math.sin(2 * math.pi * timestamp / 300)  # 5-minute micro-cycle
        variation = hour_cycle * 2 + minute_cycle * 1
        return max(0, min(100, value + variation))
    
    def _check_for_loss_event(self) -> tuple:
        """Check if a new loss event should occur. Returns (loss_type, severity)."""
        if self.active_loss:
            return None, 0
            
        for loss_type, config in SIX_BIG_LOSSES.items():
            if random.random() < config["probability"]:
                severity = random.uniform(*config["severity_range"])
                duration = random.randint(3, 15)  # 3-15 cycles (6-30 seconds)
                self.active_loss = loss_type
                self.loss_remaining_cycles = duration
                return loss_type, severity
        return None, 0
    
    def generate(self) -> dict:
        """Generate one OEE data point with realistic patterns."""
        now = time.time()
        dt = datetime.fromtimestamp(now)
        hour = dt.hour
        shift = get_current_shift(hour)
        shift_ranges = get_shift_multipliers(shift)
        
        # Base values with shift influence
        availability = random.uniform(*[x * 100 for x in shift_ranges["availability"]])
        performance = random.uniform(*[x * 100 for x in shift_ranges["performance"]])
        quality = random.uniform(*[x * 100 for x in shift_ranges["quality"]])
        
        # Apply time-based patterns
        availability = self._apply_time_pattern(availability, now)
        performance = self._apply_time_pattern(performance, now)
        quality = self._apply_time_pattern(quality, now)
        
        # Check for new loss events
        loss_event = None
        loss_type, severity = self._check_for_loss_event()
        
        # Apply active loss
        if self.active_loss:
            loss_config = SIX_BIG_LOSSES[self.active_loss]
            component = loss_config["component"]
            
            if component == "availability":
                availability = max(30, availability - severity)
            elif component == "performance":
                performance = max(40, performance - severity)
            elif component == "quality":
                quality = max(50, quality - severity)
            
            loss_event = {
                "type": self.active_loss,
                "component": loss_config["component"],
                "severity": round(severity, 2),
                "description": loss_config["description"],
                "remaining_cycles": self.loss_remaining_cycles
            }
            
            self.loss_remaining_cycles -= 1
            if self.loss_remaining_cycles <= 0:
                self.active_loss = None
        
        # Calculate OEE
        availability = round(max(0, min(100, availability)), 2)
        performance = round(max(0, min(100, performance)), 2)
        quality = round(max(0, min(100, quality)), 2)
        oee = round((availability * performance * quality) / 10000, 2)
        
        self.message_count += 1
        
        data = {
            "machine_id": self.machine_id,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee": oee,
            "shift": shift,
            "timestamp": now,
            "message_number": self.message_count,
        }
        
        # Include loss event info if active
        if loss_event:
            data["loss_event"] = loss_event
        
        return data


# ============================================
# KAFKA CONFIGURATION
# ============================================
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

producer = Producer(config)
topic = "OEE_0"

# Support multiple machines
MACHINES = os.getenv("OEE_MACHINES", "M2_MAC_SIM").split(",")
generators = {m.strip(): OEEDataGenerator(m.strip()) for m in MACHINES}


def delivery_report(err, msg):
    if err is not None:
        print(f"❌ Delivery failed: {err}")
    else:
        data = json.loads(msg.value().decode('utf-8'))
        loss_indicator = " ⚠️ LOSS EVENT" if data.get("loss_event") else ""
        print(f"✓ [{data['shift'].upper():9}] {data['machine_id']}: OEE={data['oee']:5.2f}% "
              f"(A={data['availability']:5.2f}%, P={data['performance']:5.2f}%, Q={data['quality']:5.2f}%){loss_indicator}")


print(f"🚀 Enhanced OEE Producer Started")
print(f"   Topic: {topic}")
print(f"   Machines: {', '.join(generators.keys())}")
print(f"   Features: Shift patterns, Six Big Losses simulation")
print("-" * 60)

try:
    while True:
        for machine_id, generator in generators.items():
            data = generator.generate()
            producer.produce(
                topic, 
                json.dumps(data).encode('utf-8'), 
                callback=delivery_report
            )
        producer.poll(0)
        time.sleep(2)  # Send every 2 seconds
        
except KeyboardInterrupt:
    print("\n⏹️  Streaming stopped.")
finally:
    producer.flush()