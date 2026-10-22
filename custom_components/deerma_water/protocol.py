"""Pure, testable protocol helpers. No guessed temperature or ice codes."""
import json
import math
import re

def first_present(data, *keys):
    return next((data[k] for k in keys if k in data and data[k] is not None), None)

def device_id(device):
    return str(first_present(device.get("device", {}), "id") or first_present(device, "device_id", "id") or "")

def enum_mapping(device, field):
    for attr in device.get("showAttributes", []):
        if not isinstance(attr, dict) or attr.get("id") != field:
            continue
        result = {}
        mapping = attr.get("valueMapping", {})
        if not isinstance(mapping, dict):
            return result
        for code, label in mapping.items():
            if not re.fullmatch(r"[0-9]{1,6}", str(code)):
                continue
            if isinstance(label, dict):
                label = label.get("zh-CN") or label.get("en")
            if isinstance(label, (str, int, float)):
                result[str(label)] = int(code)
        # Ambiguous labels cannot safely represent two different commands.
        if len(result) != len(mapping):
            return {}
        return result
    return {}

def desired_payload(field, value, identifier):
    if field not in ("SetTemp", "SetOutlet") or type(value) is not int or not 0 <= value <= 999999:
        raise ValueError("Unsupported command")
    return {"state": {"desired": {field: value, "CommandType": "app", "EnduserId": identifier}}}

# Diagnostic export is built from an allowlist; account/device metadata is never copied.
_PUBLIC_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
_PRIVATE = re.compile(r"token|secret|pass|account|user|serial|address|phone|email|uuid|client|endpoint|host|mac|wifi|ssid|registration|(^id$)|id$", re.I)
_ICE_FIELD = re.compile(r"ice|cool|cold|crush|freeze", re.I)
_KNOWN = {"SetTemp", "SetOutlet", "TapWaterTDS", "TDS", "AQPLife", "PC5IN1Life", "PC5IN1FilterLife", "PC5in1FilterLife", "PC5in1FilterTime", "PC5in1FilterWater", "filter1Life", "filter2Life",
          "WarmWaterSet", "HotWaterSet", "TotalOutlet", "InputTemp", "RefrigerationStatus",
          "LockKeySet", "TouchBuzzerSet", "NightModeSet", "SmallVolume"}

def diagnostics_snapshot(device, state):
    schema, values = {}, {}
    for key, value in state.items():
        if not isinstance(key, str) or not _PUBLIC_FIELD.fullmatch(key) or _PRIVATE.search(key):
            continue
        # Unknown values are omitted, even if the field name looks harmless.
        schema[key] = type(value).__name__
        if (key in _KNOWN or _ICE_FIELD.search(key)) and (type(value) is bool or (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1000000)):
            values[key] = value
    enums = {}
    for field in ("SetTemp", "SetOutlet"):
        # Only unit labels can leave the machine. No arbitrary cloud strings.
        enums[field] = {label: code for label, code in enum_mapping(device, field).items()
                        if re.fullmatch(r"(?:常温|Normal|Ambient|[0-9]{1,4}(?:℃|°C|mL|ml))", label)}
    return {"schema_version": 2, "control_mappings": enums,
            "reported_field_types": schema, "reported_numeric_values": values}

# MQTT 3.1.1 framing; adapted from upstream, with stream buffering and strict bounds.
def mqtt_string(value):
    raw = value.encode('utf-8')
    if len(raw) > 65535: raise ValueError("MQTT string too long")
    return len(raw).to_bytes(2, 'big') + raw

def packet(kind, body=b''):
    n, encoded = len(body), bytearray()
    if n > 1048576: raise ValueError("Packet too large")
    while True:
        byte = n % 128
        n //= 128
        encoded.append(byte | (128 if n else 0))
        if not n: break
    return bytes([kind]) + bytes(encoded) + body

def extract_packets(buffer):
    result = []
    while len(buffer) >= 2:
        size, multiplier, index = 0, 1, 1
        while True:
            if index >= len(buffer): return result
            byte = buffer[index]; index += 1
            size += (byte & 127) * multiplier
            if not byte & 128: break
            if index == 5: raise ValueError("Invalid remaining length")
            multiplier *= 128
        if size > 1048576: raise ValueError("Packet too large")
        if len(buffer) < index + size: return result
        result.append((buffer[0], bytes(buffer[index:index+size])))
        del buffer[:index+size]
    return result

def parse_publish(header, body):
    if len(body) < 2: raise ValueError("Truncated topic")
    size = int.from_bytes(body[:2], 'big'); end = 2 + size
    qos = (header >> 1) & 3
    if qos > 1 or len(body) < end + (2 if qos else 0): raise ValueError("Invalid publish")
    topic = body[2:end].decode('utf-8')
    ack = body[end:end+2] if qos else None
    data = json.loads(body[end+(2 if qos else 0):])
    return topic, data, ack


# Read-only observations from four labelled i2 Pro snapshots, not a write contract.
I2PRO_COOLING_MODES = {
    (0, 0): "关闭",
    (0, 1): "仅冰水",
    (1, 1): "小冰和冰水",
    (2, 1): "大冰和冰水",
}

def i2pro_cooling_mode(state):
    ice, water = state.get("IceCubeMode"), state.get("IceWaterMode")
    if type(ice) is not int or type(water) is not int:
        return None
    return I2PRO_COOLING_MODES.get((ice, water))


def has_i2pro_fields(state):
    """Feature signature observed on the tested i2 Pro, not universal model ID."""
    return all(type(state.get(k)) is int for k in
               ("IceCubeMode", "IceWaterMode", "TouchBuzzerSet", "PC5in1FilterLife"))

# User confirmed the full App click order against the b4 desired/report trace.
I2PRO_PRESETS = {
    "SetTemp": {"冰水":199, "凉水":198, "常温":200, "45℃":201,
                "55℃":202, "75℃":205, "85℃":203, "100℃":204},
    "SetOutlet": {"120 mL":8999, "150 mL":9000, "250 mL":9001,
                  "350 mL":9002, "500 mL":9003, "800 mL":9004, "连续":9999},
}

def i2pro_preset_value(field, label):
    if field not in I2PRO_PRESETS or label not in I2PRO_PRESETS[field]:
        raise ValueError("Unknown preset")
    return I2PRO_PRESETS[field][label]


def i2pro_desired_payload(values, identifier):
    """Limited beta write set backed by labelled desired/report observations."""
    if not isinstance(values, dict) or any(type(v) is not int for v in values.values()):
        raise ValueError("Invalid values")
    if set(values) == {"IceCubeMode", "IceWaterMode"}:
        if (values["IceCubeMode"], values["IceWaterMode"]) not in I2PRO_COOLING_MODES:
            raise ValueError("Unsupported mode combination")
    elif set(values) == {"TouchBuzzerSet"}:
        if values["TouchBuzzerSet"] not in (0, 1):
            raise ValueError("Unsupported buzzer value")
    elif len(values) == 1 and next(iter(values)) in I2PRO_PRESETS:
        field = next(iter(values))
        if values[field] not in I2PRO_PRESETS[field].values():
            raise ValueError("Unsupported preset code")
    else:
        raise ValueError("Unverified command")
    return {"state": {"desired": {**values, "CommandType": "app", "EnduserId": identifier}}}
