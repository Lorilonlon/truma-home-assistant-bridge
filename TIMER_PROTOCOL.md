# Classic iNet / CP-plus timer

Experimental feature in 0.1.9-beta.6. This implements the device's own daily interval, not a second Home Assistant schedule. No weekday schedule or independent clock synchronization is implemented.

## Evidence

Original user-supplied iNet System 5.1.1, package `com.truma.inet`, ARM32 Dart 3.8.1 snapshot. The base APK SHA-256 is `0b22dc323a937c3af3a456b57eae699828786613b17c1f072504c46016909a90`. Snapshot structure was parsed with Jadart revision `285ddf4c1276bc66a5b813f09455c51e50f0b4f7`, with all nine Tier-A and three Tier-B grammar gates passing. These gates validate the parser, not our protocol interpretation or device behavior. Native instructions and recovered constant references were inspected; no OEM code, binaries, assets or private captures are distributed here.

The field map follows `TimerSettingsBase.defaultDefinitions` (native address `0x770368`), `heaterDefinitions` (`0x771ed8`) and `setHeaterDefinition` (`0x771e90`). The service is `00010000-0004-0001-0000-0000fe088214`. Every characteristic below uses suffix `-0004-0001-0000-0000fe088214`.

| Prefix | Meaning | Encoding / implementation |
| --- | --- | --- |
| `00000200` | Timer enabled | Write one byte: 0 off, 1 on. An empty response is treated as unknown/uninitialized, not a confirmed off state. |
| `00000205` | Start and stop | Four bytes: start minute, start hour, stop minute, stop hour. |
| `0001000d` | Timer room target | Same temperature converter as ordinary heating; uint16 little-endian, `(C + 273) * 10`, 0 off. |
| `0001000e` | Timer fan | Same fan converter as ordinary heating; bridge supports off, Eco and High. |
| `00010010` | Timer water | Same water converter as ordinary heating; off, low, high and boost enum. |
| `0001000f` | Timer heating power | Read and preserve only. |
| `00010011` | Timer water power | Read and preserve only. |
| `00010012` | Timer heating energy | Read and preserve only. |
| `00010013` | Timer water energy | Read and preserve only. |

Time encoding follows `BluetoothTimeAttribute.readAndSerialize` (`0x8aac04`), `serializeTime` (`0x8aadb4`), `serializeHour` (`0x8aaea8`) and `serializeMinute` (`0x8aaf1c`). Decoding assigns the first two bytes to start and the next two to stop (`parseAndSet`, `0xac60e4`). Example **synthetic fixture**, not a captured write: 06:30–08:20 encodes as `1e 06 14 08`.

The original enabled parser tests whether the first byte equals 1 (`0x77070c`); its Boolean serializer defaults to true value 1 (`0x770460`). The serializer closure (`0x7705e8`) creates a one-element integer list containing the configured true value, or zero for false/null. The bridge intentionally rejects malformed flags and requires explicit off before editing a genuinely empty flag.

All nine characteristics were discovered and passively read on an iNet HW 1.3.0 / FW 3.1.5 with Combi 6. The deployed read-only integration reports timer off with zero times/targets. A shell GVariant display of `b''` was initially ambiguous: that notation can represent a NUL-terminated bytestring and must not be equated with a zero-length D-Bus byte array. These reads do **not** validate activation or successful timer writes.

## Deliberate controls

- Timer fields are optional. Missing timer support or failed timer decoding does not disable ordinary heating.
- Timer state is read twice and published only when both complete snapshots match. Panel changes appear on the next successful poll.
- Editing requires confirmed timer off. The enabled flag and the edited field are read and compared twice before a write; changing either time preserves the other freshly read endpoint. No edit enables the timer. Unrelated fields are not read before every edit, avoiding unnecessary delay; all fields are read for confirmation afterward.
- Enable is a separate command. Equal start/end, no heating/water demand, unknown modes and unsupported energy settings are rejected. Initial activation support is restricted to the known gas-only Combi 6 configuration (energy 1/1, power 0/0).
- Explicit off remains possible when other timer fields cannot be decoded.
- No writes to the ordinary heater target, no automatic fuel selection, no schedule stored locally, no timer replay on restart/reconnect.
- The existing lock, generation checks, non-retained commands and three-second command age limit apply. A whole fresh snapshot is compared again before enable. Each write is read back, then the complete timer is confirmed again. No write retry or rollback is attempted after failure.
- The device protocol has no verified atomic compare-and-swap. A physical-panel change in the final gap between the last read and write remains possible. Avoid simultaneous editing from two controls.
- Timer operation follows the clock and behavior of CP plus. HA does not correct the device clock or guarantee frost protection.

## Validation boundary

76 software tests pass, including encoding, invalid inputs, midnight/overnight times, optional discovery, unknown initial flag, concurrent panel changes, expiry, handover, read-only mode, readback mismatch, no restart replay and preserving manual heating. Expired timer requests rejected before any write do not mark the heater disconnected. A browser test covers time editing, confirmation display, active-timer editing lock and the explicit-off control when other timer data are invalid. The beta has been installed on the reference system; eight MQTT entities appear, while heater and water settings remain unchanged.

Remote hardware test on 2026-11-13 through the actual HA entities, MQTT and bridge: with the timer continuously confirmed OFF, set start to 06:30, stop to 08:20, room target to 19 °C, fan to Eco and timer water to Low. Every individual write was read back and then confirmed in a complete timer snapshot. All five settings were restored and all ten timer fields matched their initial values. Ordinary heating and water stayed OFF, with the existing ordinary target preserved. No timer-enable command was sent. The first beta exposed an overlong pre-write read path; the stale request was rejected without a write. Version 0.1.9-beta.3 completed all five changes and restorations after narrowing edit prechecks to the relevant fields. The three-second age limit was retained.

On 2026-11-19 the operator saw 06:30–00:00, 19 °C and Eco at the CP plus. HA reported the timer active. After disabling it through HA, only the end time was changed to 08:20. The operator confirmed the complete test settings at the panel (06:30–08:20, 19 °C, Eco, water off). The original end time was restored to 00:00 and the complete snapshot read back with the timer disabled.

Remote enable, a deliberately changed field at the panel appearing in HA, and an actual device-scheduled start and stop including midnight remain to be verified. Device timer writes default to off independently of ordinary heating control.
