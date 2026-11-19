"""Read-only device faults and a bounded, persistent local incident journal.

No reset opcode is known. 'Seen' acknowledges the notification, never a device.
"""
import datetime
import json
import logging
import uuid

LOG = logging.getLogger(__name__)
SUFFIX = "-0004-0001-0000-0000fe088214"
FAULT_CHARACTERISTIC = "00000108" + SUFFIX
FAULT_SERVICES = {"panel": "00030000" + SUFFIX, "heater": "00010000" + SUFFIX,
                  "ac1": "00020000" + SUFFIX, "ac2": "00021000" + SUFFIX,
                  "schaudt": "00040000" + SUFFIX}
DEVICE_NAMES = {"panel": "Bedienpanel", "heater": "Heizung", "ac1": "Klimaanlage 1",
                "ac2": "Klimaanlage 2", "schaudt": "Schaudt", "command": "Steuerbefehl"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def decode_fault(raw):
    """Original app: byte 1=warning, 2=error; remaining char codes, trim NULs.

    An unknown severity stays an active unknown fault, never a clean result.
    Control characters and overlong payloads are rejected, not silently cleared.
    """
    raw = bytes(raw)
    if len(raw) > 512:
        raise ValueError("Fehlermeldung zu lang")
    raw = raw.rstrip(b"\0")
    if not raw:
        return None
    text = raw[1:].decode("latin-1")
    if any(ord(c) < 32 or 127 <= ord(c) < 160 for c in text):
        raise ValueError("Ungültige Zeichen in Fehlermeldung")
    return {"severity": {1: "warning", 2: "error"}.get(raw[0], "unknown"),
            "code": text or "Code nicht angegeben", "raw_severity": raw[0]}


class FaultJournal:
    def __init__(self, path):
        self.path = path
        self.active = {}
        self.history = []
        self.event = {"id": "none", "message": "", "title": "Truma"}
        self.readings = {}
        self.checked = None
        try:
            saved = json.loads(path.read_text())
            if saved.get("version") == 1:
                active, history, event = saved["active"], saved["history"], saved["event"]
                if not isinstance(active, dict) or not isinstance(history, list) or not isinstance(event, dict):
                    raise ValueError("Ungültiges Meldungsjournal")
                self.active, self.history, self.event = active, history[-30:], event
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def save(self):
        try:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps({"version": 1, "active": self.active,
                "history": self.history[-30:], "event": self.event}, ensure_ascii=False))
            temp.replace(self.path)
        except OSError:
            LOG.exception("Could not persist fault journal")

    def record(self, incident, change, stamp):
        self.history.append({**incident, "change": change, "at": stamp})
        self.history = self.history[-30:]

    def changed(self, lines):
        if lines:
            self.event = {"id": uuid.uuid4().hex, "title": "Truma · Meldungen",
                          "message": "\n".join(lines), "at": now()}
            self.save()

    def update(self, readings):
        # Missing/failed sources retain the old incident; only a successful
        # empty read can resolve it. Read success is deliberately not persisted.
        self.readings = readings
        self.checked = now()
        lines = []
        for source, reading in readings.items():
            if reading["status"] != "ok":
                continue
            new, old = reading["fault"], self.active.get(source)
            if old and new and all(old.get(k) == new.get(k) for k in ("code", "severity", "raw_severity")):
                continue
            if old:
                self.record(old, "resolved", self.checked)
                del self.active[source]
                lines.append(f"{old['device']}: {old['code']} wird nicht mehr gemeldet.")
            if new:
                incident = {**new, "id": uuid.uuid4().hex, "source": source,
                            "device": DEVICE_NAMES[source], "occurred": self.checked, "seen": None}
                self.active[source] = incident
                self.record(incident, "occurred", self.checked)
                level = {"warning": "Warnung", "error": "Störung"}.get(new["severity"], "Unbekannte Meldung")
                lines.append(f"{incident['device']}: {level} {incident['code']}. Bitte am Bedienpanel prüfen.")
        self.changed(lines)

    def command_failed(self, message):
        message = str(message)[:200]
        old = self.active.get("command")
        if old and old["code"] == message and not old["seen"]:
            return
        incident = {"id": uuid.uuid4().hex, "source": "command", "device": "Steuerbefehl",
                    "severity": "command", "code": message, "occurred": now(), "seen": None}
        self.active["command"] = incident
        self.record(incident, "occurred", incident["occurred"])
        self.changed(["Steuerbefehl nicht bestätigt: " + message + ". Kein automatischer Wiederholungsversuch."])

    def mark_seen(self):
        stamp = now()
        for incident in self.active.values():
            if not incident["seen"]:
                incident["seen"] = stamp
                self.record(incident, "seen", stamp)
        # A failed command is a past event, not an ongoing device fault.
        self.active.pop("command", None)
        self.save()

    def view(self, connected):
        active = [{**v, "stale": k != "command" and
                   (not connected or self.readings.get(k, {}).get("status") != "ok")}
                  for k, v in self.active.items()]
        monitored = [k for k, v in self.readings.items() if v["status"] == "ok"]
        fresh = connected and "heater" in monitored and all(v["status"] in ("ok", "unsupported")
                                                           for v in self.readings.values())
        if active:
            summary = "Störung" if any(v["severity"] == "error" for v in active) else "Meldung vorhanden"
        else:
            summary = "Keine gemeldete Störung" if fresh else "Fehlerstatus unbekannt"
        return {"summary": summary, "fresh": fresh, "checked": self.checked,
                "active": active, "history": self.history[-30:], "sources": self.readings,
                "reset_supported": False, "event": self.event}
