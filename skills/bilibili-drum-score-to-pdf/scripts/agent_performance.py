"""Durable timing events for serial Agent tasks. No model or host inference."""
from contextlib import contextmanager
from contextvars import ContextVar
import platform
import math
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


class Performance:
    def __init__(self, directory, load, write, embedded=False):
        self.directory, self.load, self.write = directory, load, write
        self.embedded = embedded
        path = directory / ('manifest.json' if embedded else 'performance.json')
        value = load(path) if path.exists() else None
        self.data = value.get('performance_ledger') if embedded and value else value
        now = time.time()
        if self.data is None:
            self.data = dict(schema_version=1, lifecycle_id=uuid.uuid4().hex if not (directory / 'task.json').exists() else None, submitted_at=now if not (directory / 'task.json').exists() else None,
                             last_observed_at=now, first_deliverable_at=None, task_status='waiting',
                             operations=[], stages=[], clock_anomalies=[], source=None, metrics={},
                             environment=dict(python=platform.python_version(), pillow=pillow_version),
                             model=dict(id='unknown', version='unknown'), script_revision='unknown',
                             tool_versions=None, entry='prepare', cache_status='unknown')
        if not isinstance(self.data, dict) or self.data.get('schema_version') != 1 or not all(isinstance(self.data.get(k), list) for k in ('operations','stages','clock_anomalies')):
            raise ValueError('invalid performance ledger')
        def number(value):
            return type(value) in (int,float) and math.isfinite(value)
        if not number(self.data.get('last_observed_at')) or (self.data.get('submitted_at') is not None and not number(self.data['submitted_at'])) or (self.data.get('first_deliverable_at') is not None and not number(self.data['first_deliverable_at'])) or not isinstance(self.data.get('metrics'), dict):
            raise ValueError('invalid performance ledger')
        for event in self.data['operations'] + self.data['stages']:
            if not isinstance(event, dict) or not isinstance(event.get('event_id'), str) or event.get('status') not in ('running','interrupted','complete','waiting','failed','success') or not number(event.get('started_at')) or (event.get('elapsed_seconds') is not None and (not number(event['elapsed_seconds']) or event['elapsed_seconds'] < 0)):
                raise ValueError('invalid performance event')
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
        self.operation.update(ended_at=now, elapsed_seconds=time.monotonic()-self.began, status=result['status'],
                              phase=result.get('phase'), error_code=result.get('error', {}).get('code'))
        delivered = self.operation['operation'] in ('export','replay') and result['status'] == 'success' and result.get('complete')
        if delivered and self.data['first_deliverable_at'] is None:
            self.data['first_deliverable_at'] = now
        if self.data['first_deliverable_at'] is None:
            self.data['task_status'] = result['status']
        elif self.operation['operation'] in ('supplement','submit') and result['status'] == 'waiting':
            self.data['task_status'] = 'waiting'
        elif delivered:
            self.data['task_status'] = 'success'
        if self.operation['operation'] in ('prepare','supplement','export','replay'):
            self.operation['metrics'] = result.get('metrics')
        if result.get('script_revision'):
            self.data['script_revision'] = result['script_revision']
        self.save()

    def metadata(self, observation, state):
        self.data.update(task_id=state['task_id'], source=observation['source'], metrics=observation['metrics'])
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
        return {k: v for k,v in self.data.items() if k != 'last_observed_at'} | dict(
            wall_elapsed_seconds=None if anomaly else elapsed,
            wall_clock_valid=not anomaly, observed_at=now,
            model_tokens=None, model_elapsed_seconds=None, host_tool_calls=None,
            actual_presented_images=None, active_elapsed_seconds=None, model_queue_seconds=None,
            user_pause_seconds=None, missing_measurements=['host/model usage and presentation events unavailable',
                'unobserved waiting cannot be split into review, queue or user pause'],
            script_operation_count=len(self.data['operations']),
            native_seek_attempts=sum(e['name'] == 'native_decode' for e in self.data['stages']),
            source_redecode_attempts=sum(e['name'] == 'source_redecode' for e in self.data['stages']),
            full_frame_analysis_attempts=sum(e['name'] == 'native_analysis' for e in self.data['stages']),
            generated_images=self.data['metrics'].get('native_images',0)+self.data['metrics'].get('detail_images',0)+self.data['metrics'].get('comparison_images',0))
