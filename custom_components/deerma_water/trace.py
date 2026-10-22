"""Opt-in, bounded in-memory observations; never saves raw payloads."""
import time

FIELDS = frozenset({
    "IceCubeMode", "IceWaterMode", "IceCubeStatus", "IceWaterStatus",
    "RefrigerationStatus", "SetTemp", "SetOutlet", "IceWaterSet",
    "WarmWaterSet", "HotWaterSet", "Outlet120Set", "Outlet350Set", "Outlet800Set",
    "LockKeySet", "TouchBuzzerSet", "SmallVolume", "NightModeSet",
    "NightModeNoSound", "NightModeNoProduce", "NightModeNoCooling", "NightModeOpenLight",
    "NightModeStartHour", "NightModeStartMinute", "NightModeEndHour", "NightModeEndMinute",
    "AwayModeState", "HomeModeState", "PC5in1FilterLife", "PC5in1FilterTime",
    "PC5in1FilterWater", "InputTemp", "TotalOutlet", "TDS",
})

def numeric_fields(state):
    if not isinstance(state, dict):
        return {}
    return {key: value for key, value in state.items()
            if key in FIELDS and type(value) is int and -1000000 <= value <= 1000000}

class ControlTrace:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = None
        self.events = []
        self.previous = {}
        self.dropped = 0

    @property
    def active(self):
        return self.started is not None and self.clock() - self.started < 300

    def start(self, reported):
        self.started = self.clock()
        self.events = []
        self.previous = {}
        self.dropped = 0
        self.record("baseline_reported", reported)

    def record(self, source, state):
        if not self.active or source not in ("baseline_reported", "reported", "desired_snapshot"):
            return
        clean = numeric_fields(state)
        if source in ("baseline_reported", "reported"):
            changed = {k:v for k,v in clean.items() if self.previous.get(k) != v}
            self.previous.update(clean)
            clean = changed
        if not clean:
            return
        if len(self.events) >= 200:
            self.dropped += 1
            return
        self.events.append({"seconds": round(self.clock()-self.started, 1),
                            "source": source, "values": clean})

    def snapshot(self):
        return {"active": self.active, "duration_seconds": 300,
                "dropped_events": self.dropped,
                "events": [{**event, "values": dict(event["values"])} for event in self.events],
                "note": "desired_snapshot is a cloud snapshot, not proof of sender or original command"}
