import time
import math
import random

# Antigravity Simulation State
_state = {
    "stability": 87.0,
    "mode": "Stable",
    "field_strength": 72.0,
    "rotation_rpm": 1200,
    "phase": 0.0,
}

_MODES = ["Stable", "Boost", "Parallel", "Critical"]

def _update_physics():
    """One tick of physics simulation."""
    s = _state
    s["phase"] = (s["phase"] + 0.05) % (2 * math.pi)

    # Field strength oscillates
    s["field_strength"] = 65 + 20 * math.sin(s["phase"]) + random.uniform(-2, 2)

    # Stability follows field strength with noise
    s["stability"] = max(5, min(100, s["field_strength"] * 1.2 + random.uniform(-3, 3)))

    # Rotation reacts to field
    s["rotation_rpm"] = int(900 + 600 * (s["field_strength"] / 85) + random.randint(-20, 20))

    # Mode depends on stability
    stab = s["stability"]
    if stab > 85:   s["mode"] = "Stable"
    elif stab > 65: s["mode"] = "Boost"
    elif stab > 40: s["mode"] = "Parallel"
    else:           s["mode"] = "Critical"


def get_antigravity_state():
    _update_physics()
    return dict(_state)
