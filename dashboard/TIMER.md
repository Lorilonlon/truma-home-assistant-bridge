# Home Assistant timer form

The dashboard uses a **Home Assistant schedule**, separate from the experimental
CP-plus timer described in `../TIMER_PROTOCOL.md`. Its form starts empty. Editing
a field sends nothing. One submission saves the complete schedule in HA.

Date and time use a large modal picker in the HA time zone. Choosing a calendar day opens the time step; hours and minutes support direct numeric entry and step buttons. Apply transfers the selection into the draft and closes the dialog; Cancel/Escape discards it. The timer is saved only through the main form. New forms reset date/time to empty.

- One execution, or daily at the selected local time, starting on the chosen date.
- Optional end: capture a fresh physical state immediately before starting, then
  restore heating on/off, saved target, applicable fan mode and water setting at
  the end. Without an end the new settings remain in effect.
- Green means an accepted HA job is pending or active. It does **not** mean that
  a future schedule has been transferred into the Truma. The card explicitly
  distinguishes saved in HA, transferring, and confirmed by Truma.
- After confirmed completion the background returns to normal. A daily job shows
  the next occurrence; it does not claim that the next run is already confirmed.
- Confirmation means the box returned the requested control values, not that the
  room or water has already reached the target temperature.

## Install and maintain

Create the 25 storage helpers in `timer-helpers.json` through the HA helper API.
Do not set `initial`: the job, next deadline and pre-start snapshot must survive
restarts. Their expected IDs are `input_text.truma_timer_auftrag`,
`input_text.truma_timer_vorher` and `input_datetime.truma_timer_termin`, with suffixes `_2` through `_8` for
additional slots. `input_text.truma_timer_aktuell` records the newest attempted
command owner. Each slot has its own saved pre-start state and date helper.
Initialize the job helper to an empty string once when creating a new setup.
Never clear an existing active job during an upgrade.

Install `timer-script.json` as `script.truma_timer_verwalten`, and
`timer-automation.json` as `automation.truma_timer_zeitplan`, enabled. Set the
script's `notify_service` to the installation's mobile notification action, or
leave it empty for HA persistent notifications only. No personal notification
recipient is included in these files. Register `camper-inet-card.js` as a module.
The card uses these IDs by default. No bridge firmware change is necessary.

Edit `../scripts/build_timer_workflow.py` and regenerate the JSON with Python.
Eight pending timers are supported. The card offers “Weiteren Timer vormerken”.
Pending, daily waiting and failed timers have a “Timer bearbeiten” button. It pre-fills the form without writes. Save replaces the same slot only after validation and renewed overlap consent; a full expected-job comparison rejects stale edits or timers that started meanwhile. Cancel editing leaves the saved job intact.

Completed slots may be reused; the most recently applied record is kept when
another free slot exists.

Overlaps are shown before submission and require explicit confirmation. HA
recomputes the affected job IDs before accepting that consent. One-shot and
daily/overnight intervals are compared in local wall-clock time. The later
start takes precedence; at equal starts the later-created job wins. An older
end must not overwrite newer settings, even after a partial newer command.
The newer timer captures its own pre-start settings, which may be those of the
older timer. The scheduler serializes due jobs in chronological order, with
end events before start events at the same instant.

The JSON is generated for review and API installation, not for direct edits to
HA internal storage. Dynamic templates validate submitted data and calculate
calendar times; waits deliberately check existing states as well as changes.
The generated script serializes its own operations with `mode: single`.

## Execution and failure boundaries

HA must be running and able to reach the bridge at start/end. The browser may be
closed. Before a timed change the native CP-plus timer must be off and a manual
heater restart must not be running. An optional end requires a complete fresh
snapshot. An off heater is restored to off before restoring its saved target, so
restoring a target cannot implicitly enable it.

Commands are sequential, read back, and tried at most three times, sending only
settings still missing. The final check also requires a fresh bridge snapshot.
Failure records an error and sends HA/optional phone notifications; partial
changes may remain. A failed start does not silently proceed to a later restore;
the user must inspect the actual settings. An interrupted command sequence is
reported rather than replayed. Starts more than 90 seconds late are not caught up.
An end interrupted by HA downtime can restore within 24 hours; older ends fail
with a notification. Daily repetition stops after failure until resubmitted.

Daily calendar arithmetic preserves local wall-clock time, including overnight
end times. A nonexistent time at a daylight-saving transition stops the schedule
with an error rather than silently shifting it. A maximum one-day daily window
and minimum five-minute interval leave room for bounded command confirmation.
The end snapshot contains control settings, not a device safety/error reset.
Avoid simultaneous manual controls while a start/restore command is executing.

## Validation

The isolated `tests/test_timer_workflow.py` simulator requires Jinja2 and never
contacts hardware. It covers start-only, optional end/frost/off restoration,
daily next occurrence, late-start rejection, cancellation, interrupted execution,
missing readbacks and native-timer conflict. The Playwright test
`tests/test_timer_card.cjs` requires Playwright and Chrome, and accepts the card
path as its argument. It uses a fake HA object: empty drafts, no individual
writes, optional end, one submit, confirmation-dependent styling and scheduler
availability.

On the reference HA instance the submit/persist/readback/cancel path was checked
without heater commands. Actual timed start/end restoration through this new
workflow remains to be observed on hardware. The CP plus panel comparison passed on 2026-11-19. A complete scheduled device-timer cycle remains to be verified. Substantial AI assistance is disclosed
in the project-wide `AI_DISCLOSURE.md`.

Successful one-shot timers are hidden 24 hours after confirmed completion. Completion time is persisted; older entries fall back to the helper’s last_changed time. Completed and failed entries can be explicitly removed from the list without heater commands. Errors are not automatically hidden or reused; daily schedules remain visible.
