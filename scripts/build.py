import json
from copy import deepcopy
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
for directory in ("blueprints/automation", "tests", ".github/workflows", "examples"):
    (root / directory).mkdir(parents=True, exist_ok=True)


class Input(str):
    pass


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(
    Input, lambda dumper, value: dumper.represent_scalar("!input", str(value))
)


def variable(**values):
    return {"variables": values}


def condition(value):
    return {"condition": "template", "value_template": value}


def service(action, data=None, **kw):
    return {"action": action, **({"data": data} if data else {}), **kw}


def choose(test, sequence, otherwise=None):
    result = {"choose": [{"conditions": test, "sequence": sequence}]}
    if otherwise is not None:
        result["default"] = otherwise
    return result


def save(expression):
    return service(
        "input_text.set_value",
        {
            "entity_id": "{{ room.memory }}",
            "value": "{{ " + expression + " | to_json }}",
        },
    )


def timer(which, seconds):
    return service(
        "timer.start", {"entity_id": "{{ room." + which + " }}", "duration": seconds}
    )


def cancel(which):
    return service("timer.cancel", {"entity_id": "{{ room." + which + " }}"})


def log(message):
    return service(
        "logbook.log",
        {
            "name": "{{ room.name }}",
            "entity_id": "{{ room.comfort }}",
            "message": message,
        },
    )


def switch(level):
    return service(
        "select.select_option",
        {"entity_id": "{{ room.comfort }}", "option": level},
        continue_on_error=True,
    )


def label(name, description, selector, default=None):
    value = {"name": name, "description": description, "selector": selector}
    if default is not None:
        value["default"] = default
    return value


def number(low, high, step, unit):
    return {
        "number": {
            "min": low,
            "max": high,
            "step": step,
            "unit_of_measurement": unit,
            "mode": "box",
        }
    }


def entity(domain):
    return {"entity": {"domain": domain}}


inputs = {
    "weather_section": {
        "name": "1. Forecast and outdoor measurement",
        "input": {
            "source": label(
                "Weather forecast",
                "Start always uses a complete hourly forecast. Select a weather entity with hourly forecasts.",
                entity("weather"),
            ),
            "outdoor_sensor": label(
                "Outdoor sensor for stopping (optional)",
                "At period boundaries this measured temperature is preferred. If missing or invalid, the weather entity current temperature is used. Forecast values never decide stopping.",
                entity("sensor"),
                "",
            ),
        },
    },
    "rooms_section": {
        "name": "2. Rooms and independent helpers",
        "input": {
            "rooms": label(
                "Rooms",
                "Add each room once. Create TWO Timer helpers with Restore enabled and ONE Text helper with maximum length 255 per room. Select the correct climate and floor select for each room. Never share timers or memory helpers between rooms or automations.",
                {
                    "object": {
                        "multiple": True,
                        "label_field": "name",
                        "fields": {
                            "name": {
                                "label": "Room name",
                                "required": True,
                                "selector": {"text": {}},
                            },
                            "comfort": {
                                "label": "Floor comfort select",
                                "required": True,
                                "selector": entity("select"),
                            },
                            "climate": {
                                "label": "Room thermostat (required for indoor limits)",
                                "required": True,
                                "selector": entity("climate"),
                            },
                            "period_timer": {
                                "label": "Period timer – Restore enabled",
                                "required": True,
                                "selector": entity("timer"),
                            },
                            "cooldown_timer": {
                                "label": "Cooldown timer – Restore enabled",
                                "required": True,
                                "selector": entity("timer"),
                            },
                            "memory": {
                                "label": "Room status Text helper – max length 255",
                                "required": True,
                                "selector": entity("input_text"),
                            },
                        },
                    }
                },
            ),
            "level": label(
                "Comfort level for new starts",
                "Only new automatic starts use this level. Optional adoption preserves an already-active manual level.",
                {"select": {"options": ["level_1", "level_2", "level_3"]}},
                "level_1",
            ),
        },
    },
    "start_section": {
        "name": "3. Starting and protected periods",
        "input": {
            "forecast_hours": label(
                "Forecast horizon",
                "If any hourly forecast in this future window is below the start threshold, an eligible room can start now as preheating. Later forecast revisions do not cancel an active protected period.",
                number(1, 48, 1, "h"),
                8,
            ),
            "start_below": label(
                "Start below",
                "Strictly below this Celsius value. Exactly the threshold does not start comfort. Measured outdoor or room temperature alone never starts comfort.",
                number(-50, 40, 0.5, "°C"),
                5,
            ),
            "min_runtime_hours": label(
                "Minimum runtime",
                "The full first period starts on device confirmation, or at the qualifying adoption check. Repeated checks and restarts do not reset an existing active period.",
                number(0.25, 168, 0.25, "h"),
                4,
            ),
            "extension_hours": label(
                "Extension per evaluation",
                "At a period boundary, give this room a new complete period if it is still cold outside, indoor hold is active, or stop data is missing.",
                number(0.25, 24, 0.25, "h"),
                1,
            ),
        },
    },
    "stop_section": {
        "name": "4. Stopping",
        "input": {
            "stop_at": label(
                "Stop at or above",
                "After a protected period, stop if the CURRENT outdoor temperature is at/above this Celsius threshold and this room does not need minimum-temperature hold. Must exceed the start threshold.",
                number(-40, 60, 0.5, "°C"),
                7,
            )
        },
    },
    "indoor_section": {
        "name": "5. Indoor hold and upper limit",
        "collapsed": True,
        "input": {
            "use_room_minimum": label(
                "Enable indoor minimum hold",
                "A cold room may keep its OWN active comfort running. It cannot start comfort and cannot keep other rooms running.",
                {"boolean": {}},
                False,
            ),
            "room_minimum": label(
                "Indoor minimum",
                "Below this Celsius temperature, hold an already-active room at its next boundary.",
                number(5, 35, 0.5, "°C"),
                21,
            ),
            "room_margin": label(
                "Indoor hold release margin",
                "Release the indoor hold at minimum plus this margin. Example: 21 + 0.5 = 21.5 °C.",
                number(0.1, 5, 0.1, "°C"),
                0.5,
            ),
            "use_room_maximum": label(
                "Stop immediately at upper room limit",
                "A new valid room reading at/above the upper limit can stop an owned room even during minimum runtime or an extension. Manual unowned rooms are not changed.",
                {"boolean": {}},
                False,
            ),
            "room_maximum": label(
                "Upper room limit",
                "Celsius. Must exceed indoor minimum plus margin when indoor minimum hold is enabled. Missing room readings block NEW starts when this protection is enabled.",
                number(5, 40, 0.5, "°C"),
                25,
            ),
            "room_temperature_unit": label(
                "Home Assistant temperature unit",
                "Climate temperatures use your Home Assistant unit. Choose °F only when your HA installation uses Fahrenheit. All thresholds above remain Celsius.",
                {"select": {"options": ["°C", "°F"]}},
                "°C",
            ),
        },
    },
    "manual_section": {
        "name": "6. Manual control and pause",
        "collapsed": True,
        "input": {
            "adopt_manual": label(
                "Adopt already-active rooms",
                "Only when the forecast start condition is satisfied and cooldown has expired: keep the manual level and begin a NEW minimum period at this adoption check. Otherwise manual comfort stays unowned.",
                {"boolean": {}},
                False,
            ),
            "cooldown_hours": label(
                "Minimum pause before a new start",
                "After confirmed stop or an external level change, block new automatic starts/adoption for this room. Timers continue across restart and while the automation is disabled.",
                number(0, 168, 0.25, "h"),
                6,
            ),
        },
    },
}
keys = [key for section in inputs.values() for key in section["input"]]

validation = r"""{% set ns=namespace(ok=rooms is sequence and rooms is not string and rooms|count>0, ids=[]) %}
{% for room in rooms if rooms is sequence and rooms is not string %}
 {% for key,domain in [('comfort','select.'),('climate','climate.'),('period_timer','timer.'),('cooldown_timer','timer.'),('memory','input_text.')] %}
  {% set value=room.get(key,'') if room is mapping else '' %}
  {% if value is not string or not value.startswith(domain) %}{% set ns.ok=false %}{% endif %}
  {% if key in ['period_timer','cooldown_timer','memory'] and states(value) in ['unknown','unavailable'] %}{% set ns.ok=false %}{% endif %}
  {% if key != 'climate' %}{% if value in ns.ids %}{% set ns.ok=false %}{% endif %}{% set ns.ids=ns.ids+[value] %}{% endif %}
 {% endfor %}
 {% if room is mapping %}
  {% set raw=states(room.get('memory','input_text.none')) %}{% set m=raw|from_json({}) %}
  {% if raw|trim and (m is not mapping or m.get('v')!=1) %}{% set ns.ok=false %}{% endif %}
  {% if (state_attr(room.memory,'max')|int(0))<255 %}{% set ns.ok=false %}{% endif %}
  {% if ['off','level_1','level_2','level_3']|reject('in',state_attr(room.comfort,'options') or [])|list|count %}{% set ns.ok=false %}{% endif %}
 {% endif %}
{% endfor %}
{{ ns.ok and stop_at>start_below and (not use_room_minimum or not use_room_maximum or room_maximum>room_minimum+room_margin) }}"""

# This template tracks only the selected room entities/helpers. No global
# state_changed listener, custom integration service, or per-minute poll exists.
reactive = r"""{% set ns=namespace(changed=false) %}
{% for room in rooms %}
 {% set m=states(room.memory)|from_json({}) %}{% set p=m.get('p','idle') if m is mapping else 'idle' %}
 {% set actual=states(room.comfort) %}{% set known=actual in ['off','level_1','level_2','level_3'] and not state_attr(room.comfort,'assumed_state') %}
 {% set raw=state_attr(room.climate,'current_temperature') %}
 {% set temp=((raw|float-32)*5/9 if room_temperature_unit=='°F' else raw|float) if is_number(raw) and raw is not boolean else none %}
 {% if p in ['starting','stopping'] and ((known and (actual==m.get('l') if p=='starting' else actual=='off')) or is_state(room.period_timer,'idle')) %}{% set ns.changed=true %}{% endif %}
 {% if p=='active' and known %}
  {% if actual!=m.get('l') or is_state(room.period_timer,'idle') %}{% set ns.changed=true %}{% endif %}
  {% if use_room_maximum and temp is not none and temp>=room_maximum and m.get('r')!='timeout' %}{% set ns.changed=true %}{% endif %}
  {% if use_room_minimum and temp is not none and ((not m.get('h',false) and temp<room_minimum) or (m.get('h',false) and temp>=room_minimum+room_margin)) %}{% set ns.changed=true %}{% endif %}
 {% endif %}
 {% if p=='cooldown' and is_state(room.cooldown_timer,'idle') %}{% set ns.changed=true %}{% endif %}
{% endfor %}{{ ns.changed }}"""

outside = r"""{% set ns=namespace(value=none) %}
{% for id in [outdoor_sensor,source] if id %}
 {% if ns.value is none and states(id) not in ['unknown','unavailable'] %}
  {% set weather=id.startswith('weather.') %}{% set raw=state_attr(id,'temperature') if weather else states(id) %}
  {% set unit=state_attr(id,'temperature_unit' if weather else 'unit_of_measurement') %}
  {% if is_number(raw) and raw is not boolean and unit in ['°C','°F'] %}{% set ns.value=((raw|float-32)*5/9 if unit=='°F' else raw|float)|round(3) %}{% endif %}
 {% endif %}
{% endfor %}{{ ns.value }}"""
need_forecast = r"""{% set ns=namespace(needed=false) %}{% for room in rooms %}
{% set m=states(room.memory)|from_json({}) %}{% set p=m.get('p','idle') %}
{% if p=='idle' or (p=='cooldown' and is_state(room.cooldown_timer,'idle')) %}
 {% if not state_attr(room.comfort,'assumed_state') and (is_state(room.comfort,'off') or adopt_manual) %}{% set ns.needed=true %}{% endif %}
{% endif %}{% endfor %}{{ ns.needed and states(source) not in ['unknown','unavailable'] }}"""
forecast = r"""{% set response=forecast_response|default({},true) %}
{% set data=response.get(source,{}) if response is mapping else {} %}
{% set rawrows=data.get('forecast',[]) if data is mapping else [] %}
{% set rows=rawrows if rawrows is sequence and rawrows is not string else [] %}
{% set ns=namespace(points=[],valid=true) %}{% set unit=state_attr(source,'temperature_unit') %}
{% for row in rows if row is mapping %}
 {% set date=as_datetime(row.get('datetime'),none) %}
 {% if date is not none and date.tzinfo is not none %}
  {% set stamp=as_timestamp(date) %}
  {% if now_ts<=stamp<=now_ts+forecast_hours*3600 %}
   {% set raw=row.get('temperature') %}
   {% if is_number(raw) and raw is not boolean and unit in ['°C','°F'] %}
    {% set temp=((raw|float-32)*5/9 if unit=='°F' else raw|float)|round(3) %}
    {% set ns.points=ns.points+[dict(at=stamp|int,temp=temp)] %}
   {% else %}{% set ns.valid=false %}{% endif %}
  {% endif %}
 {% else %}{% set ns.valid=false %}{% endif %}
{% endfor %}
{% set points=ns.points|sort(attribute='at') %}
{% if points|count<forecast_hours or points|map(attribute='at')|unique|list|count!=points|count %}{% set ns.valid=false %}{% endif %}
{% if points %}
 {% if points[0].at>now_ts+3600 or points[-1].at<now_ts+forecast_hours*3600-3600 %}{% set ns.valid=false %}{% endif %}
 {% for point in points[1:] %}{% if point.at-points[loop.index0].at>3601 %}{% set ns.valid=false %}{% endif %}{% endfor %}
{% endif %}
{{ (points|sort(attribute='temp')|first) if ns.valid and points else dict(at=0,temp=none) }}"""


def cooldown(reason):
    return [
        cancel("period_timer"),
        save(
            "dict(m,v=1,p='cooldown',d=now_ts+cooldown_hours*3600,r="
            + (repr(reason) if reason else "m.get('r','warm')")
            + ",x=now_ts if actual=='off' else m.get('x',0))"
        ),
        timer("cooldown_timer", "{{ cooldown_hours*3600 }}"),
    ]


finish_start = [
    save("dict(m,v=1,p='active',s=now_ts,d=now_ts+min_runtime_hours*3600,r='minimum')"),
    timer("period_timer", "{{ min_runtime_hours*3600 }}"),
    log(
        "Device-confirmed comfort {{ actual }}. Protected minimum period starts now; next evaluation {{ (now_ts+min_runtime_hours*3600)|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}."
    ),
]


def stop(reason):
    return [
        save("dict(m,v=1,p='stopping',d=now_ts+150,r='" + reason + "')"),
        timer("period_timer", 150),
        log(
            "Stop requested ({{ 'upper room limit' if "
            + repr(reason)
            + "=='room_maximum' else 'period ended and warm outside' }}). Outside now: {{ outside_c }} °C; stop threshold: {{ stop_at }} °C. Room: {{ room_c }} °C; upper limit: {{ room_maximum if use_room_maximum else 'disabled' }} °C. Awaiting device confirmation."
        ),
        switch("off"),
    ]


active = [
    choose(
        "{{ known and actual != m.get('l') }}",
        cooldown("manual")
        + [
            log(
                "External level change observed ({{ actual }}); ownership ended. Cooldown starts now."
            )
        ],
        [
            choose(
                "{{ known and use_room_maximum and room_c is not none and room_c>=room_maximum and (m.get('r')!='timeout' or due) }}",
                stop("room_maximum"),
                [
                    choose(
                        "{{ known and due }}",
                        [
                            choose(
                                "{{ outside_c is not none and outside_c>=stop_at and not held and not (use_room_minimum and room_c is none) }}",
                                stop("warm"),
                                [
                                    variable(
                                        reason="{{ 'room_missing' if use_room_minimum and room_c is none else 'room_hold' if held else 'outdoor_missing' if outside_c is none else 'outdoor_cold' }}"
                                    ),
                                    save(
                                        "dict(m,v=1,p='active',h=held,d=now_ts+extension_hours*3600,r=reason)"
                                    ),
                                    timer("period_timer", "{{ extension_hours*3600 }}"),
                                    log(
                                        "Period extended for this room ({{ reason }}). Outside now: {{ outside_c }} °C; stop threshold: {{ stop_at }} °C. Room: {{ room_c }} °C. Next evaluation {{ (now_ts+extension_hours*3600)|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}."
                                    ),
                                ],
                            )
                        ],
                        [
                            choose(
                                "{{ held!=m.get('h',false) }}", [save("dict(m,h=held)")]
                            ),
                            choose(
                                "{{ is_state(room.period_timer,'idle') and now_ts<m.get('d',0) }}",
                                [timer("period_timer", "{{ [1,m.d-now_ts]|max }}")],
                            ),
                        ],
                    )
                ],
            )
        ],
    )
]

starting = [
    choose(
        "{{ known and actual==m.get('l') }}",
        finish_start,
        [
            choose(
                "{{ known and actual not in ['off',m.get('l')] }}",
                cooldown("manual")
                + [
                    log(
                        "A different device level was observed during start; it is preserved and cooldown begins."
                    )
                ],
                [
                    choose(
                        "{{ due }}",
                        cooldown("timeout")
                        + [
                            log(
                                "Start was not device-confirmed before the timeout. No immediate retry; check the device. Cooldown begins."
                            )
                        ],
                    )
                ],
            )
        ],
    )
]
stopping = [
    choose(
        "{{ known and actual=='off' }}",
        cooldown(None)
        + [
            log(
                "Switch-off device-confirmed. Earliest new start {{ (now_ts+cooldown_hours*3600)|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}."
            )
        ],
        [
            choose(
                "{{ due }}",
                [
                    save("dict(m,v=1,p='active',d=now_ts+300,r='timeout')"),
                    timer("period_timer", 300),
                    log(
                        "Switch-off was not confirmed. No immediate replay; a fresh stop evaluation is scheduled in five minutes. Other rooms remain independent."
                    ),
                ],
            )
        ],
    )
]

new_memory = "dict(v=1,p='starting',l=level,s=0,d=now_ts+150,t=forecast.temp,a=forecast.at,f=now_ts,o=outside_c,b=start_below,m=false,h=false,r='minimum',q=now_ts,x=m.get('x',0))"
start_actions = [
    save(new_memory),
    timer("period_timer", 150),
    log(
        "Start requested: forecast minimum {{ forecast.temp }} °C at {{ forecast.at|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}, below {{ start_below }} °C within {{ forecast_hours }} hours. Forecast fetched {{ now_ts|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}. Outside now: {{ outside_c }} °C. Requested {{ level }}; minimum period {{ min_runtime_hours }} hours starts on device confirmation."
    ),
    switch("{{ level }}"),
]
adopt_memory = "dict(v=1,p='active',l=actual,s=now_ts,d=now_ts+min_runtime_hours*3600,t=forecast.temp,a=forecast.at,f=now_ts,o=outside_c,b=start_below,m=true,h=false,r='adopted',q=now_ts,x=m.get('x',0))"
idle = [
    choose(
        "{{ (phase!='cooldown' or is_state(room.cooldown_timer,'idle')) and known and forecast.temp is not none and forecast.temp<start_below }}",
        [
            choose(
                "{{ actual=='off' and (not use_room_maximum or (room_c is not none and room_c<room_maximum)) }}",
                start_actions,
                [
                    choose(
                        "{{ actual in ['level_1','level_2','level_3'] and adopt_manual }}",
                        [
                            save(adopt_memory),
                            timer("period_timer", "{{ min_runtime_hours*3600 }}"),
                            log(
                                "Already-active comfort adopted at {{ actual }} without a level write. Minimum period starts now. Forecast {{ forecast.temp }} °C at {{ forecast.at|timestamp_custom('%d-%m-%Y %H:%M:%S',true) }}; start threshold below {{ start_below }} °C; outside now {{ outside_c }} °C."
                            ),
                        ],
                    )
                ],
            )
        ],
        [
            choose(
                "{{ phase=='cooldown' and is_state(room.cooldown_timer,'idle') }}",
                [save("dict(m,p='idle',r='forecast_wait')")],
            )
        ],
    )
]

room_actions = [
    variable(room="{{ repeat.item }}"),
    variable(
        m="{{ states(room.memory)|from_json({}) }}", actual="{{ states(room.comfort) }}"
    ),
    variable(
        phase="{{ m.get('p','idle') }}",
        known="{{ actual in ['off','level_1','level_2','level_3'] and not state_attr(room.comfort,'assumed_state') }}",
        room_c="{% set raw=state_attr(room.climate,'current_temperature') %}{{ ((raw|float-32)*5/9 if room_temperature_unit=='°F' else raw|float) if states(room.climate) not in ['unknown','unavailable'] and is_number(raw) and raw is not boolean else none }}",
        due="{{ is_state(room.period_timer,'idle') and now_ts>=m.get('d',0) }}",
    ),
    variable(
        held="{{ false if not use_room_minimum else true if room_c is not none and room_c<room_minimum else false if room_c is not none and room_c>=room_minimum+room_margin else m.get('h',false) }}"
    ),
    {
        "choose": [
            {"conditions": "{{ phase=='stopping' }}", "sequence": stopping},
            {"conditions": "{{ phase=='starting' }}", "sequence": starting},
            {"conditions": "{{ phase=='active' }}", "sequence": active},
        ],
        "default": idle,
    },
]

document = {
    "blueprint": {
        "name": "SALUS – forecast comfort for multiple independent rooms",
        "domain": "automation",
        "description": "One shared automation, independent standard helpers per room. Forecast starts comfort; protected minimum periods are followed by current-outdoor stop checks. No custom SALUS service, Python controller or custom store. Requires matching Off/level_1/level_2/level_3 selects. Use Restore on timers and max length 255 on Text helpers. See repository setup and migration guide.",
        "homeassistant": {"min_version": "2026.2.0"},
        "source_url": "https://github.com/MichaelBusackBertelsen/salus-comfort-blueprint/blob/main/blueprints/automation/salus_floor_comfort.yaml",
        "input": inputs,
    },
    "variables": {key: Input(key) for key in keys},
    "trigger": [
        {"platform": "time_pattern", "minutes": "/15"},
        {"platform": "homeassistant", "event": "start"},
        {"platform": "event", "event_type": "timer.finished"},
        {"platform": "template", "value_template": reactive},
    ],
    "condition": [
        {
            "condition": "template",
            "value_template": "{{ trigger is not defined or trigger.platform!='event' or trigger.event.data.entity_id in (rooms|map(attribute='period_timer')|list + rooms|map(attribute='cooldown_timer')|list) }}",
        }
    ],
    "action": [
        variable(configuration_valid=validation),
        choose(
            "{{ not configuration_valid }}",
            [
                {
                    "stop": "Check room helper IDs, uniqueness, Text max=255, available entities and ordered thresholds.",
                    "error": True,
                }
            ],
        ),
        variable(
            now_ts="{{ as_timestamp(now())|int }}",
            outside_c=outside,
            forecast_response={},
        ),
        choose(
            need_forecast,
            [
                service(
                    "weather.get_forecasts",
                    {"entity_id": "{{ source }}", "type": "hourly"},
                    response_variable="forecast_response",
                    continue_on_error=True,
                )
            ],
        ),
        variable(forecast=forecast),
        {"repeat": {"for_each": "{{ rooms }}", "sequence": room_actions}},
    ],
    "mode": "queued",
    "max": 20,
    "max_exceeded": "silent",
    "trace": {"stored_traces": 30},
}

# Both importable variants share all control logic. Only form labels differ.
notice = (
    "\n".join(
        "# " + line
        for line in (root / "LICENSE").read_text(encoding="utf-8").splitlines()
    )
    + "\n\n"
)


def write_variant(name, content):
    (root / "blueprints" / "automation" / name).write_text(
        notice
        + yaml.dump(
            content, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=110
        ),
        encoding="utf-8",
    )


write_variant("salus_floor_comfort.yaml", document)
translated = deepcopy(document)
metadata = json.loads((root / "translations" / "da.json").read_text(encoding="utf-8"))
bp = translated["blueprint"]
bp["name"] = metadata["name"]
bp["description"] = metadata["description"]
bp["source_url"] = bp["source_url"].replace(
    "salus_floor_comfort.yaml", "salus_floor_comfort_da.yaml"
)
for key, section in bp["input"].items():
    section["name"] = metadata["sections"][key]
    for input_key, value in section["input"].items():
        if input_key in metadata["inputs"]:
            value.update(metadata["inputs"][input_key])
fields = bp["input"]["rooms_section"]["input"]["rooms"]["selector"]["object"]["fields"]
for key, value in fields.items():
    value["label"] = metadata["fields"][key]
write_variant("salus_floor_comfort_da.yaml", translated)
