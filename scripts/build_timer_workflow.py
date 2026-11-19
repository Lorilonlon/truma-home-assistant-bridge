#!/usr/bin/env python3
"""Build reviewable HA configs for the dashboard's persistent start timer.

No live calls. Install through HA's config API; see dashboard/TIMER.md.
Templates are necessary for validation of a submitted form, stored JSON and
calendar arithmetic. Device conditions/actions otherwise use native HA types.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = 'input_text.truma_timer_auftrag'
PREVIOUS = 'input_text.truma_timer_vorher'
WHEN = 'input_datetime.truma_timer_termin'
CLIMATE = 'climate.truma_inet_heizung'
WATER = 'select.truma_inet_warmwasser'
SCRIPT = 'script.truma_timer_verwalten'
OWNER = 'input_text.truma_timer_aktuell'
SLOTS = 8
JOBS = [JOB] + [JOB + '_' + str(i + 1) for i in range(1, SLOTS)]
PREVIOUS_SLOTS = [PREVIOUS] + [PREVIOUS + '_' + str(i + 1) for i in range(1, SLOTS)]
WHEN_SLOTS = [WHEN] + [WHEN + '_' + str(i + 1) for i in range(1, SLOTS)]

# Compare local wall-clock intervals. For repeating schedules it suffices to
# consider the cycles around the later first start (including overnight).
# This exact calculation is independently implemented in the browser; the
# server re-reads every job before accepting the user's overlap consent.
OVERLAPS = """{% set out = namespace(ids=[]) %}
{% set a0 = as_local(as_datetime(start_ts)) %}
{% set a = a0.date().toordinal()*1440+a0.hour*60+a0.minute %}
{% set ae0 = as_local(as_datetime(end_ts)) if end_ts else none %}
{% set alen = ae0.date().toordinal()*1440+ae0.hour*60+ae0.minute-a if ae0 else 1000000000 %}
{% for ent in job_entities %}{% set other = states(ent) | from_json({}) %}
{% if ent != job_entity and other.get('p') in ['armed','waiting','executing','running','restoring'] %}
{% set b0 = as_local(as_datetime(other.s)) %}
{% set b = b0.date().toordinal()*1440+b0.hour*60+b0.minute %}
{% set be0 = as_local(as_datetime(other.e)) if other.e else none %}
{% set blen = be0.date().toordinal()*1440+be0.hour*60+be0.minute-b if be0 else 1000000000 %}
{% set base = [a,b] | max %}{% set ka = ((base-a)/1440) | int %}{% set kb = ((base-b)/1440) | int %}
{% set hit = namespace(yes=false) %}
{% for i in ([0,ka-1,ka,ka+1] if daily else [0]) %}{% for k in ([0,kb-1,kb,kb+1] if other.d else [0]) %}
{% if i >= 0 and k >= 0 and a+i*1440 < b+k*1440+blen and b+k*1440 < a+i*1440+alen %}{% set hit.yes=true %}{% endif %}
{% endfor %}{% endfor %}{% if hit.yes %}{% set out.ids=out.ids+[other.id] %}{% endif %}
{% endif %}{% endfor %}{{ out.ids | sort }}"""

def template(expr):
    return '{{ ' + expr + ' }}'

def condition(expr):
    return {'condition': 'template', 'value_template': template(expr)}

def state(entity, value, attribute=None):
    return {'condition': 'state', 'entity_id': entity, 'state': value,
            **({'attribute': attribute} if attribute else {})}

def call(action, entity=None, data=None, **extra):
    return {'action': action, **({'target': {'entity_id': entity}} if entity else {}),
            **({'data': data} if data is not None else {}), **extra}

def save(expr):
    # JSON true prevents HA's native result parser turning this back into a
    # Python dict before input_text's string validator receives it.
    return call('input_text.set_value', JOB, {'value': template('dict(' + expr + ', v=true) | to_json')})

def phase(value, reason=''):
    return save(f"dict(job, p='{value}', r='{reason}')")

def notify(message):
    return [call('persistent_notification.create', data={
        'title': 'Truma · Timer', 'message': message, 'notification_id': 'truma_timer_auftrag'}),
        {'if': [condition("notify_service != ''")], 'then': [call('{{ notify_service }}', data={
            'title': 'Truma · Timer', 'message': message,
            'data': {'tag': 'truma_timer_auftrag', 'channel': 'Truma Meldungen',
                     'clickAction': '/wohnmobil-klima/klima', 'url': '/wohnmobil-klima/klima'}}, continue_on_error=True)]}]

def fail(reason, message):
    return [phase('error', reason), *notify(message), {'stop': message, 'error': True}]

def require(expr, message):
    return {'if': [{'condition': 'not', 'conditions': [condition(expr)]}],
            'then': [{'stop': message, 'error': True}]}

READY = [state('binary_sensor.truma_inet_verbindung', 'on'),
         state('sensor.truma_inet_timer', 'Aus'),
         state(CLIMATE, ['off', 'heat']), state(WATER, ['Aus', 'Niedrig', 'Hoch', 'Boost']),
         {'condition': 'not', 'conditions': [state('script.truma_heizung_neu_starten', 'on')]}]
ready_expr = ("is_state('binary_sensor.truma_inet_verbindung','on') and "
              "is_state('sensor.truma_inet_timer','Aus') and "
              f"states('{CLIMATE}') in ['off','heat'] and "
              f"states('{WATER}') in ['Aus','Niedrig','Hoch','Boost'] and "
              "not is_state('script.truma_heizung_neu_starten','on')")

def matches(v):
    return (f"is_state('{CLIMATE}', {v}.m) and "
            f"({v}.t is none or is_state_attr('{CLIMATE}','temperature',{v}.t | int)) and "
            f"({v}.m == 'off' or is_state_attr('{CLIMATE}','fan_mode',{v}.f)) and "
            f"is_state('{WATER}',{v}.w)")

def wait(expr, seconds=20):
    return {'wait_template': template(expr), 'timeout': {'seconds': seconds}, 'continue_on_timeout': True}

def step(action, entity, data, matched, prerequisites=None):
    return {'if': READY + (prerequisites or []), 'then': [
        {'if': [{'condition': 'not', 'conditions': [condition(matched)]}],
         'then': [call(action, entity, data, continue_on_error=True)]}, wait(matched)]}

def build():
    submit = [
        require("(expected_job is defined and expected_job == job and job.get('p') in ['armed','waiting','error']) or (expected_job is not defined and job.get('p') not in ['saving','armed','executing','running','restoring','waiting'])",
                'Timer wurde inzwischen geändert oder gestartet. Bitte erneut öffnen; laufende Timer können nicht bearbeitet werden.'),
        require("request_id is defined and request_id is string and request_id | regex_match('^[a-zA-Z0-9-]{8,40}$')",
                'Ungültige Auftragskennung.'),
        require("temperature is defined and temperature | string in ['Aus'] + (range(5,31) | map('string') | list) and fan is defined and fan in ['Aus','Eco','High'] and water is defined and water in ['Aus','Niedrig','Hoch','Boost']",
                'Bitte alle Betriebswerte vollständig ausfüllen.'),
        require("(temperature | string == 'Aus' and fan == 'Aus') or (temperature | string != 'Aus' and fan in ['Eco','High'])",
                'Bei Heizung aus auch Gebläse Aus wählen; sonst Eco oder High.'),
        require("daily is defined and daily is boolean and use_end is defined and use_end is boolean",
                'Wiederholung und Endzeit ausdrücklich auswählen.'),
        require("start_at is defined and start_at is string and start_at | regex_match('^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$')",
                'Beginn fehlt.'),
        {'variables': {'start_dt': "{{ strptime(start_at, '%Y-%m-%dT%H:%M', none) }}"}},
        require("start_dt is not none", 'Ungültiger Beginn.'),
        {'variables': {'start_ts': "{{ as_timestamp(as_datetime(start_dt).replace(tzinfo=now().tzinfo)) | int }}"}},
        require("start_ts > as_timestamp(now()) + 60 and (start_ts | timestamp_custom('%Y-%m-%dT%H:%M', true)) == start_at",
                'Beginn muss mindestens eine Minute in der Zukunft liegen und eine gültige Ortszeit sein.'),
        {'variables': {'end_ts': 0}},
        {'if': [condition('use_end')], 'then': [
            require("end_at is defined and end_at is string and end_at | regex_match('^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$')", 'Ende fehlt.'),
            {'variables': {'end_dt': "{{ strptime(end_at, '%Y-%m-%dT%H:%M', none) }}"}},
            require('end_dt is not none', 'Ungültiges Ende.'),
            {'variables': {'end_ts': "{{ as_timestamp(as_datetime(end_dt).replace(tzinfo=now().tzinfo)) | int }}"}},
            require("end_ts >= start_ts + 300 and (end_ts | timestamp_custom('%Y-%m-%dT%H:%M', true)) == end_at and (not daily or end_ts < start_ts + 86400)",
                    'Ende mindestens fünf Minuten nach Beginn; täglich kürzer als 24 Stunden.')
        ]},
        require("is_state('sensor.truma_inet_timer','Aus')", 'Den Truma-Gerätetimer zuerst ausschalten.'),
        require("is_state('automation.truma_timer_zeitplan','on')", 'Die HA-Timerüberwachung ist nicht aktiv.'),
        {'variables': {'overlaps': OVERLAPS}},
        require("overlap_ids | default([]) | sort == overlaps", 'Überschneidung: Bitte die betroffenen Timer erneut prüfen und ausdrücklich bestätigen.'),
        {'variables': {'job': "{{ dict(id=request_id, p='saving', s=start_ts, e=end_ts, d=daily, t=temperature | string, f=fan, w=water, r='', c=as_timestamp(now()) | int) }}"}},
        save('job'),
        call('input_datetime.set_datetime', WHEN, {'timestamp': '{{ job.s }}'}),
        phase('armed'),
        {'stop': 'Timer in Home Assistant gespeichert. Noch keine Heizbefehle gesendet.'}
    ]

    cancel = [require("expected_job is not defined or expected_job == job", 'Timer wurde inzwischen geändert. Bitte erneut prüfen.'),
              require("job.get('p') not in ['executing','restoring']", 'Übertragung läuft.'),
              require("job.get('p') != 'running' or states('input_text.truma_timer_aktuell') != job.get('id')", 'Aktiver Timer: Vorzustand über Jetzt beenden wiederherstellen.'),
              phase('cancelled'), {'stop': 'Zeitplan entfernt. Betriebswerte unverändert.'}]

    finish = [
        {'if': [condition('job.d')], 'then': [
            {'variables': {
                'next_s': "{% set old = as_local(as_datetime(job.s)) %}{% set dt = today_at(old.strftime('%H:%M')) %}{{ as_timestamp(dt + timedelta(days=1) if dt <= now() else dt) | int }}",
                'next_e': "{% if job.e %}{% set old_s = as_local(as_datetime(job.s)) %}{% set old_e = as_local(as_datetime(job.e)) %}{% set ns = as_local(as_datetime(next_s)) %}{{ as_timestamp(ns.replace(hour=old_e.hour, minute=old_e.minute) + timedelta(days=1 if old_e.date() > old_s.date() else 0)) | int }}{% else %}0{% endif %}"}},
            {'if': [condition("(next_s | timestamp_custom('%H:%M',true)) != (job.s | timestamp_custom('%H:%M',true)) or (job.e and (next_e | timestamp_custom('%H:%M',true)) != (job.e | timestamp_custom('%H:%M',true)))")],
             'then': fail('clock', 'Zeitumstellung: Die nächste Ortszeit existiert nicht. Bitte den täglichen Timer neu planen.')},
            call('input_datetime.set_datetime', WHEN, {'timestamp': '{{ next_s }}'}),
            save("dict(job, p='waiting', s=next_s, e=next_e, r=completion_reason)")
        ], 'else': [save("dict(job, p='done', r=completion_reason, finished=as_timestamp(now()) | int)")]},
        {'stop': 'Alle angeforderten Einstellungen von der Box bestätigt.'}
    ]

    # Every step waits for the preceding state before continuing. Off is sent
    # before restoring a saved target, so a previously off heater stays off.
    mode_match = f"is_state('{CLIMATE}',desired.m)"
    temp_match = f"is_state_attr('{CLIMATE}','temperature',desired.t | int)"
    fan_match = f"is_state_attr('{CLIMATE}','fan_mode',desired.f)"
    water_match = f"is_state('{WATER}',desired.w)"
    attempts = [
        {'variables': {'attempt_started': '{{ as_timestamp(now()) }}'}},
        wait(ready_expr),
        {'if': [condition("desired.m == 'off'")], 'then': [step('climate.set_hvac_mode', CLIMATE, {'hvac_mode': 'off'}, mode_match)]},
        {'if': [condition('desired.t is not none')], 'then': [step('climate.set_temperature', CLIMATE, {'temperature': '{{ desired.t | int }}'}, temp_match,
            [condition("desired.m == 'heat' or is_state('climate.truma_inet_heizung','off')")])]},
        {'if': [condition("desired.m == 'heat'")], 'then': [
            step('climate.set_hvac_mode', CLIMATE, {'hvac_mode': 'heat'}, mode_match, [condition(temp_match)]),
            step('climate.set_fan_mode', CLIMATE, {'fan_mode': '{{ desired.f }}'}, fan_match, [condition(temp_match), condition(mode_match)])]},
        step('select.select_option', WATER, {'option': '{{ desired.w }}'}, water_match),
        wait(ready_expr + ' and ' + matches('desired') + " and as_timestamp(states('sensor.truma_inet_letzte_aktualisierung'), 0) >= attempt_started", 30),
        {'if': [condition('wait.completed')], 'then': [
            {'if': [condition('not restoring and job.e > 0')], 'then': [
                call('input_datetime.set_datetime', WHEN, {'timestamp': '{{ job.e }}'}), phase('running'),
                {'stop': 'Start bestätigt; vorherige Einstellungen sind für das Ende gesichert.'}
            ], 'else': finish}
        ]},
        {'if': [condition('repeat.index < 3')], 'then': [{'delay': {'seconds': 15}}]}
    ]

    tick = [
        {'if': [condition("job.get('p') in ['saving','executing','restoring']")],
         'then': fail('interrupted', 'Timer-Ausführung wurde unterbrochen. Keine automatische Wiederholung; mögliche Teiländerungen bitte prüfen.')},
        {'condition': 'template', 'value_template': template("job.get('p') in ['armed','waiting','running']")},
        {'variables': {'restoring': "{{ job.p == 'running' }}", 'due': "{{ job.e if restoring else job.s }}",
                       'desired': {}, 'previous': {}, 'completion_reason': ''}},
        {'condition': 'template', 'value_template': template("as_timestamp(now()) >= due or (operation == 'finish' and restoring)")},
        {'if': [condition("restoring and states('input_text.truma_timer_aktuell') != job.id")],
         'then': [{'variables': {'completion_reason': 'superseded'}}, *finish]},
        {'if': [condition("not restoring and as_timestamp(now()) - due > 90")],
         'then': fail('missed', 'Timerstart verpasst (Home Assistant war nicht rechtzeitig bereit). Keine verspätete Ausführung; Zeitplan bitte neu setzen.')},
        {'if': [condition("restoring and as_timestamp(now()) - due > 86400")],
         'then': fail('stale', 'Timerende liegt mehr als einen Tag zurück. Vorzustand wird nicht ungeprüft wiederhergestellt.')},
        wait(ready_expr, 30),
        {'if': [{'condition': 'not', 'conditions': READY}],
         'then': fail('unavailable', 'Timer nicht ausgeführt: Verbindung oder Betriebswerte fehlen, Gerätetimer oder Heizungsneustart aktiv.')},
        {'if': [condition('restoring')], 'then': [
            {'variables': {'previous': template(f"states('{PREVIOUS}') | from_json({{}})")}},
            {'if': [condition("previous.get('id') != job.id or previous.get('m') not in ['off','heat']")],
             'then': fail('snapshot', 'Gesicherter Vorzustand fehlt. Keine ungeprüfte Wiederherstellung.')},
            {'variables': {'desired': '{{ previous }}'}}
        ], 'else': [
            {'variables': {'desired': "{{ dict(m='off' if job.t == 'Aus' else 'heat', t=none if job.t == 'Aus' else job.t | int, f=job.f, w=job.w) }}"}},
            {'if': [condition('job.e > 0')], 'then': [
                {'variables': {'capture_started': '{{ as_timestamp(now()) }}'}},
                wait(ready_expr + " and as_timestamp(states('sensor.truma_inet_letzte_aktualisierung'), 0) >= capture_started", 30),
                {'if': [condition("not wait.completed or state_attr('climate.truma_inet_heizung','temperature') is none or state_attr('climate.truma_inet_heizung','fan_mode') not in ['Aus','Eco','High']")],
                 'then': fail('snapshot', 'Vorzustand nicht frisch und vollständig bekannt. Timer wurde nicht gestartet.')},
                call('input_text.set_value', PREVIOUS, {'value': template(f"dict(v=true, id=job.id, m=states('{CLIMATE}'), t=state_attr('{CLIMATE}','temperature'), f=state_attr('{CLIMATE}','fan_mode'), w=states('{WATER}')) | to_json")})
            ]}
        ]},
        save("dict(job, p='restoring' if restoring else 'executing', r='')"),
        # Claim ownership before a possible partial write: an old timer must
        # never undo a newer attempt, including an interrupted/failed one.
        {'if': [condition('not restoring')], 'then': [call('input_text.set_value', OWNER, {'value': '{{ job.id }}'})]},
        {'repeat': {'count': 3, 'sequence': attempts}},
        *fail('confirmation', 'Timer nach drei Versuchen nicht vollständig bestätigt. Es folgen keine weiteren Versuche. Teiländerungen sind möglich; bitte Heizung und Warmwasser prüfen.')
    ]
    script = {'alias': 'Truma Timer verwalten', 'description': 'Persistenter HA-Starttimer. Einmalig oder täglich, optional Vorzustand am Ende wiederherstellen. Drei begrenzte Versuche; kein Nachholen verpasster Starts. Mit KI-Unterstützung entwickelt.',
        'mode': 'single', 'max_exceeded': 'silent', 'trace': {'stored_traces': 20},
        'fields': {name: {'selector': {'text': {}}} for name in ['operation','request_id','start_at','end_at','temperature','fan','water']},
        'variables': {'notify_service': '', 'job_entities': JOBS, 'previous_entities': PREVIOUS_SLOTS, 'when_entities': WHEN_SLOTS},
        'sequence': [require("slot | default(0) | string in ['0','1','2','3','4','5','6','7']", 'Ungültiger Timerplatz.'),
            {'variables': {'slot': '{{ slot | default(0) | int }}', 'job_entity': '{{ job_entities[slot] }}',
                           'previous_entity': '{{ previous_entities[slot] }}', 'when_entity': '{{ when_entities[slot] }}',
                           'job': '{{ states(job_entity) | from_json({}) }}'}},
            {'choose': [{'conditions': [condition("operation == 'submit'")], 'sequence': submit},
                        {'conditions': [condition("operation == 'cancel'")], 'sequence': cancel},
                        {'conditions': [condition("operation in ['tick','finish']")], 'sequence': tick}]}]}
    script['fields'].update({k: {'selector': {'boolean': {}}} for k in ['daily','use_end']})
    script['fields']['slot'] = {'selector': {'number': {'min': 0, 'max': SLOTS-1, 'mode': 'box'}}}
    script['fields']['overlap_ids'] = {'selector': {'object': {}}}
    script['fields']['expected_job'] = {'selector': {'object': {}}}
    def dynamic(value):
        if isinstance(value, str):
            for entity, var in [(JOB, 'job_entity'), (PREVIOUS, 'previous_entity'), (WHEN, 'when_entity')]:
                if value == entity:
                    return '{{ ' + var + ' }}'
                value = value.replace("states('" + entity + "')", 'states(' + var + ')')
            return value
        if isinstance(value, list):
            return [dynamic(x) for x in value]
        if isinstance(value, dict):
            return {k: dynamic(v) for k,v in value.items()}
        return value
    script['sequence'] = dynamic(script['sequence'])
    automation = {'id': 'truma_timer_zeitplan', 'alias': 'Truma Timer Zeitplan',
        'description': 'Start/Ende per Datumshilfe; Wiederanlauf und Minutenprüfung erkennen verpasste oder unterbrochene Aufträge. Keine UI-Abhängigkeit.',
        'mode': 'single', 'max_exceeded': 'silent', 'trace': {'stored_traces': 10},
        'triggers': [{'trigger': 'time', 'at': WHEN_SLOTS}, {'trigger': 'homeassistant', 'event': 'start'},
                     {'trigger': 'event', 'event_type': 'automation_reloaded'}, {'trigger': 'time_pattern', 'minutes': '/1'}],
        'variables': {'job_entities': JOBS},
        'actions': [{'variables': {'due_jobs': """{% set ns = namespace(jobs=[]) %}
{% for ent in job_entities %}{% set j=states(ent)|from_json({}) %}
{% if j.get('p') in ['saving','armed','executing','running','restoring','waiting'] %}
{% set due = j.e if j.p == 'running' else j.s %}
{% if due <= as_timestamp(now()) or j.p in ['saving','executing','restoring'] %}
{% set ns.jobs=ns.jobs+[dict(slot=loop.index0, when=due, priority=0 if j.p=='running' else 1, created=j.get('c',0))] %}
{% endif %}{% endif %}{% endfor %}
{{ ns.jobs | sort(attribute='created') | sort(attribute='priority') | sort(attribute='when') }}"""}},
            {'repeat': {'for_each': '{{ due_jobs }}', 'sequence': [call(SCRIPT, data={'operation': 'tick', 'slot': '{{ repeat.item.slot }}'}, continue_on_error=True)]}}]}
    helpers = []
    for slot in range(SLOTS):
        suffix = '' if slot == 0 else ' ' + str(slot+1)
        helpers += [
            {'helper_type': 'input_text', 'name': 'Truma Timer Auftrag'+suffix, 'config': {'max': 255, 'mode': 'text'}},
            {'helper_type': 'input_text', 'name': 'Truma Timer Vorher'+suffix, 'config': {'max': 255, 'mode': 'text'}},
            {'helper_type': 'input_datetime', 'name': 'Truma Timer Termin'+suffix, 'config': {'has_date': True, 'has_time': True}}
        ]
    helpers += [{'helper_type': 'input_text', 'name': 'Truma Timer Aktuell', 'config': {'max': 64, 'mode': 'text'}}]
    return {'timer-script.json': script, 'timer-automation.json': automation, 'timer-helpers.json': helpers}

if __name__ == '__main__':
    for name, config in build().items():
        (ROOT / 'dashboard' / name).write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
