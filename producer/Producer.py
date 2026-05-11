"""
Semiconductor Fab OEE Producer
================================
Simulates 5 real-world fab machines sending OEE telemetry to Kafka.

OEE Formula (from Kennedy, "Understanding, Measuring and Improving OEE"):
  Availability = Run Time / Planned Production Time  × 100
  Performance  = (Ideal Cycle Time × Total Pieces) / Run Time  × 100
  Quality      = Good Pieces / Total Pieces  × 100
  OEE          = (Availability × Performance × Quality) / 10 000

Each Kafka message represents one ~30-second production window per machine.
The producer fires every 0.5 s (one message per machine per cycle).

7 OEE Losses modelled (Kennedy's model):
  Availability losses → Unplanned Downtime, Setup/Changeover, Planned Downtime
  Performance losses  → Minor Stoppages, Reduced Speed
  Quality losses      → Rejects/Rework, Start-up Yield Loss
"""

import json
import os
import random
import sys
import time
import uuid
from datetime import datetime

from confluent_kafka import Producer

# ── shared validator ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from schema_validator import validate_message, SchemaValidationError


# ── config loaders ────────────────────────────────────────────────────────────
def _load_env(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _load_kafka_props(path=None):
    path = path or os.path.join(
        os.path.dirname(__file__), "..", "ccloud-python-client", "client.properties"
    )
    if not os.path.exists(path):
        return
    props = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    for src, env in [
        ("bootstrap.servers", "KAFKA_BOOTSTRAP_SERVERS"),
        ("sasl.username",     "KAFKA_SASL_USERNAME"),
        ("sasl.password",     "KAFKA_SASL_PASSWORD"),
    ]:
        if src in props:
            os.environ.setdefault(env, props[src])


_load_env()
_load_kafka_props()


# ═══════════════════════════════════════════════════════════════════════════════
# MACHINE PROFILES
# Each machine has:
#   ideal_cycle_time_min  — how long it *should* take to make one piece (minutes)
#   planned_window_min    — the production window each message represents (minutes)
#   base_downtime_pct     — typical unplanned downtime as % of planned window
#   base_defect_rate      — typical defect rate (fraction of pieces that fail QC)
#   base_speed_ratio      — typical actual speed / ideal speed (< 1 = running slow)
#
# These numbers are grounded in real semiconductor fab benchmarks (SEMI E10).
# ═══════════════════════════════════════════════════════════════════════════════
MACHINE_PROFILES = {
    # EUV Lithography — flagship, tightly controlled, very high OEE
    "LITHO_ASML_01": {
        "ideal_cycle_time_min": 0.55,   # ~110 wafers/hour ideal
        "planned_window_min":   0.5,
        "base_downtime_pct":    0.04,   # 4 % unplanned downtime
        "base_defect_rate":     0.005,  # 0.5 % defect rate
        "base_speed_ratio":     0.94,   # runs at 94 % of ideal speed
    },
    # Plasma Etch — solid performer, occasional chamber dips
    "ETCH_LAM_02": {
        "ideal_cycle_time_min": 0.71,   # ~85 wafers/hour ideal
        "planned_window_min":   0.5,
        "base_downtime_pct":    0.07,
        "base_defect_rate":     0.015,
        "base_speed_ratio":     0.90,
    },
    # CVD Deposition — reliable, slightly lower ceiling due to PM schedule
    "DEP_AMAT_03": {
        "ideal_cycle_time_min": 0.80,   # ~75 wafers/hour ideal
        "planned_window_min":   0.5,
        "base_downtime_pct":    0.08,
        "base_defect_rate":     0.020,
        "base_speed_ratio":     0.88,
    },
    # CMP — good availability, tight quality control
    "CMP_EBARA_04": {
        "ideal_cycle_time_min": 0.63,   # ~95 wafers/hour ideal
        "planned_window_min":   0.5,
        "base_downtime_pct":    0.06,
        "base_defect_rate":     0.018,
        "base_speed_ratio":     0.91,
    },
    # Inspection — near-continuous uptime, highest quality gate
    "INSPECT_KLA_05": {
        "ideal_cycle_time_min": 0.43,   # ~140 wafers/hour ideal
        "planned_window_min":   0.5,
        "base_downtime_pct":    0.03,
        "base_defect_rate":     0.004,
        "base_speed_ratio":     0.95,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 7 LOSS EVENTS  (Kennedy's 7 OEE Losses)
# Each event:
#   type       — one of the 7 loss categories
#   component  — which OEE factor it hurts (availability / performance / quality)
#   impact     — (min, max) extra degradation applied to the affected component
#   duration   — how many consecutive windows the event lasts
#   prob       — probability of triggering per window (when no event is active)
#   tools      — which machines can experience this event
# ═══════════════════════════════════════════════════════════════════════════════
LOSS_EVENTS = [
    # ── Availability losses ───────────────────────────────────────────────────
    {
        "name": "Unplanned Breakdown",
        "type": "unplanned_downtime",
        "component": "availability",
        "impact": (0.15, 0.35),   # adds 15–35 % extra downtime fraction
        "duration": (4, 10),
        "prob": 0.006,
        "tools": ["LITHO_ASML_01", "ETCH_LAM_02", "DEP_AMAT_03", "CMP_EBARA_04", "INSPECT_KLA_05"],
    },
    {
        "name": "Chamber Seasoning (Setup)",
        "type": "setup_changeover",
        "component": "availability",
        "impact": (0.08, 0.18),
        "duration": (3, 7),
        "prob": 0.008,
        "tools": ["ETCH_LAM_02", "DEP_AMAT_03"],
    },
    {
        "name": "PM Overrun",
        "type": "planned_downtime",
        "component": "availability",
        "impact": (0.05, 0.12),
        "duration": (2, 5),
        "prob": 0.004,
        "tools": ["LITHO_ASML_01", "ETCH_LAM_02", "DEP_AMAT_03", "CMP_EBARA_04", "INSPECT_KLA_05"],
    },
    # ── Performance losses ────────────────────────────────────────────────────
    {
        "name": "Vacuum Leak (Minor Stoppage)",
        "type": "minor_stoppage",
        "component": "performance",
        "impact": (0.06, 0.14),   # reduces speed ratio by this fraction
        "duration": (3, 8),
        "prob": 0.007,
        "tools": ["ETCH_LAM_02", "DEP_AMAT_03"],
    },
    {
        "name": "Pad Wear (Reduced Speed)",
        "type": "reduced_speed",
        "component": "performance",
        "impact": (0.04, 0.10),
        "duration": (5, 12),
        "prob": 0.005,
        "tools": ["CMP_EBARA_04"],
    },
    {
        "name": "Vibration Spike (Reduced Speed)",
        "type": "reduced_speed",
        "component": "performance",
        "impact": (0.03, 0.08),
        "duration": (2, 6),
        "prob": 0.005,
        "tools": ["LITHO_ASML_01", "INSPECT_KLA_05"],
    },
    # ── Quality losses ────────────────────────────────────────────────────────
    {
        "name": "Particle Contamination (Rejects)",
        "type": "rejects_rework",
        "component": "quality",
        "impact": (0.02, 0.06),   # adds this fraction to defect rate
        "duration": (3, 8),
        "prob": 0.004,
        "tools": ["DEP_AMAT_03"],
    },
    {
        "name": "Slurry Imbalance (Rejects)",
        "type": "rejects_rework",
        "component": "quality",
        "impact": (0.02, 0.05),
        "duration": (3, 7),
        "prob": 0.006,
        "tools": ["CMP_EBARA_04"],
    },
    {
        "name": "Reticle Haze (Start-up Yield Loss)",
        "type": "startup_yield_loss",
        "component": "quality",
        "impact": (0.03, 0.07),
        "duration": (2, 5),
        "prob": 0.004,
        "tools": ["LITHO_ASML_01"],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# SHIFT HELPER
# ═══════════════════════════════════════════════════════════════════════════════
def _current_shift() -> str:
    h = datetime.now().hour
    if 6 <= h < 14:
        return "morning"
    if 14 <= h < 22:
        return "afternoon"
    return "night"


# ═══════════════════════════════════════════════════════════════════════════════
# MACHINE SIMULATOR
# Maintains state across windows so loss events persist across multiple messages.
# ═══════════════════════════════════════════════════════════════════════════════
class MachineSimulator:
    """
    Simulates one production window (~30 s) for a single machine.

    State kept between windows:
      active_loss      — the currently active loss event (or None)
      loss_remaining   — how many more windows the active loss will last
      current_lot      — lot ID (rotates every 50 windows)
      window_count     — total windows generated
    """

    def __init__(self, machine_id: str):
        self.machine_id = machine_id
        self.profile = MACHINE_PROFILES[machine_id]
        self.active_loss: dict | None = None
        self.loss_remaining: int = 0
        self.current_lot = f"LOT-{random.randint(1000, 9999)}"
        self.window_count = 0

    # ── internal helpers ──────────────────────────────────────────────────────

    def _maybe_trigger_loss(self):
        """Randomly trigger a new loss event if none is active."""
        for event in LOSS_EVENTS:
            if self.machine_id not in event["tools"]:
                continue
            if random.random() < event["prob"]:
                self.active_loss = event
                self.loss_remaining = random.randint(*event["duration"])
                return

    def _compute_oee_components(self) -> tuple[float, float, float, float, float, float]:
        """
        Return (downtime_min, run_time_min, total_pieces, good_pieces,
                speed_ratio, defect_rate) for this window.

        All values are derived from the machine profile + any active loss,
        then clamped to physically sensible ranges.
        """
        p = self.profile
        planned = p["planned_window_min"]

        # ── base values with small random noise ──────────────────────────────
        downtime_frac = p["base_downtime_pct"] + random.gauss(0, 0.01)
        speed_ratio   = p["base_speed_ratio"]  + random.gauss(0, 0.015)
        defect_rate   = p["base_defect_rate"]  + random.gauss(0, 0.002)

        # ── apply active loss ─────────────────────────────────────────────────
        if self.active_loss:
            impact = random.uniform(*self.active_loss["impact"])
            comp   = self.active_loss["component"]
            if comp == "availability":
                downtime_frac += impact
            elif comp == "performance":
                speed_ratio -= impact
            elif comp == "quality":
                defect_rate += impact

        # ── clamp to sensible ranges ──────────────────────────────────────────
        downtime_frac = max(0.0, min(0.95, downtime_frac))
        speed_ratio   = max(0.1, min(1.05, speed_ratio))   # allow tiny over-speed
        defect_rate   = max(0.0, min(0.50, defect_rate))

        # ── derive time values ────────────────────────────────────────────────
        downtime_min = round(planned * downtime_frac, 4)
        run_time_min = round(planned - downtime_min, 4)

        # ── derive piece counts ───────────────────────────────────────────────
        # How many pieces *could* be made at ideal speed during run time?
        ideal_pieces = run_time_min / p["ideal_cycle_time_min"]
        # Actual pieces = ideal × speed_ratio (performance loss)
        total_pieces = max(0.0, round(ideal_pieces * speed_ratio, 2))
        good_pieces  = max(0.0, round(total_pieces * (1 - defect_rate), 2))

        return downtime_min, run_time_min, total_pieces, good_pieces, speed_ratio, defect_rate

    # ── public API ────────────────────────────────────────────────────────────

    def next_window(self) -> dict:
        """
        Generate one OEE message for the next production window.

        Returns a dict ready to be JSON-serialised and sent to Kafka.
        """
        # Rotate lot every 50 windows
        if self.window_count % 50 == 0 and self.window_count > 0:
            self.current_lot = f"LOT-{random.randint(1000, 9999)}"

        # Advance loss state
        if self.active_loss:
            self.loss_remaining -= 1
            if self.loss_remaining <= 0:
                self.active_loss = None
        else:
            self._maybe_trigger_loss()

        p = self.profile
        planned = p["planned_window_min"]

        downtime_min, run_time_min, total_pieces, good_pieces, _, _ = (
            self._compute_oee_components()
        )

        # ── OEE formula (Kennedy) ─────────────────────────────────────────────
        #
        #   Availability = Run Time / Planned Production Time
        #   Performance  = (Ideal Cycle Time × Total Pieces) / Run Time
        #   Quality      = Good Pieces / Total Pieces
        #   OEE          = A × P × Q  (all as fractions, then × 100 for %)
        #
        availability = (run_time_min / planned) * 100 if planned > 0 else 0.0

        performance = (
            (p["ideal_cycle_time_min"] * total_pieces / run_time_min) * 100
            if run_time_min > 0 and total_pieces > 0
            else 0.0
        )

        quality = (good_pieces / total_pieces) * 100 if total_pieces > 0 else 0.0

        oee = (availability * performance * quality) / 10_000

        # Clamp all to [0, 100]
        availability = round(max(0.0, min(100.0, availability)), 2)
        performance  = round(max(0.0, min(100.0, performance)),  2)
        quality      = round(max(0.0, min(100.0, quality)),      2)
        oee          = round(max(0.0, min(100.0, oee)),          2)

        # ── loss category ─────────────────────────────────────────────────────
        if self.active_loss:
            loss_category = {
                "name":      self.active_loss["name"],
                "type":      self.active_loss["type"],
                "component": self.active_loss["component"],
            }
        else:
            loss_category = {"name": "none", "type": "none", "component": "none"}

        self.window_count += 1

        return {
            "machine_id":                  self.machine_id,
            "message_id":                  str(uuid.uuid4()),
            "timestamp":                   time.time(),
            "shift":                       _current_shift(),
            "lot_id":                      self.current_lot,

            # Raw inputs — stored so Spark can re-derive OEE if needed
            "planned_production_time_min": round(planned, 4),
            "downtime_min":                round(downtime_min, 4),
            "ideal_cycle_time_min":        round(p["ideal_cycle_time_min"], 4),
            "total_pieces_run":            round(total_pieces, 2),
            "good_pieces":                 round(good_pieces, 2),

            # Derived OEE components
            "availability": availability,
            "performance":  performance,
            "quality":      quality,
            "oee":          oee,

            # Active loss (one of the 7 OEE losses, or "none")
            "loss_category": loss_category,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# KAFKA SETUP
# ═══════════════════════════════════════════════════════════════════════════════
_kafka_config = {
    "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", ""),
    "security.protocol": "SASL_SSL",
    "sasl.mechanisms":   "PLAIN",
    "sasl.username":     os.getenv("KAFKA_SASL_USERNAME", ""),
    "sasl.password":     os.getenv("KAFKA_SASL_PASSWORD", ""),
}
TOPIC = "OEE_0"

producer = Producer(_kafka_config)
simulators = {m: MachineSimulator(m) for m in MACHINE_PROFILES}


def _on_delivery(err, msg):
    if err:
        print(f"  ❌ Delivery failed [{msg.topic()}]: {err}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════
print("🚀 OEE Producer started")
print(f"   Machines : {', '.join(MACHINE_PROFILES)}")
print(f"   Topic    : {TOPIC}")
print(f"   Interval : 0.5 s per cycle (all machines)\n")

_cycle = 0

try:
    while True:
        _cycle += 1
        for machine_id, sim in simulators.items():
            window = sim.next_window()

            try:
                payload = json.dumps(window).encode("utf-8")
                validate_message(payload)
                producer.produce(
                    TOPIC,
                    key=machine_id.encode("utf-8"),
                    value=payload,
                    callback=_on_delivery,
                )
            except SchemaValidationError as exc:
                print(f"  ⚠️  Schema error [{machine_id}]: {exc}")

        producer.poll(0)

        # Print a summary every 50 cycles (~25 s) instead of every message.
        # This keeps the log clean while still showing the system is alive.
        if _cycle % 50 == 0:
            sample = simulators[list(simulators)[0]].next_window()
            print(
                f"  [cycle {_cycle:>6}] "
                f"sample {list(simulators)[0]:18} | "
                f"OEE {sample['oee']:5.1f}%  "
                f"A={sample['availability']:5.1f}%  "
                f"P={sample['performance']:5.1f}%  "
                f"Q={sample['quality']:5.1f}%"
            )

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\n⏹  Stopped by user.")
finally:
    producer.flush()
    print("✅ Producer flushed and exited.")
