# Truma iNet Bridge for Home Assistant

Control space heating and hot water from Home Assistant through the classic **Truma iNet Box**. The bridge runs locally, talks to the box over Bluetooth and exposes controls and sensors through MQTT. Tested with a Truma Combi 6. The iNet X protocol is not supported.

> [!WARNING]
> Experimental software controlling a real heater and water system. Use at your own risk. Incorrect readings, lost connections or unexpected operation can cause injury, fire, overheating or frost damage. Test changes on site, follow the manufacturer's instructions and retain access to the local controls. Do not rely on the bridge alone for frost protection. If it behaves unexpectedly, stop the bridge and use the local controls as instructed by the manufacturer. The MIT licence and mandatory statutory liability apply. [Safety and liability](LEGAL.md#sicherheit-und-haftung)

## Heating, water and dashboard

Set a target room temperature, choose Eco or High fan speed and select a hot water setting (Off, Low, High or Boost). Changing the target while space heating is off stores it for the next explicit start. The dashboard shows the measured room and water temperatures, confirmed settings and connection status. Supply voltage is available as a separate sensor. It measures voltage at the iNet Box and can differ from a battery monitor. Missing or implausible values appear as unknown. Readback confirms control settings, not burner operation.

## Timers

- **Home Assistant schedules.** Queue up to eight one-off or daily timers. Pick the date, time, temperature, fan and hot water settings, then save the whole form. You can edit a pending timer. Adding an end time tells HA to restore the settings it read immediately before the start. With no end time, the new settings stay in effect.
- **Overlapping timers.** The dashboard asks for confirmation when a new entry overlaps an existing one. The later start takes priority, and the older timer's end cannot undo it. The dashboard distinguishes a schedule saved in HA from settings confirmed by the box. Completed one-off entries disappear from the list after 24 hours.
- **Execution.** HA and the Bluetooth connection must be available when a schedule runs. If the box still does not confirm the requested settings after bounded retries, HA reports the failure. Configure a phone notification action to receive it on your phone. [Install the scheduler and dashboard controls](dashboard/TIMER.md)
- **CP plus device timer.** The heater's own daily timer stores one start and end time. It can be read through the bridge. Writing requires separate opt-in via `allow_timer_control`. On the reference installation, the operator checked **06:30–08:20, 19 °C, Eco, hot water off** at the CP plus after the end time was changed in HA with the device timer off. The bridge also read back the restored end time. A complete scheduled start and stop by the CP plus still needs verification. [Device timer tests and limits](TIMER_PROTOCOL.md)

## Heater warnings and faults

**As in the Truma iNet System phone app, you cannot reset a heater fault remotely through the classic iNet Box using Home Assistant.** The dashboard shows the fault reported by the appliance. Marking a message as seen acknowledges it in HA. If the fault requires acknowledgement at the CP plus, address the cause and follow the manufacturer's instructions at the panel.

HA can forward new warnings, faults and failed commands to your phone using a Companion App notification action you configure. The optional “Heizung neu starten” action cycles heating and hot water and restores the previous settings. In tests the W17H warning persisted after this operation. [Fault reporting and notification setup](FAULTS.md)

## Installation

1. On Home Assistant OS, set up the MQTT integration and a reachable broker. [Add this app repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FLorilonlon%2Ftruma-home-assistant-bridge). Select **Camper Heater Bridge** in the app store. The app builds locally from source.
2. Enter your box's Bluetooth address in `box_address`, choose the adapter (usually `hci0`) and enter your MQTT connection settings. TLS is enabled by default. If needed, supply your CA's public certificate. The adapter must support BLE peripheral advertising and a GATT server. An ordinary ESPHome Bluetooth proxy cannot replace it.
3. Turn off Bluetooth on phones previously paired with the box. Start the bridge, open its web interface, start pairing and press the Bluetooth button on the iNet Box. First check the readings, then enable `allow_control` when you want to control the appliances. HA schedules do not require device-timer write access.
4. For the dashboard, copy `dashboard/camper-inet-card.js` and `dashboard/camper-inet-fault-card.js` to `/config/www/` and register each as a JavaScript module under `/local/`. Add the cards from [the example dashboard](dashboard.json) to your view. Check the entity IDs and adjust the setup link to your installed app. Install the [timer helpers, script and automation](dashboard/TIMER.md) separately to use the scheduler.
5. If you already use a local installation or the previous GitHub repository URL, keep the existing entry when updating. A different repository prefix can create a second installation. Back up the existing options and data before migrating, and run only one bridge. A fresh GitHub installation and migration have yet to be verified on the reference hardware.

## Bluetooth troubleshooting

A paired phone can reconnect to the box and occupy the connection the bridge needs. If HA loses contact, disconnect the phone and temporarily turn off Bluetooth on **all** previously paired phones, including a spare phone. If a phone keeps reconnecting and you no longer use it with the box, remove the pairing on that phone. To use the Truma app intentionally, release the box temporarily in the bridge's setup page.

If pairing still fails, consult the [optional Bluetooth compatibility app](truma_bluetooth_compat/README.md). It delays a security request to the configured box by 800 ms, affects the shared Bluetooth service and requires host permissions. The bridge web interface also offers a bounded local connection log for troubleshooting. Its three rotating log files use about 1.5 MiB in total, record connection changes and periodic status, and survive app restarts. The export excludes Bluetooth payloads, pairing keys and configured credentials. Timestamps and operating states can still be personal. Keep exported logs private.

## Test scope and project information

Test setup: Raspberry Pi 4 running Home Assistant OS, classic iNet Box hardware 1.3.0 / firmware 3.1.5, and a Combi 6. The owner reports more than a month of fault-free day-to-day operation of the bridge in their motorhome. A scheduled HA hot-water command was confirmed by the box. Remote fault reporting was compared with W17H on the CP plus. Results are specific to this equipment. See [measurement notes](PROTOCOL.md), [timer tests](TIMER_PROTOCOL.md) and [fault tests](FAULTS.md).

For local tests, install the dependencies from `truma_inet_bridge/requirements.txt` and Jinja2 for the scheduler simulations. Run `PYTHONPATH=truma_inet_bridge python -m unittest discover -s tests`.

Use non-retained MQTT commands and restrict access to the broker. MQTT 3 does not always identify a retained command forwarded to a live subscriber. The bridge does not replay commands after reconnection.

Independent community project, unaffiliated with Truma or Home Assistant. Developed with [OpenAI Codex support](AI_DISCLOSURE.md). [MIT licence](LICENSE) · [Third-party notices](THIRD_PARTY.md) · [Private security reporting](SECURITY.md).
