"""Durable timing events for serial Agent tasks. No model or host inference."""
from contextlib import contextmanager
from contextvars import ContextVar
import platform
import hashlib
from pathlib import Path
import math
import re
from video_seek import ConversionError
import time
import uuid
from PIL import __version__ as pillow_version

ACTIVE = ContextVar('performance', default=None)


@contextmanager
def stage(name):
    recorder = ACTIVE.get()
    if recorder is None:
        yield
        return
    event = dict(event_id=uuid.uuid4().hex, operation_id=recorder.operation['event_id'],
                 name=name, source='script_monotonic', started_at=time.time(),
                 offset_seconds=time.monotonic()-recorder.began, elapsed_seconds=None, status='running')
    recorder.data['stages'].append(event)
    recorder.save()
    began = time.monotonic()
    try:
        yield
    except BaseException:
        event['status'] = 'failed'
        raise
    else:
        event['status'] = 'complete'
    finally:
        event.update(elapsed_seconds=time.monotonic()-began, ended_at=time.time())
        recorder.save()


def validate_events(data, number):
    def require(condition):
        if not condition:
            raise ValueError('invalid performance event')
    operations = set()
    ids = set()
    for event in data['operations']:
        required = {'event_id','operation','started_at','elapsed_seconds','ended_at','status'}
        optional = {'phase','error_code','metrics','state_changed'}
        require(isinstance(event, dict) and required <= set(event) <= required | optional)
        require(event['operation'] in ('prepare','resume','submit','supplement','export','replay','confirm-delivery'))
        require(event['status'] in ('running','interrupted','waiting','failed','success'))
        require(number(event['started_at']) and (event['ended_at'] is None or number(event['ended_at'])))
        require(event['elapsed_seconds'] is None or number(event['elapsed_seconds']) and event['elapsed_seconds'] >= 0)
        require(isinstance(event['event_id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', event['event_id'])) and event['event_id'] not in ids)
        require('metrics' not in event or event['metrics'] is None or isinstance(event['metrics'], dict))
        require('state_changed' not in event or type(event['state_changed']) is bool)
        require(all(event.get(k) is None or isinstance(event[k], str) for k in ('phase','error_code')))
        operations.add(event['event_id'])
        ids.add(event['event_id'])
    for event in data['stages']:
        common = {'event_id','name','source','started_at','elapsed_seconds','status'}
        require(isinstance(event, dict) and common <= set(event))
        require(isinstance(event['event_id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', event['event_id'])) and event['event_id'] not in ids)
        require(number(event['started_at']) and (event['elapsed_seconds'] is None or number(event['elapsed_seconds']) and event['elapsed_seconds'] >= 0))
        if event['source'] == 'script_monotonic':
            required = common | {'operation_id','offset_seconds'}
            require(required <= set(event) <= required | {'ended_at'})
            require(event['operation_id'] in operations and number(event['offset_seconds']) and event['offset_seconds'] >= 0)
            require(event['name'] in ('source_verification','navigation','anonymous_acquisition','native_decode','native_analysis',
                                    'image_generation','decision_validation','source_redecode','pdf_export','delivery_publication'))
            require(event['status'] in ('running','interrupted','complete','failed'))
        else:
            require(set(event) == common | {'ended_at','source_id','measurement'})
            require(event['source'] in ('host','controlled_fixture') and event['measurement'] == 'caller_supplied_monotonic')
            require(isinstance(event['source_id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', event['source_id'])))
            require(event['name'] in ('agent_review','model_queue','user_pause','decision_building') and event['status'] in ('complete','failed','waiting'))
        require('ended_at' not in event or number(event['ended_at']))
        require(event['status'] in ('running','interrupted') or ('ended_at' in event and event['elapsed_seconds'] is not None))
        ids.add(event['event_id'])


class Performance:
    def __init__(self, directory, load, write, embedded=False):
        self.directory, self.load, self.write = directory, load, write
        self.embedded = embedded
        path = directory / ('manifest.json' if embedded else 'performance.json')
        value = load(path) if path.exists() else None
        self.data = value.get('performance_ledger') if embedded and value else value
        now = time.time()
        preexisting = value is not None or (directory / 'task.json').exists()
        if self.data is None:
            self.data = dict(schema_version=1, lifecycle_id=uuid.uuid4().hex if not preexisting else None, submitted_at=now if not preexisting else None,
                             last_observed_at=now, first_deliverable_at=None, task_status='waiting',
                             operations=[], stages=[], clock_anomalies=[], source=None, metrics={},
                             environment=dict(python=platform.python_version(), pillow=pillow_version),
                             script_sha256=hashlib.sha256(b''.join(p.name.encode()+b'\0'+p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest(),
                             requirements_sha256=hashlib.sha256(Path(__file__).with_name('requirements.txt').read_bytes()).hexdigest(),
                             model=dict(id='unknown', version='unknown'), script_revision='unknown',
                             tool_versions=None, entry='prepare', cache_status='unknown')
        fields = {'schema_version','lifecycle_id','submitted_at','last_observed_at','first_deliverable_at','task_status',
                  'operations','stages','clock_anomalies','source','metrics','environment','script_sha256','requirements_sha256',
                  'model','script_revision','tool_versions','entry','cache_status','state_revision','task_id','sampling_usage'}
        if not isinstance(self.data, dict) or set(self.data)-fields or type(self.data.get('schema_version')) is not int or self.data.get('schema_version') != 1 or self.data.get('task_status') not in ('waiting','failed','success') or not all(isinstance(self.data.get(k), list) for k in ('operations','stages','clock_anomalies')):
            raise ValueError('invalid performance ledger')
        def number(value):
            try:
                return type(value) in (int,float) and math.isfinite(value)
            except OverflowError:
                return False
        if not number(self.data.get('last_observed_at')) or (self.data.get('submitted_at') is not None and not number(self.data['submitted_at'])) or (self.data.get('first_deliverable_at') is not None and not number(self.data['first_deliverable_at'])) or not isinstance(self.data.get('metrics'), dict):
            raise ValueError('invalid performance ledger')
        validate_events(self.data, number)
        self.operation = None
        self.began = None
        self.observe(now)

    def observe(self, now):
        if now < self.data['last_observed_at']:
            self.data['clock_anomalies'].append(dict(kind='wall_clock_regression', previous=self.data['last_observed_at'], current=now))
        self.data['last_observed_at'] = max(now, self.data['last_observed_at'])

    def save(self):
        if self.embedded:
            self.write(self.directory / 'manifest.json', dict(schema_version=1, phase='acquisition', status='failed', complete=False,
                       error=dict(code='interrupted', message='匿名获取未完成，可在此目录重试。'), rows=[], issues=[], performance_ledger=self.data))
        else:
            self.write(self.directory / 'performance.json', self.data)

    def start(self, operation):
        # A persisted start with no end belongs to the previous interrupted process.
        for event in self.data['operations'] + self.data['stages']:
            if event['status'] == 'running':
                event['status'] = 'interrupted'
        self.began = time.monotonic()
        self.operation = dict(event_id=uuid.uuid4().hex, operation=operation, started_at=time.time(),
                              elapsed_seconds=None, ended_at=None, status='running')
        self.data['operations'].append(self.operation)
        self.save()

    def finish(self, result):
        now = time.time()
        self.observe(now)
        elapsed = time.monotonic()-self.began
        if abs((now-self.operation['started_at'])-elapsed) > 1.0:
            self.data['clock_anomalies'].append(dict(kind='wall_clock_discontinuity', operation_id=self.operation['event_id'],
                                                   wall_seconds=now-self.operation['started_at'], monotonic_seconds=elapsed))
        self.operation.update(ended_at=now, elapsed_seconds=elapsed, status=result['status'],
                              phase=result.get('phase'), error_code=result.get('error', {}).get('code'))
        delivered = self.operation['operation'] in ('export','replay') and result['status'] == 'success' and result.get('complete')
        if delivered and self.data['first_deliverable_at'] is None:
            self.data['first_deliverable_at'] = now
        if self.data['first_deliverable_at'] is None:
            self.data['task_status'] = result['status']
        elif self.operation['operation'] in ('supplement','submit') and self.operation.get('state_changed'):
            self.data['task_status'] = 'waiting'
        elif delivered:
            self.data['task_status'] = 'success'
        if self.operation['operation'] in ('prepare','supplement','export','replay'):
            self.operation['metrics'] = result.get('metrics')
        if result.get('script_revision'):
            self.data['script_revision'] = result['script_revision']
        self.save()

    def import_events(self, path):
        try:
            packet = self.load(path)
            if not isinstance(packet, dict) or set(packet) != {'schema_version','lifecycle_id','source','events'} or type(packet['schema_version']) is not int or packet['schema_version'] != 1 or self.data['lifecycle_id'] is None or packet['lifecycle_id'] != self.data['lifecycle_id']:
                raise ValueError
            source = packet['source']
            if not isinstance(source, dict) or set(source) != {'kind','id'} or source['kind'] not in ('host','controlled_fixture') or not isinstance(source['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', source['id']):
                raise ValueError
            if not isinstance(packet['events'], list) or len(packet['events']) > 1000:
                raise ValueError
            existing = {e['event_id']: e for e in self.data['stages'] + self.data['operations']}
            additions = []
            for event in packet['events']:
                if not isinstance(event, dict) or set(event) != {'event_id','name','started_at','ended_at','elapsed_seconds','status'} or not isinstance(event['event_id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', event['event_id']) or event['name'] not in ('agent_review','model_queue','user_pause','decision_building') or event['status'] not in ('complete','failed','waiting'):
                    raise ValueError
                if any(type(event[k]) not in (int,float) or not math.isfinite(event[k]) for k in ('started_at','ended_at','elapsed_seconds')) or event['elapsed_seconds'] < 0 or event['ended_at'] < event['started_at'] or event['ended_at'] > time.time():
                    raise ValueError
                imported = event | dict(source=source['kind'], source_id=source['id'], measurement='caller_supplied_monotonic')
                if event['event_id'] in existing:
                    if existing[event['event_id']] != imported:
                        raise ValueError
                else:
                    additions.append(imported)
                    existing[event['event_id']] = imported
            self.data['stages'].extend(additions)
            self.save()
        except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
            raise ConversionError('invalid_performance', '性能事件字段、绑定或已有事件内容非法。') from None

    def metadata(self, observation, state):
        revision = dict(observation_sha256=state['observation_sha256'], phase=state['phase'], complete=state['complete'],
                        decision_sha256=state.get('decision_history', [{}])[-1].get('sha256') if state.get('decision_history') else None)
        if self.operation:
            self.operation['state_changed'] = self.data.get('state_revision') != revision
        self.data.update(task_id=state['task_id'], source=observation['source'], metrics=observation['metrics'], state_revision=revision)
        history = state.get('decision_history', [])
        if history:
            value = self.load(self.directory / history[-1]['path'])
            self.data['model'] = value.get('decision', value)['model']
        self.data['sampling_usage'] = state.get('sampling_usage', observation['sampling']['used'])

    def report(self):
        now = time.time()
        end = self.data['first_deliverable_at'] or now
        elapsed = None if self.data['submitted_at'] is None else end-self.data['submitted_at']
        anomaly = now < self.data['last_observed_at'] or bool(self.data['clock_anomalies']) or (elapsed is not None and elapsed < 0)
        from host_accounting import task_summary
        host = task_summary(self.directory, self.data, self.load)
        return {k: v for k,v in self.data.items() if k != 'last_observed_at'} | dict(
            wall_elapsed_seconds=None if anomaly else elapsed,
            wall_clock_valid=not anomaly, observed_at=now,
            host_usage=host, model_tokens=host['model_tokens'] if host else None, model_elapsed_seconds=None, host_tool_calls=host['host_tool_calls'] if host else None,
            actual_presented_images=host['actual_presented_images'] if host else None, active_elapsed_seconds=None, model_queue_seconds=None,
            user_pause_seconds=None, missing_measurements=(['lifecycle submission time unavailable for pre-existing task'] if self.data['submitted_at'] is None else []) + ((host['missing_measurements'] if host else ['host/model usage and presentation events unavailable']) + [
                'unobserved waiting cannot be split into review, queue or user pause']),
            script_operation_count=len(self.data['operations']),
            native_seek_attempts=sum(e['name'] == 'native_decode' for e in self.data['stages']),
            source_redecode_attempts=sum(e['name'] == 'source_redecode' for e in self.data['stages']),
            full_frame_analysis_attempts=sum(e['name'] == 'native_analysis' for e in self.data['stages']),
            generated_images=(self.data['metrics'].get('native_images',0)+self.data['metrics'].get('detail_images',0)+self.data['metrics'].get('comparison_images',0)) if self.data['metrics'] else None)
