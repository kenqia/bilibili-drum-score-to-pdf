"""Nearest-rank delivery statistics with all submitted outcomes retained."""
import math
import re
from host_accounting import identifier, number, require
from agent_delivery import current_delivery


def aggregate(packet):
    require(isinstance(packet,dict) and set(packet)=={'schema_version','runs'} and type(packet['schema_version']) is int and packet['schema_version']==1)
    require(isinstance(packet['runs'],list) and 0<len(packet['runs'])<=10000)
    identities, lifecycles, groups, hashes = {}, set(), {}, {}
    fields={'run_id','sample_id','code_version','entry','mode','input_sha256','environment_id','model_id','model_version','measurement_source','timeout_seconds','performance'}
    statuses=('success','waiting','failed','cancelled','timeout')
    for run in packet['runs']:
        require(isinstance(run,dict) and set(run)==fields)
        for key in ('run_id','sample_id','code_version','environment_id','model_id','model_version'):
            identifier(run[key])
        if run['run_id'] in identities:
            require(identities[run['run_id']]==run)
            continue
        identities[run['run_id']]=run
        require(run['measurement_source'] in ('host','codex_desktop_jsonl','controlled_fixture','unknown'))
        require(run['entry'] in ('local','url') and run['mode'] in ('review','review_only','replay'))
        require(isinstance(run['input_sha256'],str) and re.fullmatch('[0-9a-f]{64}',run['input_sha256']))
        number(run['timeout_seconds']);require(run['timeout_seconds']>0)
        sample=run['sample_id']
        require(sample not in hashes or hashes[sample]==run['input_sha256']);hashes[sample]=run['input_sha256']
        performance=run['performance']
        require(isinstance(performance,dict) and performance.get('task_status') in statuses)
        identifier(performance.get('lifecycle_id'))
        require(performance['lifecycle_id'] not in lifecycles)
        lifecycles.add(performance['lifecycle_id'])
        elapsed=performance.get('wall_elapsed_seconds')
        if elapsed is not None:number(elapsed)
        if performance['task_status']=='success':
            require(performance.get('delivery_confirmed') is True and performance.get('delivered_at') is not None)
            number(performance['delivered_at'])
        tokens=performance.get('model_tokens')
        if tokens is not None:
            require(isinstance(tokens,dict) and type(tokens.get('total_tokens')) is int and tokens['total_tokens']>=0)
            require(type(tokens.get('input_tokens')) is int and type(tokens.get('output_tokens')) is int and tokens['input_tokens']>=0 and tokens['output_tokens']>=0)
            require(tokens['total_tokens']==tokens['input_tokens']+tokens['output_tokens'])
        keys=('sample_id','code_version','entry','mode','input_sha256','environment_id','model_id','model_version','measurement_source','timeout_seconds')
        key=tuple(run[k] for k in keys)
        groups.setdefault(key,dict(zip(keys,key))|{'runs':[]})['runs'].append(performance)
    result=[]
    for group in groups.values():
        runs=group.pop('runs');n=len(runs)
        successful=sorted(r['wall_elapsed_seconds'] for r in runs if r['task_status']=='success' and r.get('wall_clock_valid') is True and r.get('wall_elapsed_seconds') is not None)
        def quantile(q):
            return successful[math.ceil(q*len(successful))-1] if successful else None
        complete=[r['model_tokens']['total_tokens'] for r in runs if r.get('model_tokens') is not None]
        observed=[]
        for run in runs:
            value=run.get('host_usage',{}).get('observed_actual_tokens',{}).get('total_tokens') if isinstance(run.get('host_usage'),dict) else None
            if value is None and run.get('model_tokens') is not None:value=run['model_tokens']['total_tokens']
            if value is not None:
                require(type(value) is int and value>=0);observed.append(value)
        counts={status:sum(r['task_status']==status for r in runs) for status in statuses}
        result.append(group|dict(submitted_count=n,status_counts=counts,status_rates={k:v/n for k,v in counts.items()},
            delivery_seconds=dict(sample_count=len(successful),p50=quantile(.5),p90=quantile(.9),algorithm='nearest-rank'),
            known_elapsed_seconds_by_status={status:[r.get('wall_elapsed_seconds') for r in runs if r['task_status']==status] for status in statuses},
            complete_token_run_count=len(complete),actual_total_tokens=sum(complete) if len(complete)==n else None,
            observed_token_run_count=len(observed),known_observed_total_tokens=sum(observed) if observed else None,
            small_sample_limit=len(successful)<10,
            real_baseline_eligible=group['measurement_source'] in ('host','codex_desktop_jsonl') and group['mode']=='review' and len(complete)==n and all(
                r.get('wall_clock_valid') is True and r.get('wall_elapsed_seconds') is not None and
                current_delivery(r) is not None and current_delivery(r)['review']['reviewer']['kind'] in ('agent','human') and
                isinstance(r.get('host_usage'),dict) and r['host_usage'].get('token_complete') is True and r['host_usage'].get('declared_presented_images_match') is not False and
                r['host_usage'].get('source',{}).get('kind')==group['measurement_source'] and
                all(r['host_usage'].get('coverage',{}).get(k) is True for k in ('lifecycle_complete','model_calls_complete','tools_complete','images_complete'))
                for r in runs)))
    return dict(status='success',groups=result)
