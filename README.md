# SALUS Comfort Blueprint

One shared Home Assistant automation for multiple rooms, with independent room
timers and decisions. Uses standard HA actions and helpers; no custom SALUS
controller, storage, service or frontend loader is needed.

**Preview v0.1.0-beta.1.** Tested in HA's actual blueprint parser and script engine
with simulated entities. This extracted version has not been tested on physical
hardware. Keep your existing working installation until you choose to migrate.

[Dansk vejledning](README.da.md) ·
[Independent dashboard card](https://github.com/MichaelBusackBertelsen/salus-room-card)

## Requirements and installation

Home Assistant 2026.2 or newer, a weather entity supporting hourly forecasts, and
floor selects whose underlying options are `off`, `level_1`, `level_2`, `level_3`.
The UI may translate these options. A pending optimistic level must expose HA's
standard `assumed_state`; it is not accepted as a device confirmation.

1. For **each room**, create two **Timer** helpers under Settings → Devices &
   services → Helpers → Create helper. Enable **Restore** on both. Name them
   clearly: e.g. `Example comfort period` and `Example comfort pause`.
2. Create one **Text** helper for that room. Set maximum length **255**, leave its
   value empty, and do not set an initial value in YAML. It stores compact room
   status that HA can restore. Never share any of these three helpers with
   another room or another automation.
3. Settings → Automations & scenes → Blueprints → Import blueprint. Paste the
   [English blueprint URL](https://github.com/MichaelBusackBertelsen/salus-comfort-blueprint/blob/main/blueprints/automation/salus_floor_comfort.yaml)
   or the [Danish blueprint URL](https://github.com/MichaelBusackBertelsen/salus-comfort-blueprint/blob/main/blueprints/automation/salus_floor_comfort_da.yaml).
4. Create **one** automation from that blueprint. In **Rooms**, add each room,
   its floor select, climate entity, two timers and Text helper. Configure the
   common thresholds and periods; save and enable the automation.

The form is grouped into weather, rooms, starting, stopping, indoor limits, and
manual control. Every setting includes an explanation. All threshold inputs use
Celsius. Select Fahrenheit for **Home Assistant temperature unit** if your climate
entities report Fahrenheit; outdoor weather/sensor units are converted automatically.

YAML helper examples are available in [examples/helpers.yaml](examples/helpers.yaml).
These are examples to adapt, not a second installation step for helpers already
created through the UI.

## Decisions, per room

| Situation | Result |
|---|---|
| At least one valid hourly forecast within the horizon is strictly below the start threshold; room is off and its pause ended | Request the selected level now; record forecast minimum, its time, fetch time and current outdoor temperature |
| Device confirms that level | Start the complete minimum runtime; later forecast revisions do not cancel it |
| Period ends; current outdoor temperature is below the stop threshold | Extend only this room by the configured extension |
| Period ends; current outdoor temperature is at/above the stop threshold | Request Off unless this room needs indoor minimum hold |
| Current outdoor temperature is missing at the boundary | Extend; use the optional sensor first, then the weather entity's **current** temperature |
| Indoor minimum hold is enabled and this room is cold | Hold this already-owned room; never start it or hold other rooms solely for this reason |
| Owned room reaches the enabled upper indoor limit | Request Off immediately, including during minimum runtime |
| Room was already manually active | Leave it alone unless adoption is enabled **and** the forecast qualifies; adoption preserves its level and starts a new minimum period now |
| An owned room is manually switched off or to another level | Release it and start its own pause; preserve the external setting |

The first period begins at **confirmation**, not at sending the request. Repeated
checks and HA restarts preserve the existing start/deadline. The optional outdoor
sensor is used only for stop decisions; starts always use the hourly forecast.
This is air temperature, not a calculated “feels like” value.

Forecasts must be complete, hourly, timezone-aware, finite and without duplicate
timestamps across the selected horizon. Invalid/incomplete forecasts cannot start
new rooms. Existing protected periods continue. Missing indoor data prevents a
new start when the upper-limit protection is enabled; missing indoor data with
minimum hold enabled extends that room at the boundary.

## Scheduling, confirmations and failures

Forecast/start eligibility is checked every **15 minutes** and at HA startup.
Selected timer completions and room state changes handle confirmation, manual
changes and indoor protection. There is no minute polling or global
`state_changed` subscription. Room writes are short sequential requests; waiting
for device confirmation does not block other rooms.

Allow 150 seconds for confirmation. An unconfirmed start ends in that room's
pause, without immediate replay. An unconfirmed stop retains ownership and
schedules a **fresh evaluation in five minutes**; if stopping is still needed,
that later evaluation can issue a new request. A pending/unknown level is never
reported as confirmed. These are automation-level checks, not transport retries.

Disabling the automation stops its decisions; it **does not switch comfort off**
and timers keep running. When enabled again, reconciliation occurs at the next
scheduled check (up to 15 minutes) or selected event. To stop immediately, disable
the automation and manually set the floor selects to Off.

Timers must restore. If a timer expires while HA is stopped, the startup check
uses the stored deadline to reconcile it. Do not edit the Text JSON or restart
the timers manually during operation. Invalid configuration is stopped before
floor writes and is visible in the automation trace.

## Activity and dashboard

Decisions are logged against the **individual floor select** in HA Activity:
forecast-based request, device confirmation, adoption, extension and its reason,
stop request, confirmation and pause. Activity retention follows your Recorder
configuration. The Text helper retains the latest room state, not an unlimited
history. The automation keeps 30 traces, independently of Activity retention.

In the optional SALUS Climate Card choose that room's Text helper as
`comfort_state` and this automation as `comfort_automation`. Timing, latest
decision and Activity link appear only when expanded. The card does not write
helpers or make automation decisions.

## Migration from the bundled beta

Installation does not alter your existing SALUS beta, dashboards or automations.
When ready: create the new helpers, import the blueprint, configure the new
automation **disabled**, and copy your existing thresholds and chosen rooms.
Disable the old weather automation before enabling the new one. Never run both
on the same rooms. Old custom-controller periods do not migrate automatically.
Choose deliberately whether manually active rooms may be adopted, or confirm
them Off before enabling the new automation. Expect a fresh minimum period on
new starts/adoptions. Keep the old automation disabled for rollback; no gateway
or integration configuration is deleted.

## Development

`scripts/build.py` generates both importable YAML variants from one definition;
Danish form labels live in `translations/da.json`. Activity messages currently use
English in both variants. Python is needed only for development, not installation.

Install the dependencies in `.github/workflows/ci.yml`, then run:

```sh
python scripts/build.py
python -m pytest -p pytest_asyncio.plugin -q
python -m ruff check scripts tests
```

Tests execute the shipped YAML with real HA template/script/blueprint machinery
and simulated services, including independent rooms, confirmation timeouts,
restart reconciliation, forecasts, manual control and indoor overrides. CI checks
HA 2026.2.3 and 2026.10.3. MIT license; upstream notices retained.
