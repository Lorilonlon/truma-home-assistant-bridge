"""Classic iNet/CP-plus timer, independent of the current heating settings.

Field mappings and codecs: original iNet System 5.1.1 ARM32 snapshot,
TimerSettingsBase.heaterDefinitions/defaultDefinitions and BluetoothTimeAttribute.
See TIMER_PROTOCOL.md for evidence and remaining hardware validation.
"""
import re

from .protocol import FANS, WATER, decode_choice, decode_temperature, encode_temperature

TIMER_CHARACTERISTICS = {
    "timer_enabled": "00000200-0004-0001-0000-0000fe088214",
    "timer_time": "00000205-0004-0001-0000-0000fe088214",
    "timer_temperature": "0001000d-0004-0001-0000-0000fe088214",
    "timer_fan": "0001000e-0004-0001-0000-0000fe088214",
    "timer_power": "0001000f-0004-0001-0000-0000fe088214",
    "timer_water": "00010010-0004-0001-0000-0000fe088214",
    "timer_water_power": "00010011-0004-0001-0000-0000fe088214",
    "timer_energy": "00010012-0004-0001-0000-0000fe088214",
    "timer_water_energy": "00010013-0004-0001-0000-0000fe088214",
}
# Energy settings are read and preserved; this first implementation does not
# change fuel/power selection or the ordinary heater target characteristic.
TIMER_WRITABLE = frozenset({"timer_enabled", "timer_time", "timer_temperature",
                            "timer_fan", "timer_water"})
TIMER_COMMANDS = frozenset({"timer_enabled", "timer_start", "timer_stop",
                            "timer_temperature", "timer_fan", "timer_water"})


def decode_enabled(payload):
    # An empty byte array is not confirmed OFF. GVariant's printed b'' can
    # also represent a NUL-terminated bytestring; decode actual D-Bus bytes.
    if payload == b"":
        return None
    if payload == b"\x00":
        return False
    if payload == b"\x01":
        return True
    raise ValueError("Unbekannter Timer-Schaltzustand")


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Timerzeit bitte als HH:MM angeben (00:00 bis 23:59).")
    hour, minute = map(int, value.split(":"))
    return hour, minute


def encode_times(start, stop):
    sh, sm = parse_time(start)
    eh, em = parse_time(stop)
    return bytes((sm, sh, em, eh))


def decode_times(payload):
    if len(payload) != 4:
        raise ValueError("Ungültige Länge der Timerzeiten")
    sm, sh, em, eh = payload
    if sm > 59 or em > 59 or sh > 23 or eh > 23:
        raise ValueError("Ungültige Timerzeit aus der Box")
    return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"


def decode_timer(values):
    start, stop = decode_times(values["timer_time"])
    state = {"enabled": decode_enabled(values["timer_enabled"]), "start": start, "stop": stop,
             "temperature": decode_temperature(values["timer_temperature"]),
             "fan": decode_choice(values["timer_fan"], FANS),
             "water": decode_choice(values["timer_water"], WATER)}
    for name in ("power", "water_power", "energy", "water_energy"):
        raw = values["timer_" + name]
        if len(raw) not in (1, 2):
            raise ValueError("Ungültige Timer-Energieeinstellung")
        state[name] = int.from_bytes(raw, "little")
    return state


def timer_write(kind, value, state):
    """One explicit write. Configuration edits never enable the timer.

    CP-plus can change independently of our lock. Require a disabled timer
    while editing, and merge a single requested change with a fresh read.
    """
    if kind == "timer_enabled":
        if value not in ("ON", "OFF"):
            raise ValueError("Unbekannter Timerbefehl")
        if value == "OFF":
            return "timer_enabled", b"\x00"
        if state["start"] == state["stop"]:
            raise ValueError("Start und Ende müssen verschieden sein.")
        if state["temperature"] is None and state["water"] == "Aus":
            raise ValueError("Bitte zuerst Timer-Temperatur oder Warmwasser einstellen.")
        if state["water"] not in WATER.values() or state["fan"] not in FANS.values():
            raise ValueError("Unbekannte Timer-Betriebseinstellung")
        if state["temperature"] is not None and state["fan"] not in ("Eco", "High"):
            raise ValueError("Bitte zuerst Eco oder High für das Timer-Gebläse wählen.")
        if (state["energy"], state["water_energy"], state["power"], state["water_power"]) != (1, 1, 0, 0):
            raise ValueError("Aktivieren ist bisher nur für Combi 6 mit Gasbetrieb vorbereitet.")
        return "timer_enabled", b"\x01"
    if kind not in TIMER_COMMANDS:
        raise ValueError("Unbekannter Timerbefehl")
    if state["enabled"] is not False:
        raise ValueError("Timer zuerst ausschalten, Einstellungen ändern und danach bewusst einschalten.")
    if kind in ("timer_start", "timer_stop"):
        start = value if kind == "timer_start" else state["start"]
        stop = value if kind == "timer_stop" else state["stop"]
        return "timer_time", encode_times(start, stop)
    if kind == "timer_temperature":
        return kind, b"\x00\x00" if value == "Aus" else encode_temperature(value)
    choices = FANS if kind == "timer_fan" else WATER
    raw = next((raw for raw, label in choices.items() if label == value), None)
    if raw is None:
        raise ValueError("Unbekannte Timer-Betriebseinstellung")
    return kind, raw.to_bytes(1 if kind == "timer_fan" else 2, "little")


def timer_reply_matches(field, expected, actual):
    if field in ("timer_enabled", "timer_time"):
        return expected == actual
    return len(actual) in (1, 2) and int.from_bytes(expected, "little") == int.from_bytes(actual, "little")
