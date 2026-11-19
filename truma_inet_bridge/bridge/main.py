import asyncio
import contextlib
import datetime
import json
import logging
import os
from pathlib import Path
import signal
import time
from aiohttp import web
from .bluez import BlueZ
from .mqtt import MQTT
from .faults import FaultJournal
from .timer import (TIMER_COMMANDS, decode_timer, decode_enabled, decode_times,
                    timer_write, timer_reply_matches)
from .protocol import (encode_temperature, decode_temperature, decode_choice, FANS, WATER,
                       command_writes, validate_write_reply)

LOG = logging.getLogger(__name__)

# Bounded waiting and bounded execution are separate budgets. The complete
# transaction remains below the HA automation confirmation window (20 s).
COMMAND_QUEUE_SECONDS = 5
COMMAND_EXECUTION_SECONDS = 12

class CommandRejected(ValueError):
    """Rejected before execution; must not invalidate another active command."""

class TimerRejected(CommandRejected):
    """A timer request rejected before any device write."""

class Bridge:
    def __init__(self, options, data=Path("/data"), backend=None):
        self.options, self.data = options, data
        self.backend = backend or BlueZ(options)
        self.ready = False
        self.state = {"mode": "off", "target": None, "fan": "Unbekannt", "water": "Unbekannt"}
        self.updated = None
        self.status = "Bluetooth wird vorbereitet"
        self.error = None
        self.generation = 0
        self.paused_until = 0
        self.last_read = 0
        self.lock = asyncio.Lock()
        self.mqtt = None
        self.inventory = []
        self.command_tasks = set()
        self.stopping = False
        self.last_target = None
        self.diagnostics = None
        self.timer = None
        self.timer_error = None
        self.faults = FaultJournal(data / "fault-journal.json")
        try:
            saved = json.loads((data / "last-target.json").read_text())
            from .protocol import encode_temperature
            encode_temperature(saved["target"])
            self.last_target = saved["target"]
        except (FileNotFoundError, ValueError, TypeError, KeyError):
            pass

    def notify(self, status=None):
        if status:
            self.status = status
        if self.mqtt:
            self.mqtt.update()

    def unavailable(self, status):
        if self.ready:
            self.generation += 1
        self.ready = False
        self.timer = None
        self.notify(status)

    def remember_target(self, target):
        temporary = self.data / "last-target.tmp"
        temporary.write_text(json.dumps({"target": target}))
        temporary.replace(self.data / "last-target.json")
        self.last_target = target

    async def snapshot(self, include_measurements=True, guard=None):
        # Publish one coherent snapshot; never leave stale controls available
        # when a partial read fails.
        values = {k: await self.backend.read(k) for k in ("temperature", "fan", "water")}
        if guard:
            guard()
        target = decode_temperature(values["temperature"])
        if target is not None and target != self.last_target:
            self.remember_target(target)
        previous = self.state
        measurements = {k: previous.get(k) for k in ("current_temperature", "voltage", "water_temperature")}
        if include_measurements:
            read_measurements = getattr(self.backend, "measurements", None)
            measurements = await read_measurements() if read_measurements else dict.fromkeys(measurements)
            await self.refresh_timer()
            read_faults = getattr(self.backend, "read_faults", None)
            if read_faults:
                try:
                    self.faults.update(await read_faults())
                except Exception:
                    self.faults.update({})
                    LOG.exception("Fault read unavailable; retaining previous incidents")
        self.state = {"mode": "heat" if target is not None else "off",
                      "target": target if target is not None else self.last_target,
                      "fan": decode_choice(values["fan"], FANS),
                      "water": decode_choice(values["water"], WATER), **measurements}
        if not self.ready or previous != self.state:
            LOG.info("Confirmed box state: %s", json.dumps(self.state, ensure_ascii=False))
        self.updated = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if include_measurements:
            self.last_read = time.monotonic()
        self.ready = True
        self.error = None
        self.notify("Verbunden – Steuerung bereit" if self.options["allow_control"] else "Verbunden – Lesemodus")

    async def read_timer_snapshot(self):
        reader = getattr(self.backend, "read_timer", None)
        first = await reader() if reader else None
        if first is None:
            return None
        second = await reader()
        if first != second:
            raise ValueError("Timer wurde am Bedienpanel geändert; erneut auslesen.")
        return second

    async def refresh_timer(self):
        try:
            raw = await self.read_timer_snapshot()
            self.timer = decode_timer(raw) if raw is not None else None
            self.timer_error = None
            return raw
        except Exception as exc:
            self.timer = None
            self.timer_error = str(exc) or type(exc).__name__
            LOG.warning("Timer read unavailable: %s", self.timer_error)

    def check_command_fresh(self, generation, deadline):
        if (self.stopping or time.monotonic() < self.paused_until or not self.ready or
                not self.options["allow_control"] or
                getattr(self.backend, "restart_required", False) or
                generation != self.generation):
            raise ValueError("Keine aktuelle Verbindung; Befehl verworfen")
        if time.monotonic() >= deadline:
            raise ValueError("Zeitlimit für laufenden Befehl überschritten; verworfen")

    async def prepare_timer_write(self, kind, value):
        # Caller holds the same lock as ordinary commands and polling.
        if not self.options.get("allow_timer_control", False):
            raise ValueError("Timersteuerung ist noch gesperrt; Timer wird nur ausgelesen.")
        if not getattr(self.backend, "timer_writable", False):
            raise ValueError("Die Box bietet keinen vollständig schreibbaren Timer an.")
        if kind == "timer_enabled" and value == "OFF":
            # An explicit stop must remain possible even with malformed times
            # or settings the bridge cannot interpret.
            field, payload = "timer_enabled", b"\x00"
        elif kind == "timer_enabled":
            raw = await self.read_timer_snapshot()
            if raw is None:
                raise ValueError("Timer nicht verfügbar")
            state = decode_timer(raw)
            field, payload = timer_write(kind, value, state)
            # Detect a concurrent CP-plus change immediately before the write.
            changed = await self.backend.read_timer() != raw
            if changed:
                raise ValueError("Timer wurde inzwischen am Bedienpanel geändert; Befehl verworfen.")
        else:
            # While OFF, one edit depends only on its own field and the enabled
            # flag. Read those twice rather than blocking manual controls with
            # two unrelated nine-field snapshots. Activation still validates
            # the entire configuration. Confirmation below reads all fields.
            field = "timer_time" if kind in ("timer_start", "timer_stop") else kind
            enabled = await self.backend.read("timer_enabled")
            before = await self.backend.read(field)
            state = {"enabled": decode_enabled(enabled)}
            if field == "timer_time":
                state["start"], state["stop"] = decode_times(before)
            field, payload = timer_write(kind, value, state)
            if (await self.backend.read("timer_enabled") != enabled or
                    await self.backend.read(field) != before):
                raise ValueError("Timer wurde inzwischen am Bedienpanel geändert; Befehl verworfen.")
        return field, payload

    async def timer_command(self, kind, value, generation, deadline):
        try:
            field, payload = await self.prepare_timer_write(kind, value)
            self.check_command_fresh(generation, deadline)
        except ValueError as exc:
            raise TimerRejected(str(exc)) from exc
        await self.backend.write(field, payload)
        actual = await self.backend.read(field)
        if not timer_reply_matches(field, payload, actual):
            raise ValueError("Die Box hat die Timeränderung nicht bestätigt")
        confirmed = await self.refresh_timer()
        if self.timer is None:
            raise ValueError(self.timer_error or "Timer-Rückmeldung fehlt")
        if (generation != self.generation or self.stopping or
                getattr(self.backend, "restart_required", False)):
            raise ValueError("Verbindung während der Timerbestätigung geändert")
        if not timer_reply_matches(field, payload, confirmed[field]):
            raise ValueError("Timer wurde während der Bestätigung erneut geändert")
        self.check_command_fresh(generation, deadline)
        self.notify("Timeränderung von der Box bestätigt")

    async def run(self):
        had_link = False
        while not self.stopping:
            try:
                if self.diagnostics:
                    self.diagnostics.observe(self)
                if not self.backend.registered or self.backend.restart_required:
                    self.unavailable("Bluetooth-Dienst wird verbunden")
                    had_link = False
                    self.generation += 1
                    await self.backend.restart()
                if time.monotonic() < self.paused_until:
                    self.unavailable("Für Truma-App freigegeben")
                    await asyncio.sleep(1)
                    continue
                if not self.backend.advertising:
                    await self.backend.advertise(True)
                props = await self.backend.device()
                if self.diagnostics:
                    self.diagnostics.link(props)
                if not props.get("Connected") or not props.get("ServicesResolved") or not props.get("Paired"):
                    if had_link:
                        self.backend.paths = {}
                        self.backend.subscriptions = []
                        self.generation += 1
                        had_link = False
                    self.unavailable("Kopplung aktiv – Bluetooth-Taste an der Box drücken" if
                                     self.backend.pair_until > time.monotonic() else "Warte auf iNet-Box")
                    await asyncio.sleep(1)
                    continue
                if not had_link:
                    async with self.lock:
                        self.inventory = await self.backend.discover()
                        (self.data / "gatt-inventory.json").write_text(json.dumps(self.inventory, indent=2))
                        self.generation += 1
                        await self.snapshot()
                        await self.backend.trust_verified_box()
                        had_link = True
                    await self.backend.close_pairing()
                elif time.monotonic() - self.last_read >= self.options.get("poll_seconds", 15):
                    async with self.lock:
                        await self.snapshot()
                # Signals from ReadValue itself must not create a busy poll loop.
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
                self.unavailable("Verbindung prüfen: " + self.error[:170])
                if self.diagnostics:
                    self.diagnostics.error(exc)
                LOG.warning("Bluetooth read/connect failed (%s): %s", type(exc).__name__, exc)
                had_link = False
                await asyncio.sleep(5)

    def schedule_command(self, kind, value, generation):
        if len(self.command_tasks) >= 4:
            self.faults.command_failed("Zu viele gleichzeitige Aufträge")
            self.notify("Befehl abgewiesen – zu viele gleichzeitige Aufträge")
            return
        task = asyncio.create_task(self.command(kind, value, generation, time.monotonic()))
        self.command_tasks.add(task)
        task.add_done_callback(self.command_tasks.discard)

    async def command(self, kind, value, generation, arrived=None):
        arrived = time.monotonic() if arrived is None else arrived
        admitted = False
        if kind == "fault_seen":
            # Local notification acknowledgment only; never touches Bluetooth.
            if not self.stopping and time.monotonic() - arrived <= COMMAND_QUEUE_SECONDS:
                self.faults.mark_seen()
                self.notify()
            return
        try:
            remaining = COMMAND_QUEUE_SECONDS - (time.monotonic() - arrived)
            if remaining <= 0:
                if kind in TIMER_COMMANDS:
                    raise TimerRejected("Timerbefehl ist veraltet; bitte erneut auslösen.")
                raise CommandRejected("Befehl zu lange gewartet; verworfen")
            async with asyncio.timeout(remaining) as queue_timeout:
                async with self.lock:
                    queue_timeout.reschedule(None)
                    admitted = True
                    if not self.options["allow_control"]:
                        raise ValueError("Steuerung ist gesperrt: Lesemodus")
                    if kind in TIMER_COMMANDS and time.monotonic() - arrived > COMMAND_QUEUE_SECONDS:
                        raise TimerRejected("Timerbefehl ist veraltet; bitte erneut auslösen.")
                    if (self.stopping or time.monotonic() < self.paused_until or
                            not self.ready or getattr(self.backend, "restart_required", False) or
                            generation != self.generation or time.monotonic() - arrived > COMMAND_QUEUE_SECONDS):
                        raise ValueError("Keine aktuelle Verbindung; Befehl verworfen")
                    deadline = time.monotonic() + COMMAND_EXECUTION_SECONDS
                    async with asyncio.timeout(COMMAND_EXECUTION_SECONDS):
                        await self.execute_command(kind, value, generation, deadline)
                    LOG.info("Command confirmed: %s (%.2f s including queue)", kind,
                             time.monotonic() - arrived)
        except Exception as exc:
            if isinstance(exc, TimeoutError) and not admitted:
                exc = CommandRejected("Befehl zu lange gewartet; verworfen")
            self.error = ("Bluetooth-Befehl hat das Zeitlimit überschritten; Rückmeldung fehlt"
                          if isinstance(exc, TimeoutError) else str(exc) or type(exc).__name__)
            self.faults.command_failed(self.error)
            if isinstance(exc, TimerRejected):
                self.timer = None
                self.timer_error = str(exc)
                self.notify("Timerbefehl abgewiesen: " + str(exc)[:160])
                LOG.warning("Timer command rejected before write: %s", exc)
                return
            if isinstance(exc, CommandRejected):
                self.notify("Befehl abgewiesen: " + self.error[:160])
                LOG.warning("Command rejected before execution: %s", self.error)
                return
            # A write may have partially succeeded. Invalidate the entire state
            # until the polling loop has read it again. No retries/replay.
            self.unavailable("Befehl nicht abgeschlossen: " + self.error[:160])
            LOG.warning("Command rejected/failed: %s", self.error)

    async def execute_command(self, kind, value, generation, deadline):
        props = await self.backend.device()
        if not props.get("Connected") or not props.get("Paired") or not props.get("ServicesResolved"):
            raise ValueError("Bluetooth-Verbindung nicht bereit")
        if kind in TIMER_COMMANDS:
            await self.timer_command(kind, value, generation, deadline)
            return
        # Re-read the physical state before composing a multi-step command.
        await self.snapshot(include_measurements=False,
                            guard=lambda: self.check_command_fresh(generation, deadline))
        self.check_command_fresh(generation, deadline)
        if kind == "temperature" and self.state["mode"] == "off":
            # A nonzero box temperature also enables heating. While off,
            # keep the user's preset locally until an explicit heat command.
            target = decode_temperature(encode_temperature(value))
            self.remember_target(target)
            self.state["target"] = target
            self.notify()
            return
        writes = command_writes(kind, value, self.state)
        self.notify("Änderung wird bestätigt")
        for field, payload in writes:
            self.check_command_fresh(generation, deadline)
            await self.backend.write(field, payload)
            actual = await self.backend.read(field)
            if not validate_write_reply(payload, actual):
                raise ValueError("Die Box hat die Änderung nicht bestätigt")
        await self.snapshot(include_measurements=False,
                            guard=lambda: self.check_command_fresh(generation, deadline))
        self.check_command_fresh(generation, deadline)

    async def handover(self):
        async with self.lock:
            self.generation += 1
            self.paused_until = time.monotonic() + 300
            await self.backend.close_pairing()
            await self.backend.advertise(False)
            await self.backend.disconnect()
            self.unavailable("Für Truma-App freigegeben")

    async def resume(self):
        self.paused_until = 0
        await self.backend.advertise(True)

    def public_status(self):
        return {"status": self.status, "error": self.error, "ready": self.ready,
                "state": self.state if self.ready else None, "updated": self.updated,
                "timer": self.timer if self.ready else None, "timer_error": self.timer_error,
                "faults": self.faults.view(self.ready),
                "timer_control": bool(self.options.get("allow_timer_control", False)),
                "read_only": not self.options["allow_control"], "mqtt": bool(self.mqtt and self.mqtt.connected),
                "pair_seconds": max(0, int(self.backend.pair_until - time.monotonic())),
                "pause_seconds": max(0, int(self.paused_until - time.monotonic())),
                "advertising": self.backend.advertising, "box": self.options["box_address"],
                "characteristics": len(self.inventory)}

@web.middleware
async def ingress_only(request, handler):
    # The port is not exposed to the LAN. HA ingress is the only trusted caller.
    if request.remote != "172.30.32.2":
        raise web.HTTPForbidden(text="Bitte über Home Assistant öffnen.")
    if request.method == "POST" and request.headers.get("X-Truma-Action") != "1":
        raise web.HTTPForbidden(text="Ungültige Anfrage")
    return await handler(request)

def create_web(bridge):
    app = web.Application(middlewares=[ingress_only])

    async def index(request):
        return web.FileResponse(Path(__file__).with_name("index.html"))

    async def status(request):
        return web.json_response(bridge.public_status())

    async def diagnostics(request):
        if not bridge.diagnostics:
            raise web.HTTPNotFound()
        return web.Response(body=bridge.diagnostics.archive(), content_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="truma-connection-history.zip"',
                                     "Cache-Control": "no-store"})

    async def action(request):
        action_name = request.match_info["action"]
        try:
            if action_name == "pair":
                await bridge.resume()
                await bridge.backend.pair()
            elif action_name == "cancel":
                await bridge.backend.close_pairing()
            elif action_name == "handover":
                await bridge.handover()
            elif action_name == "resume":
                await bridge.resume()
            else:
                raise ValueError("Unbekannte Aktion")
            return web.json_response(bridge.public_status())
        except Exception as exc:
            LOG.warning("UI action failed: %s", exc)
            return web.json_response({"error": str(exc)}, status=400)

    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/diagnostics", diagnostics)
    app.router.add_post("/api/{action}", action)
    return app

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    options = json.loads(Path("/data/options.json").read_text())
    bridge = Bridge(options)
    from .diagnostics import Diagnostics
    bridge.diagnostics = Diagnostics(bridge.data / "diagnostics")
    bridge.mqtt = MQTT(bridge, options)
    bridge.mqtt.start()
    runner = web.AppRunner(create_web(bridge), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8099).start()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    task = asyncio.create_task(bridge.run())
    task.add_done_callback(lambda t: stop.set() if not t.cancelled() else None)
    await stop.wait()
    bridge.stopping = True
    for pending in bridge.command_tasks:
        pending.cancel()
    if bridge.command_tasks:
        await asyncio.gather(*bridge.command_tasks, return_exceptions=True)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        try:
            await task
        except Exception:
            LOG.exception("Bridge stopped unexpectedly")
    bridge.unavailable("Bridge beendet")
    await bridge.backend.stop()
    await asyncio.to_thread(bridge.mqtt.stop)
    await runner.cleanup()
    bridge.diagnostics.close()

if __name__ == "__main__":
    asyncio.run(main())
