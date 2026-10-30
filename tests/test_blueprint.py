"""Execute the shipped YAML in real HA's blueprint parser and script engine."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time
from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    PLATFORM_SCHEMA,
)
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import Context, HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.util import yaml as yaml_util

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
ROOMS = [
    dict(
        name=name,
        comfort=f"select.{name}",
        climate=f"climate.{name}",
        period_timer=f"timer.{name}_period",
        cooldown_timer=f"timer.{name}_cooldown",
        memory=f"input_text.{name}",
    )
    for name in ("one", "two")
]


def configuration(**inputs):
    path = ROOT / "blueprints/automation/salus_floor_comfort.yaml"
    bp = Blueprint(
        yaml_util.load_yaml_dict(str(path)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    instance = BlueprintInputs(
        bp,
        {
            "use_blueprint": {
                "path": str(path),
                "input": {"source": "weather.test", "rooms": deepcopy(ROOMS), **inputs},
            }
        },
    )
    instance.validate()
    return instance.async_substitute()


@pytest.fixture
async def env(tmp_path):
    with freeze_time(NOW, real_asyncio=True) as clock:
        hass = HomeAssistant(str(tmp_path))
        await hass.config.async_set_time_zone("Europe/Copenhagen")
        data = {
            "hass": hass,
            "clock": clock,
            "calls": [],
            "logs": [],
            "forecast_calls": 0,
            "delay": False,
        }
        data["rows"] = [
            {"datetime": (NOW + timedelta(hours=i)).isoformat(), "temperature": 2}
            for i in range(1, 50)
        ]
        hass.states.async_set(
            "weather.test", "cloudy", {"temperature": 14, "temperature_unit": "°C"}
        )
        for room in ROOMS:
            hass.states.async_set(
                room["comfort"],
                "off",
                {"options": ["off", "level_1", "level_2", "level_3"]},
            )
            hass.states.async_set(room["climate"], "heat", {"current_temperature": 22})
            hass.states.async_set(room["memory"], "", {"max": 255})
            for key in ("period_timer", "cooldown_timer"):
                hass.states.async_set(room[key], "idle", {"restore": True})

        async def forecast(call):
            data["forecast_calls"] += 1
            if data.get("forecast_error"):
                raise HomeAssistantError("offline")
            return {"weather.test": {"forecast": deepcopy(data["rows"])}}

        async def select(call):
            data["calls"].append((call.data["entity_id"], call.data["option"]))
            if data.get("write_error"):
                raise HomeAssistantError("lost reply")
            if not data["delay"]:
                hass.states.async_set(
                    call.data["entity_id"],
                    call.data["option"],
                    {"options": ["off", "level_1", "level_2", "level_3"]},
                )

        async def text(call):
            value = call.data["value"]
            assert isinstance(value, str) and len(value) <= 255, (len(value), value)
            hass.states.async_set(call.data["entity_id"], value, {"max": 255})

        async def timer_start(call):
            duration = float(call.data["duration"])
            end = datetime.now(UTC) + timedelta(seconds=duration)
            hass.states.async_set(
                call.data["entity_id"],
                "active" if duration else "idle",
                {"restore": True, "finishes_at": end.isoformat()},
            )

        async def timer_cancel(call):
            hass.states.async_set(call.data["entity_id"], "idle", {"restore": True})

        async def log(call):
            data["logs"].append(dict(call.data))

        hass.services.async_register(
            "weather",
            "get_forecasts",
            forecast,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register("select", "select_option", select)
        hass.services.async_register("input_text", "set_value", text)
        hass.services.async_register("timer", "start", timer_start)
        hass.services.async_register("timer", "cancel", timer_cancel)
        hass.services.async_register("logbook", "log", log)
        yield data
        await hass.async_stop()


async def run(env, **inputs):
    config = configuration(**inputs)
    script = Script(
        env["hass"],
        cv.SCRIPT_SCHEMA(config.get("actions", config.get("action"))),
        "comfort test",
        "automation",
        script_mode="queued",
    )
    await script.async_run(config["variables"], context=Context())
    await env["hass"].async_block_till_done()


def memory(env, room="one"):
    return json.loads(env["hass"].states.get(f"input_text.{room}").state or "{}")


def tick(env, seconds):
    env["clock"].tick(seconds)
    now = datetime.now(UTC)
    for state in list(env["hass"].states.async_all("timer")):
        if (
            state.state == "active"
            and datetime.fromisoformat(state.attributes["finishes_at"]) <= now
        ):
            env["hass"].states.async_set(state.entity_id, "idle", {"restore": True})


async def start(env, **inputs):
    await run(env, **inputs)
    await run(env, **inputs)


def outside(env, value):
    env["hass"].states.async_set(
        "weather.test", "cloudy", {"temperature": value, "temperature_unit": "°C"}
    )


async def test_full_automation_schema_and_no_custom_service(env):
    assert PLATFORM_SCHEMA(configuration())
    text = (ROOT / "blueprints/automation/salus_floor_comfort.yaml").read_text(
        encoding="utf-8"
    )
    assert "salus.evaluate_comfort_rule" not in text
    assert "state_changed" not in text


async def test_warm_now_still_starts_on_future_cold_and_protects_minimum(env):
    await start(env)
    assert env["calls"] == [("select.one", "level_1"), ("select.two", "level_1")]
    assert memory(env)["p"] == "active"
    assert memory(env)["d"] == NOW.timestamp() + 4 * 3600
    tick(env, 3600)
    await run(env)
    assert len(env["calls"]) == 2
    assert env["forecast_calls"] == 1


async def test_delayed_confirmation_does_not_start_minimum_early_or_block_other_room(
    env,
):
    env["delay"] = True
    await run(env)
    assert memory(env)["p"] == "starting" and memory(env)["s"] == 0
    assert len(env["calls"]) == 2
    tick(env, 20)
    env["hass"].states.async_set(
        "select.one", "level_1", {"options": ["off", "level_1", "level_2", "level_3"]}
    )
    await run(env)
    assert memory(env)["s"] == NOW.timestamp() + 20
    assert memory(env)["d"] == NOW.timestamp() + 20 + 4 * 3600
    assert memory(env, "two")["p"] == "starting"


async def test_optimistic_level_does_not_count_as_confirmation(env):
    env["delay"] = True
    await run(env)
    env["hass"].states.async_set(
        "select.one",
        "level_1",
        {"options": ["off", "level_1", "level_2", "level_3"], "assumed_state": True},
    )
    await run(env)
    assert memory(env)["p"] == "starting" and memory(env)["s"] == 0


async def test_per_room_hold_does_not_keep_warm_room_on(env):
    await start(env, use_room_minimum=True)
    env["hass"].states.async_set("climate.one", "heat", {"current_temperature": 20})
    tick(env, 4 * 3600)
    await run(env, use_room_minimum=True)
    assert memory(env)["p"] == "active" and memory(env)["h"]
    assert memory(env, "two")["p"] == "stopping"
    assert env["calls"][-1] == ("select.two", "off")


async def test_cold_extends_then_warm_stops_only_at_next_boundary(env):
    await start(env)
    outside(env, 4)
    tick(env, 4 * 3600)
    await run(env)
    assert memory(env)["d"] == NOW.timestamp() + 5 * 3600
    outside(env, 14)
    tick(env, 3500)
    await run(env)
    assert len(env["calls"]) == 2
    tick(env, 100)
    await run(env)
    await run(env)
    assert memory(env)["p"] == "cooldown"
    assert memory(env)["d"] == NOW.timestamp() + 11 * 3600
    assert env["calls"][-2:] == [("select.one", "off"), ("select.two", "off")]


async def test_upper_limit_overrides_minimum_only_for_its_room(env):
    await start(env, use_room_maximum=True)
    env["hass"].states.async_set("climate.one", "heat", {"current_temperature": 25})
    await run(env, use_room_maximum=True)
    await run(env, use_room_maximum=True)
    assert env["calls"][-1] == ("select.one", "off")
    assert memory(env)["r"] == "room_maximum"
    assert memory(env, "two")["p"] == "active"


async def test_manual_adoption_preserves_level_and_starts_its_own_clock(env):
    env["hass"].states.async_set(
        "select.one", "level_3", {"options": ["off", "level_1", "level_2", "level_3"]}
    )
    await run(env, adopt_manual=True)
    assert memory(env)["p"] == "active" and memory(env)["m"]
    assert memory(env)["l"] == "level_3"
    assert ("select.one", "level_1") not in env["calls"]


async def test_manual_unowned_room_is_not_adopted_by_default(env):
    env["hass"].states.async_set(
        "select.one", "level_3", {"options": ["off", "level_1", "level_2", "level_3"]}
    )
    await run(env)
    assert not memory(env)
    assert env["calls"] == [("select.two", "level_1")]


async def test_no_confirmation_creates_cooldown_without_automatic_replay(env):
    env["delay"] = True
    await run(env)
    tick(env, 151)
    await run(env)
    assert memory(env)["p"] == "cooldown"
    await run(env)
    assert len(env["calls"]) == 2


async def test_sensor_preferred_then_current_weather_fallback(env):
    env["hass"].states.async_set("sensor.outside", "4", {"unit_of_measurement": "°C"})
    await start(env, outdoor_sensor="sensor.outside")
    tick(env, 4 * 3600)
    await run(env, outdoor_sensor="sensor.outside")
    assert memory(env)["r"] == "outdoor_cold"
    env["hass"].states.async_set(
        "sensor.outside", "unavailable", {"unit_of_measurement": "°C"}
    )
    tick(env, 3600)
    await run(env, outdoor_sensor="sensor.outside")
    assert env["calls"][-1] == ("select.two", "off")


@pytest.mark.parametrize("temperature", [5, 8.2, 12])
async def test_equal_or_warm_forecast_does_not_start(env, temperature):
    for row in env["rows"]:
        row["temperature"] = temperature
    await run(env, start_below=5)
    assert env["calls"] == []


async def test_forecast_cold_outside_horizon_is_ignored(env):
    for i, row in enumerate(env["rows"]):
        row["temperature"] = 12 if i < 8 else 2
    await run(env, forecast_hours=8, start_below=8, stop_at=10)
    assert env["calls"] == []


async def test_duplicate_helpers_fail_before_any_write(env):
    rooms = deepcopy(ROOMS)
    rooms[1]["memory"] = rooms[0]["memory"]
    await run(env, rooms=rooms)
    assert env["calls"] == []


async def test_idle_timer_after_restart_evaluates_existing_period_without_reset(env):
    await start(env)
    original_start = memory(env)["s"]
    outside(env, 4)
    tick(env, 7 * 3600)  # Timer expired during downtime; timer.finished was missed.
    await run(env)
    assert memory(env)["s"] == original_start
    assert memory(env)["d"] == NOW.timestamp() + 8 * 3600
    assert len(env["calls"]) == 2


async def test_later_forecast_revisions_do_not_cancel_or_restart_active_rooms(env):
    await start(env)
    start_time = memory(env)["s"]
    for row in env["rows"]:
        row["temperature"] = 30
    env["forecast_error"] = True
    tick(env, 3600)
    await run(env)
    assert memory(env)["s"] == start_time
    assert memory(env)["d"] == NOW.timestamp() + 4 * 3600
    assert len(env["calls"]) == 2
    assert env["forecast_calls"] == 1


async def test_missing_indoor_reading_extends_only_its_room(env):
    await start(env, use_room_minimum=True)
    env["hass"].states.async_set("climate.one", "unavailable")
    tick(env, 4 * 3600)
    await run(env, use_room_minimum=True)
    assert memory(env)["r"] == "room_missing"
    assert env["calls"][-1] == ("select.two", "off")


async def test_unknown_upper_limit_temperature_blocks_only_new_starts_for_that_room(
    env,
):
    env["hass"].states.async_set("climate.one", "unavailable")
    await run(env, use_room_maximum=True)
    assert env["calls"] == [("select.two", "level_1")]


async def test_manual_off_creates_pause_without_automatically_overwriting_it(env):
    await start(env)
    env["hass"].states.async_set(
        "select.one", "off", {"options": ["off", "level_1", "level_2", "level_3"]}
    )
    await run(env)
    assert memory(env)["p"] == "cooldown"
    tick(env, 100)
    await run(env)
    assert len(env["calls"]) == 2


async def test_stop_timeout_schedules_a_fresh_evaluation_without_immediate_replay(env):
    await start(env)
    env["delay"] = True
    tick(env, 4 * 3600)
    await run(env)
    assert len(env["calls"]) == 4
    tick(env, 151)
    await run(env)
    assert memory(env)["r"] == "timeout"
    assert memory(env)["d"] == NOW.timestamp() + 4 * 3600 + 151 + 300
    await run(env)
    assert len(env["calls"]) == 4


@pytest.mark.parametrize("kind", ["missing", "nan", "duplicate", "gap", "boolean"])
async def test_invalid_forecasts_cannot_start_rooms(env, kind):
    if kind == "missing":
        env["rows"][2].pop("temperature")
    elif kind == "nan":
        env["rows"][2]["temperature"] = float("nan")
    elif kind == "boolean":
        env["rows"][2]["temperature"] = True
    elif kind == "duplicate":
        env["rows"][2]["datetime"] = env["rows"][1]["datetime"]
    else:
        env["rows"][2]["datetime"] = (NOW + timedelta(hours=40)).isoformat()
    await run(env)
    assert env["calls"] == []


async def test_unavailable_weather_does_not_start_from_a_cached_forecast(env):
    env["hass"].states.async_set(
        "weather.test", "unavailable", {"temperature": 14, "temperature_unit": "°C"}
    )
    await run(env)
    assert env["calls"] == []


async def test_native_reactive_trigger_tracks_selected_rooms_and_upper_limit(env):
    from homeassistant.components.template.trigger import (
        TRIGGER_SCHEMA,
        async_attach_trigger,
    )

    await start(env, use_room_maximum=True)
    config = configuration(use_room_maximum=True)
    triggers = config.get("triggers", config.get("trigger"))
    trigger = TRIGGER_SCHEMA(triggers[-1])
    seen = []

    async def act(variables, context=None):
        seen.append(variables)
        await run(env, use_room_maximum=True)

    cancel = await async_attach_trigger(
        env["hass"],
        trigger,
        act,
        {
            "trigger_data": {"id": "reactive", "idx": "3"},
            "variables": config["variables"],
        },
    )
    env["hass"].states.async_set(
        "climate.unrelated", "heat", {"current_temperature": 40}
    )
    await env["hass"].async_block_till_done()
    assert not seen
    env["hass"].states.async_set("climate.one", "heat", {"current_temperature": 25})
    await env["hass"].async_block_till_done()
    cancel()
    assert seen
    assert ("select.one", "off") in env["calls"]
    assert ("select.two", "off") not in env["calls"]


async def test_fahrenheit_forecast_sensor_and_room_are_converted(env):
    env["hass"].states.async_set(
        "weather.test", "cloudy", {"temperature": 57.2, "temperature_unit": "°F"}
    )
    env["hass"].states.async_set("sensor.outdoor", "50", {"unit_of_measurement": "°F"})
    for row in env["rows"]:
        row["temperature"] = 35.6
    for room in ROOMS:
        env["hass"].states.async_set(
            room["climate"], "heat", {"current_temperature": 71.6}
        )
    inputs = dict(
        outdoor_sensor="sensor.outdoor",
        room_temperature_unit="°F",
        use_room_minimum=True,
    )
    await start(env, **inputs)
    assert memory(env)["t"] == 2
    assert memory(env)["o"] == 10
    tick(env, 4 * 3600)
    await run(env, **inputs)
    assert env["calls"][-2:] == [("select.one", "off"), ("select.two", "off")]


async def test_unavailable_floor_does_not_block_another_room(env):
    env["hass"].states.async_set(
        "select.one",
        "unavailable",
        {"options": ["off", "level_1", "level_2", "level_3"]},
    )
    await run(env)
    assert env["calls"] == [("select.two", "level_1")]


async def test_text_helper_with_default_short_maximum_is_rejected(env):
    env["hass"].states.async_set("input_text.one", "", {"max": 100})
    await run(env)
    assert not env["calls"]


async def test_danish_import_has_identical_control_logic_and_valid_schema(env):
    english = yaml_util.load_yaml_dict(
        str(ROOT / "blueprints/automation/salus_floor_comfort.yaml")
    )
    danish = yaml_util.load_yaml_dict(
        str(ROOT / "blueprints/automation/salus_floor_comfort_da.yaml")
    )
    bp = Blueprint(
        deepcopy(danish),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    instance = BlueprintInputs(
        bp,
        {
            "use_blueprint": {
                "path": "test.yaml",
                "input": {"source": "weather.test", "rooms": deepcopy(ROOMS)},
            }
        },
    )
    instance.validate()
    PLATFORM_SCHEMA(instance.async_substitute())
    english.pop("blueprint")
    danish.pop("blueprint")
    assert english == danish
