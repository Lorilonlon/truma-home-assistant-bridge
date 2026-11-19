import asyncio
import json
import logging
import ssl
import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)

class MQTT:
    def __init__(self, bridge, options):
        self.bridge, self.options = bridge, options
        self.uid = "truma_" + options["box_address"].replace(":", "").lower()
        self.base = "truma_inet/" + self.uid
        self.client = None
        self.connected = False
        self.published = {}
        self.loop = asyncio.get_running_loop()

    def start(self):
        if not self.options.get("mqtt_host"):
            return
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=self.uid + "_bridge", clean_session=True)
        if self.options.get("mqtt_username"):
            self.client.username_pw_set(self.options["mqtt_username"], self.options.get("mqtt_password", ""))
        if self.options.get("mqtt_tls", True):
            ctx = ssl.create_default_context()
            if self.options.get("mqtt_ca"):
                ctx.load_verify_locations(cadata=self.options["mqtt_ca"])
            if self.options.get("mqtt_insecure", False):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self.client.tls_set_context(ctx)
        self.client.will_set(self.base + "/bridge", "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(2, 60)
        self.client.connect_async(self.options["mqtt_host"], self.options.get("mqtt_port", 8883), 30)
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.warning("MQTT connection rejected: %s", reason)
            return
        self.connected = True
        client.subscribe(self.base + "/set/+", qos=0)
        client.subscribe("homeassistant/status", qos=0)
        self.loop.call_soon_threadsafe(self.announce)

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.connected = False

    def on_message(self, client, userdata, msg):
        if msg.topic == "homeassistant/status":
            if msg.payload == b"online":
                self.loop.call_soon_threadsafe(self.announce)
            return
        # Commands are non-retained, non-queued and short lived. Never accept
        # broker-restored commands following a bridge or HA restart.
        if msg.retain or len(msg.payload) > 128:
            return
        try:
            kind = msg.topic.rsplit("/", 1)[-1]
            value = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        generation = self.bridge.generation
        self.loop.call_soon_threadsafe(self.bridge.schedule_command, kind, value, generation)

    def publish(self, topic, payload, retain=True):
        if self.client and self.connected:
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            if retain and self.published.get(topic) == payload:
                return
            result = self.client.publish(topic, payload, qos=1, retain=retain)
            if retain and result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.published[topic] = payload

    def availability(self, control=False):
        result = [{"topic": self.base + "/bridge"}]
        if control:
            result.append({"topic": self.base + "/control"})
        return {"availability": result, "availability_mode": "all"}

    def announce(self):
        self.published.clear()
        device = {"identifiers": [self.uid], "name": "Truma iNet", "manufacturer": "Truma",
                  "model": "iNet Box / Combi 6"}
        items = {
            "climate/heizung": {
                "name": "Heizung", "modes": ["off", "heat"], "min_temp": 5, "max_temp": 30,
                "temp_step": 1, "precision": 0.1, "temperature_unit": "C", "optimistic": False,
                "mode_command_topic": self.base + "/set/mode",
                "mode_state_topic": self.base + "/state", "mode_state_template": "{{ value_json.mode }}",
                "temperature_command_topic": self.base + "/set/temperature",
                "temperature_state_topic": self.base + "/state",
                "temperature_state_template": "{{ value_json.target if value_json.target is not none else 'None' }}",
                "current_temperature_topic": self.base + "/state",
                "current_temperature_template": "{{ value_json.get('current_temperature') if value_json.get('current_temperature') is not none else 'None' }}",
                "fan_modes": ["Eco", "High"], "fan_mode_command_topic": self.base + "/set/fan",
                "fan_mode_state_topic": self.base + "/state",
                "fan_mode_state_template": "{{ value_json.fan if value_json.fan in ['Eco', 'High'] else 'None' }}",
                **self.availability(True)},
            "select/warmwasser": {
                "name": "Warmwasser", "icon": "mdi:water-boiler", "options": ["Aus", "Niedrig", "Hoch", "Boost"],
                "command_topic": self.base + "/set/water", "state_topic": self.base + "/state",
                "value_template": "{{ value_json.water if value_json.water in ['Aus', 'Niedrig', 'Hoch', 'Boost'] else 'None' }}",
                "optimistic": False, **self.availability(True)},
            "binary_sensor/verbindung": {
                "name": "Verbindung", "device_class": "connectivity", "state_topic": self.base + "/connection",
                "payload_on": "online", "payload_off": "offline", **self.availability()},
            "sensor/status": {
                "name": "Status", "icon": "mdi:information-outline", "state_topic": self.base + "/status",
                **self.availability()},
            "sensor/letzte_aktualisierung": {
                "name": "Letzte Aktualisierung", "device_class": "timestamp",
                "state_topic": self.base + "/updated", "entity_category": "diagnostic", **self.availability()},
            "sensor/solltemperatur": {
                "name": "Solltemperatur", "unit_of_measurement": "°C", "device_class": "temperature",
                "state_topic": self.base + "/state", "value_template": "{{ value_json.target if value_json.target is not none else 'None' }}",
                "availability": [{"topic": self.base + "/bridge"}, {"topic": self.base + "/connection"}],
                "availability_mode": "all"},
            "sensor/heizmodus": {
                "name": "Heizmodus", "icon": "mdi:radiator", "state_topic": self.base + "/state",
                "value_template": "{{ 'Heizen' if value_json.mode == 'heat' else 'Aus' }}",
                "availability": [{"topic": self.base + "/bridge"}, {"topic": self.base + "/connection"}],
                "availability_mode": "all"},
            "sensor/warmwasserstatus": {
                "name": "Warmwasserstatus", "icon": "mdi:water-boiler", "state_topic": self.base + "/state",
                "value_template": "{{ value_json.water }}",
                "availability": [{"topic": self.base + "/bridge"}, {"topic": self.base + "/connection"}],
                "availability_mode": "all"},
        }
        for field, name, unit, device_class in (
                ("current_temperature", "Raumtemperatur", "°C", "temperature"),
                ("voltage", "Versorgungsspannung", "V", "voltage"),
                ("water_temperature", "Wassertemperatur", "°C", "temperature")):
            items["sensor/" + field] = {
                "name": name, "unit_of_measurement": unit, "device_class": device_class,
                "state_class": "measurement", "suggested_display_precision": 1,
                "state_topic": self.base + "/state",
                "value_template": "{{ value_json.get('" + field + "') if value_json.get('" + field + "') is not none else 'None' }}",
                "availability": [{"topic": self.base + "/bridge"}, {"topic": self.base + "/connection"}],
                "availability_mode": "all"}
        timer_availability = {"availability": [{"topic": self.base + "/bridge"},
                                               {"topic": self.base + "/timer/available"}],
                              "availability_mode": "all"}
        items["sensor/meldungen"] = {
            "name": "Meldungen", "icon": "mdi:alert-circle-outline",
            "state_topic": self.base + "/faults", "value_template": "{{ value_json.summary }}",
            "json_attributes_topic": self.base + "/faults", **self.availability()}
        items["sensor/meldeereignis"] = {
            "name": "Meldeereignis", "icon": "mdi:message-alert-outline", "entity_category": "diagnostic",
            "state_topic": self.base + "/fault-event", "value_template": "{{ value_json.id }}",
            "json_attributes_topic": self.base + "/fault-event", **self.availability()}
        items["button/meldungen_gesehen"] = {
            "name": "Meldungen gesehen", "icon": "mdi:check", "payload_press": "seen",
            "command_topic": self.base + "/set/fault_seen", **self.availability()}
        timer_control = {"availability": [{"topic": self.base + "/bridge"},
                                          {"topic": self.base + "/timer/control"}],
                         "availability_mode": "all"}
        items["sensor/timer"] = {
            "name": "Timer", "icon": "mdi:clock-outline", "state_topic": self.base + "/timer/state",
            "value_template": "{{ 'Aktiv' if value_json.enabled == true else 'Aus' if value_json.enabled == false else 'Nicht eingerichtet' }}",
            "json_attributes_topic": self.base + "/timer/state", **timer_availability}
        items["switch/timer"] = {
            "name": "Timer aktiv", "icon": "mdi:clock-check-outline", "optimistic": False,
            "command_topic": self.base + "/set/timer_enabled", "state_topic": self.base + "/timer/state",
            "value_template": "{{ 'ON' if value_json.enabled == true else 'OFF' if value_json.enabled == false else 'None' }}",
            **timer_control}
        items["button/timer_off"] = {
            "name": "Timer ausschalten", "icon": "mdi:clock-remove-outline", "payload_press": "OFF",
            "command_topic": self.base + "/set/timer_enabled",
            "availability": [{"topic": self.base + "/bridge"}, {"topic": self.base + "/timer/stop"}],
            "availability_mode": "all"}
        for field, name in (("start", "Timer Beginn"), ("stop", "Timer Ende")):
            items["text/timer_" + field] = {
                "name": name, "icon": "mdi:clock-outline", "mode": "text", "min": 5, "max": 5,
                "pattern": r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", "optimistic": False,
                "command_topic": self.base + "/set/timer_" + field,
                "state_topic": self.base + "/timer/state",
                "value_template": "{{ value_json." + field + " }}", **timer_control}
        for field, name, options in (
                ("temperature", "Timer Raumtemperatur", ["Aus"] + [str(t) for t in range(5, 31)]),
                ("fan", "Timer Gebläse", ["Aus", "Eco", "High"]),
                ("water", "Timer Warmwasser", ["Aus", "Niedrig", "Hoch", "Boost"])):
            items["select/timer_" + field] = {
                "name": name, "options": options, "optimistic": False,
                "command_topic": self.base + "/set/timer_" + field,
                "state_topic": self.base + "/timer/state",
                "value_template": ("{{ value_json.temperature | string if value_json.temperature is not none else 'Aus' }}"
                                   if field == "temperature" else "{{ value_json." + field +
                                   " if value_json." + field + " in " + repr(options) + " else 'None' }}"),
                **timer_control}
        for key, config in items.items():
            domain, name = key.split("/")
            self.publish(f"homeassistant/{domain}/{self.uid}/{name}/config", {
                "unique_id": f"{self.uid}_{name}", "default_entity_id": f"{domain}.truma_inet_{name}",
                "device": device, **config})
        # Availability first stays offline until a complete live read succeeds.
        self.update()
        self.publish(self.base + "/bridge", "online")

    def update(self):
        b = self.bridge
        self.publish(self.base + "/connection", "online" if b.ready else "offline")
        self.publish(self.base + "/control", "online" if b.ready and b.options["allow_control"] else "offline")
        self.publish(self.base + "/status", b.status[:250])
        journal = getattr(b, "faults", None)
        if journal:
            self.publish(self.base + "/faults", journal.view(b.ready))
            self.publish(self.base + "/fault-event", journal.event)
        timer = getattr(b, "timer", None)
        timer_ready = b.ready and timer is not None
        timer_writable = bool(getattr(getattr(b, "backend", None), "timer_writable", False))
        stop_available = (b.ready and b.options["allow_control"] and
                          b.options.get("allow_timer_control", False) and timer_writable)
        if timer_ready:
            # Populate HH:MM values before making text entities available.
            # Otherwise HA can validate a previous null as too short (min=5).
            self.publish(self.base + "/timer/state", timer)
            self.publish(self.base + "/timer/available", "online")
            self.publish(self.base + "/timer/control", "online" if stop_available else "offline")
        else:
            # Never leave old timer values actionable after a failed read.
            self.publish(self.base + "/timer/available", "offline")
            self.publish(self.base + "/timer/control", "offline")
            self.publish(self.base + "/timer/state", {"enabled": None, "start": None,
                         "stop": None, "temperature": None, "fan": "Unbekannt", "water": "Unbekannt"})
        self.publish(self.base + "/timer/stop", "online" if stop_available else "offline")
        if b.ready:
            self.publish(self.base + "/state", b.state)
            self.publish(self.base + "/updated", b.updated)

    def stop(self):
        if self.client:
            result = self.client.publish(self.base + "/bridge", "offline", qos=1, retain=True)
            if self.connected:
                try:
                    result.wait_for_publish(timeout=2)
                except RuntimeError:
                    pass
            self.client.disconnect()
            self.client.loop_stop()
