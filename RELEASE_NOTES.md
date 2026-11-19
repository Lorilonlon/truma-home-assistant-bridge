# 0.1.9-beta.6 — Timers and heater fault reporting

- Schedule up to eight one-off or daily HA timers. Edit pending entries, confirm overlaps, and optionally restore the previous settings at the end. The dashboard distinguishes saved schedules from confirmed settings. Persistent notifications and optional phone alerts report final failures.
- Inspect and optionally configure the separate daily CP plus timer. The panel comparison passed on a Combi 6 with iNet Box HW 1.3.0 / FW 3.1.5. A full device-scheduled start and stop remains to be verified.
- Read appliance warnings and faults in HA and forward them to a configured phone. **As in the Truma iNet System app, Home Assistant cannot remotely reset heater faults through the classic iNet Box.** Mark as seen acknowledges the HA message. The optional heater restart did not clear W17H in testing.
- Separate queue and execution time limits improve command confirmation on slower Bluetooth connections.

The owner reports more than a month of fault-free day-to-day operation of the bridge in their motorhome.

Install the updated dashboard modules and the optional HA scheduler helpers, script and automation as described in the README. Existing private settings belong in your local installation.

Experimental source pre-release for the classic iNet Box. Test on site and follow the manufacturer's instructions. Use at your own risk. Developed with OpenAI Codex support.
