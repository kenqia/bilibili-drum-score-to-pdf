"""Program geometry and temporal evidence. These checks are not Agent vision."""
import hashlib
import json
import math
import time
from pathlib import Path
import uuid
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw
import reconstruction as geometry
import score_task as state
import score_geometry
import score_continuity as continuity
from score_geometry import detect  # Existing geometry entry.

from video_seek import VideoReader, ConversionError

PROGRAM_CHECK_VERSION = "geometry-temporal/10"
SCAN_POLICY_VERSION = "native-visible-ink/3"
MAX_EVENTS = 8192
MAX_NATIVE_BYTES = 1024 * 1024 * 1024
SIGNATURE_PIXELS = 512 * 1024 * 1024


def _fingerprint(record):
    material = {'source': record['source']['sha256'], 'regions': record['regions'],
        'rough_chunks': record.get('rough_chunks'), 'review': record.get('source_review'),
        'checks': record.get('program_checks'),
        'overview_candidates': [c['sha256'] for c in record.get('overview',{}).get('candidates',[])]}
    if record.get('agent_review_contract'):
        material['agent_review_contract'] = record['agent_review_contract']
        material['source_issue_history'] = record.get('source_issue_history', [])
        if 'legacy_source_approval' in record:
            material['legacy_source_approval'] = record['legacy_source_approval']
    if 'row_manifest' in record:
        material['row_manifest'] = record['row_manifest']
    if 'continuity_reviews' in record:
        material['continuity_reviews'] = record['continuity_reviews']
    if 'row_anchor_reviews' in record:
        material['row_anchor_reviews'] = record['row_anchor_reviews']
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def freeze(record, producer):
    material_digest=hashlib.sha256(json.dumps(record['regions'],sort_keys=True).encode()).hexdigest()
    previous=record.get('freeze',{})
    identifier=previous['id'] if previous.get('material_digest')==material_digest else uuid.uuid4().hex
    record['freeze'] = {'id': identifier, 'producer': producer, 'material_digest':material_digest,
        'fingerprint': _fingerprint(record), 'source_sha256': record['source']['sha256']}
    if producer=='program':
        record['freeze']['policy_version']=PROGRAM_CHECK_VERSION
    return record['freeze']


def require_frozen(record):
    frozen = record.get('freeze')
    if frozen and frozen.get('producer') == 'program' and record.get('overview', {}).get('mode') == 'sparse':
        navigation = record.get('navigation', {})
        if (navigation.get('policy_version') != continuity.NAVIGATION_POLICY or navigation.get('status') != 'observed' or
                not all(navigation.get('endpoints', {}).get(name) for name in ('first', 'last')) or
                record.get('row_manifest', {}).get('continuity_complete') is not True):
            raise state.ReconstructionError('稀疏导航或谱行接续证据尚未完成。')
    if frozen and frozen.get('producer')=='program' and (
            frozen.get('policy_version')!=PROGRAM_CHECK_VERSION or
            record.get('program_checks',{}).get('policy_version')!=PROGRAM_CHECK_VERSION or
            record.get('overview',{}).get('scan',{}).get('policy_version')!=SCAN_POLICY_VERSION):
        raise state.ReconstructionError('程序检查规则已改变；请重新运行 auto-freeze。')
    if (not frozen or frozen['fingerprint'] != _fingerprint(record) or
            record.get('source_review', {}).get('complete') is not True or
            record['source_review'].get('unresolved')):
        raise state.ReconstructionError('材料尚未冻结或已改变；请重新检查。', code='source_review_required', action='stage')

    if frozen.get('producer') == 'agent' and record.get('agent_review_contract'):
        from agent_source_review import validate
        validate(record, record['regions'], record['source_review'], same=True)


def _panels(task, candidates):
    refs = []
    for offset in range(0, len(candidates), 24):
        batch = candidates[offset:offset+24]
        panel = Image.new('RGB', (1280, math.ceil(len(batch)/4)*270), 'white')
        draw = ImageDraw.Draw(panel)
        for index, shot in enumerate(batch):
            with Image.open(state.artifact(task, shot)) as original:
                thumb = original.copy()
                thumb.thumbnail((312,240))
                px,py = (index%4)*320, (index//4)*270
                panel.paste(thumb,(px,py))
                draw.text((px,py+242), f"{shot['id']} req={shot['requested_seconds']:.3f}",fill='black')
                draw.text((px,py+255), f"PTS={shot['pts']} {shot['time_base']}",fill='black')
        path = state.write_path(task, Path('navigation')/('overview-'+uuid.uuid4().hex+'.png'))
        path.parent.mkdir(exist_ok=True)
        panel.save(path)
        panel.close()
        refs.append({'path':str(path.relative_to(task)), 'sha256':state.digest(path)})
    return refs


def overview(task, intervals=None, reason='full continuous source scan', *, force=False,
             max_new_candidates=128):
    if type(max_new_candidates) is not int or not 1 <= max_new_candidates <= MAX_EVENTS:
        raise state.ReconstructionError('单次候选预算必须为 1–8192 的整数。')
    started = time.monotonic()
    record = state.load(task)
    duration = record['source']['duration']
    intervals = [[0, duration]] if intervals is None else intervals
    if not isinstance(intervals,list) or not intervals or not isinstance(reason,str) or not reason.strip():
        raise state.ReconstructionError('补采区间和原因必填。')
    for interval in intervals:
        if (not isinstance(interval,list) or len(interval)!=2 or
            any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) for t in interval) or
            not 0 <= interval[0] < interval[1] <= duration):
            raise state.ReconstructionError('补采区间越界。')
    survey = record.setdefault('overview', {'candidates':[], 'scan':{'complete':False,
        'frames_observed':0, 'completed_intervals':[], 'cursor':0}, 'panels':[], 'resamples':[]})
    retained_bytes=sum((Path(task)/c['path']).stat().st_size for c in survey['candidates'])
    scan = survey['scan']
    if scan.get('policy_version')!=SCAN_POLICY_VERSION:
        survey.setdefault('scan_history',[]).append(dict(scan))
        scan.update(complete=False,frames_observed=0,completed_intervals=[],cursor=0,segments=[],policy_version=SCAN_POLICY_VERSION)
        survey['candidates']=[]
        retained_bytes = 0
        scan.pop('progress', None)
        record.pop('freeze',None)
    # Recover previously published zero-frame success claims through the public
    # operation. Only actual decoded segments may contribute coverage.
    invalid = [s['requested_interval'] for s in scan.get('segments',[])
        if s.get('complete') and (not s.get('frames') or not s.get('last'))]
    if invalid:
        scan['completed_intervals'] = [span for span in scan['completed_intervals'] if span not in invalid]
        scan['complete'] = False
        record.pop('freeze',None)
        scan.setdefault('recovered_invalid_segments',[]).extend(invalid)
        for segment in scan['segments']:
            if segment['requested_interval'] in invalid:
                segment['complete'] = False
    merged=[]
    for low,high in sorted(scan['completed_intervals']):
        if merged and low<=merged[-1][1]+1e-6:
            merged[-1][1]=max(merged[-1][1],high)
        else:
            merged.append([low,high])
    scan['completed_intervals']=merged
    request = {'intervals':intervals, 'reason':reason, 'new_candidates':[], 'unresolved':[]}
    survey['resamples'].append(request)
    prior_progress = scan.get('progress', {})
    checkpoint_writes = prior_progress.get('checkpoint_writes', 0)
    last_checkpoint = started
    timings = dict(prior_progress.get('timings', {}))
    for name in ('change_detection_seconds', 'image_save_seconds', 'record_save_seconds'):
        timings.setdefault(name, 0.0)

    def checkpoint():
        nonlocal checkpoint_writes, last_checkpoint
        now = time.monotonic()
        checkpoint_writes += 1
        scan['progress'] = {
            'frames_observed': scan['frames_observed'],
            'candidates_retained': len(survey['candidates']),
            'candidate_bytes': retained_bytes,
            'candidate_ratio': len(survey['candidates']) / max(1, scan['frames_observed']),
            'wall_seconds': prior_progress.get('wall_seconds', 0) + now - started,
            'checkpoint_writes': checkpoint_writes,
            'cursor_seconds': scan.get('cursor', 0),
            'source_seconds': duration,
            'timings': timings,
        }
        before_save = time.monotonic()
        state.save(task, record)
        timings['record_save_seconds'] += time.monotonic() - before_save
        last_checkpoint = time.monotonic()

    previous = None
    if survey['candidates']:
        with Image.open(state.artifact(task, survey['candidates'][-1])) as image:
            previous = score_geometry.signature(image)
    reader = VideoReader(record['source']['path'], record['source'], record['metrics'])
    stream = None
    observed_start = observed_end = None
    try:
        work=[]
        for low,high in intervals:
            pending=[[low,high]]
            if not force:
                for a,b in scan['completed_intervals']:
                    remaining=[]
                    for left,right in pending:
                        if b<=left or a>=right:
                            remaining.append([left,right])
                        else:
                            if left<a:
                                remaining.append([left,a])
                            if b<right:
                                remaining.append([b,right])
                    pending=remaining
            for low,high in pending:
                while low<high:
                    end=min(high,low+15)
                    work.append([low,end])
                    low=end
        for start,end in work:
            if not force and any(a<=start and b>=end for a,b in scan['completed_intervals']):
                continue
            if start >= end:
                continue
            observed_start, observed_end = start, start
            segment={'requested_interval':[start,end],'first':None,'last':None,'frames':0,'complete':False}
            scan.setdefault('segments',[]).append(segment)
            stream = reader.scan(start,end)
            for pts,image in stream:
                try:
                    observed_end = pts['timestamp']
                    if segment['first'] is None:
                        segment['first']=pts
                    segment['last']=pts
                    segment['frames']+=1
                    before_change = time.monotonic()
                    mask = score_geometry.signature(image)
                    changed = previous is None or not score_geometry.same_ink(previous,mask)
                    timings['change_detection_seconds'] += time.monotonic() - before_change
                    scan['frames_observed'] += 1
                    scan['cursor'] = max(scan.get('cursor',0), pts['timestamp'])
                    if changed and not any(c['pts']==pts['pts'] and c['time_base']==pts['time_base'] for c in survey['candidates']):
                        if len(survey['candidates']) >= MAX_EVENTS:
                            raise state.ReconstructionError('变化候选达到资源上限，保留进度。')
                        identifier = f'capture-{len(record["captures"])+1:04d}'
                        path = state.write_path(task,Path('captures')/(identifier+'-'+uuid.uuid4().hex+'.png'))
                        path.parent.mkdir(exist_ok=True)
                        before_image = time.monotonic()
                        image.save(path)
                        timings['image_save_seconds'] += time.monotonic() - before_image
                        retained_bytes+=path.stat().st_size
                        if retained_bytes>MAX_NATIVE_BYTES:
                            raise state.ReconstructionError('原生证据达到资源字节上限，保留进度。')
                        shot={'id':identifier,'path':str(path.relative_to(task)), 'sha256':state.digest(path),
                            'source_sha256':record['source']['sha256'], 'requested_seconds':pts['timestamp'],
                            'requested_aliases':[pts['timestamp']], 'width':image.width,'height':image.height, **pts}
                        record['captures'].append(shot)
                        survey['candidates'].append(shot)
                        request['new_candidates'].append(identifier)
                        previous=mask
                        if len(request['new_candidates']) >= max_new_candidates:
                            raise ConversionError('candidate_budget', '单次候选预算已用尽，保留已观察前缀。')
                    # Checkpoint at most once per second; finally preserves SIGTERM progress.
                    if time.monotonic() - last_checkpoint >= 1:
                        checkpoint()
                finally:
                    image.close()
            segment['complete']=True
            scan['completed_intervals'].append([start,end])
        spans=sorted(scan['completed_intervals'])
        covered=0
        for a,b in spans:
            if a <= covered+1e-6:
                covered=max(covered,b)
        scan['complete']=covered>=duration
        scan['method']='continuous_decoded_frames_native_ink_change'
    except (ConversionError,state.ReconstructionError) as error:
        request['unresolved'].append({'code':getattr(error,'code','resource_limit'), 'resume':'overview'})
        scan['complete']=False
    finally:
        if stream is not None:
            stream.close()
        if observed_start is not None and observed_end > observed_start and not scan['complete']:
            scan['completed_intervals'].append([observed_start, observed_end])
        reader.close()
        record['metrics']['stream_frames_decoded'] = scan['frames_observed']
        record['metrics']['stream_candidates_retained'] = len(survey['candidates'])
        record['metrics']['stream_native_bytes'] = sum((Path(task)/c['path']).stat().st_size for c in survey['candidates'])
        record['metrics']['native_retained']=len(record['captures'])
        survey['candidates'].sort(key=lambda c:c['timestamp'])
        survey['panels']=_panels(task,survey['candidates'])
        checkpoint()
    return survey


def scan_status(task):
    """Read the last metadata checkpoint; this does not verify source artifacts."""
    path = state.write_path(task, 'record.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schema') != 'score-reconstruction/1':
        raise state.ReconstructionError('不是当前重构任务。')
    scan = record.get('overview', {}).get('scan', {})
    return {'metadata_only': True, 'complete': scan.get('complete', False),
            'progress': scan.get('progress', {}),
            'unresolved': (record.get('overview', {}).get('resamples') or [{}])[-1].get('unresolved', [])}


def resample(task, intervals, reason):
    return overview(task,intervals,reason,force=True)


def _apply_revisions(task, record, shot, regions):
    risks=[]
    if not any(r['capture']==shot['id'] for r in record.get('crop_revisions',[])):
        return risks
    with Image.open(state.artifact(task,shot)) as image:
        mask=geometry.ink_mask(image)
        for revision in record.get('crop_revisions',[]):
            if revision['capture']!=shot['id']:
                continue
            for region in regions:
                if region['bbox']!=revision['original_bbox']:
                    continue
                old=region['bbox']
                box=revision['bbox']
                yy,xx=np.where(mask[old[1]:old[3],old[0]:old[2]]>0)
                if len(xx) and not (box[0]<=old[0]+xx.min() and box[2]>old[0]+xx.max() and
                    box[1]<=old[1]+yy.min() and box[3]>old[1]+yy.max()):
                    risks.append({'code':'crop_cuts_visible_ink','bbox':box})
                if region['kind']=='system':
                    region['staff_top']+=old[1]-box[1]
                region['bbox']=box
    return risks


def _partial_recovered(task, partial, atlas, captures, observations, neighbours, native, record=None):
    shot=captures[partial['capture']]
    lines=partial.get('lines',[])
    if not lines or not partial.get('spacing'):
        return False
    spacing=partial['spacing']
    paper=partial['paper_bbox']
    index=next(i for i,item in enumerate(observations) if item[1]['id']==shot['id'])
    own=observations[index]
    anchors={}
    for neighbour in neighbours:
        mapping=score_geometry.spatial_continuation(own[3],neighbour[3],own[6],neighbour[6],native)
        if record is not None:
            comparison = continuity.compare(task, record, shot, neighbour[1])
            if comparison.get('reason') == 'printed_bar_overlap':
                mapping = comparison['matches']
        shifts=[neighbour[3][j]['bbox'][1]+neighbour[3][j]['staff_top']-
            own[3][i]['bbox'][1]-own[3][i]['staff_top'] for j,i in mapping.items()]
        if shifts:
            anchors[neighbour[1]['id']]=round(float(np.median(shifts)))

    with Image.open(state.artifact(task,shot)) as image:
        original=geometry.ink_mask(image)
    for row,full in atlas:
        if row['capture'] not in anchors:
            continue
        shift=anchors[row['capture']]
        if any(min(abs(line+shift-observed) for observed in row['evidence']['five_lines'])>1.5 for line in lines):
            continue
        if abs(row['staff_spacing']-spacing)>1:
            continue
        left=max(paper[0],row['bbox'][0])
        right=min(paper[2],row['bbox'][2])
        low=max(paper[1],round(lines[0]-3*spacing))
        high=min(paper[3],round(lines[-1]+spacing))
        if high<=low or right<=left:
            continue
        patch=original[low:high,left:right]
        # Pure staff fragments cannot identify a source position or prove the
        # hidden music matches an unrelated earlier full row.
        staff=cv2.morphologyEx(patch,cv2.MORPH_OPEN,
            np.ones((1,max(24,patch.shape[1]//8)),np.uint8))
        if np.count_nonzero(cv2.subtract(patch,staff))<max(12,spacing):
            continue
        target_native=native(row['capture'])
        # Compare each observed pixel against full native neighbours, rather
        # than dilating a truncated patch (which loses border raster evidence).
        target_dilated=cv2.dilate(target_native,np.ones((3,3),np.uint8))
        for actual in (shift,shift-1,shift+1):
            origin=round(low+actual)
            if origin<row['bbox'][1] or origin+patch.shape[0]>row['bbox'][3]:
                continue
            target=target_dilated[origin:origin+patch.shape[0],left:right]
            if patch.shape==target.shape and not np.any((patch>0)&(target==0)):
                return True
    return False


def _compatible_repair(task, old_rows, new_rows, risk_by_position, captures):
    shifts=[new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top']
        for old,new in zip(old_rows,new_rows)]
    if shifts and max(shifts)-min(shifts)>2:
        return False
    for old,new,shift in zip(old_rows,new_rows,shifts):
        risks=risk_by_position.get(old['position'],[])
        if not risks:
            continue
        if abs(old['staff_spacing']-new['staff_spacing'])>1:
            return False
        with Image.open(state.artifact(task,captures[old['capture']])) as image:
            left=geometry.ink_mask(image)
        with Image.open(state.artifact(task,captures[new['capture']])) as image:
            right=geometry.ink_mask(image)
        shift=round(shift)
        x0=max(old['bbox'][0],new['bbox'][0])
        x1=min(old['bbox'][2],new['bbox'][2])
        y0=max(old['bbox'][1],new['bbox'][1]-shift,0,-shift)
        y1=min(old['bbox'][3],new['bbox'][3]-shift,left.shape[0],right.shape[0]-shift)
        if x1<=x0 or y1<=y0:
            return False
        first=left[y0:y1,x0:x1].copy()
        second=right[y0+shift:y1+shift,x0:x1].copy()
        for risk in risks:
            if risk['code']=='crop_edge':
                continue
            bx0,by0,bx1,by1=risk['bbox']
            first[max(0,by0-y0):max(0,by1-y0),max(0,bx0-x0):max(0,bx1-x0)]=0
            second[max(0,by0-y0):max(0,by1-y0),max(0,bx0-x0):max(0,bx1-x0)]=0
        if not score_geometry.same_ink(first,second):
            return False
    return True


def auto_freeze(task, title=None):
    record=state.load(task)
    survey=record.get('overview')
    if not survey:
        overview(task)
        record=state.load(task)
        survey=record['overview']
    try:
        require_frozen(record)
        if record['freeze']['producer']=='program' and (title is None or title.strip()==record['title']):
            return {'status':'frozen','freeze':record['freeze'],'checks':record['program_checks'],
                **{k:record[k] for k in ('regions','rough','rough_chunks')},'next':{'operation':'redraw-inputs'}}
    except state.ReconstructionError:
        pass
    captures={c['id']:c for c in record['captures']}
    reviews = record.get('continuity_reviews', [])
    # Keep the actual frames the Agent reviewed in both navigation modes.
    for review in reviews:
        for identifier in (review['previous_capture'], review['capture']):
            if not any(shot['id'] == identifier for shot in survey['candidates']):
                survey['candidates'].append(captures[identifier])
    survey['candidates'].sort(key=lambda shot: shot['timestamp'])
    reconciliation = []
    for review in reviews:
        first, last = captures[review['previous_capture']], captures[review['capture']]
        if any(first['timestamp'] < shot['timestamp'] < last['timestamp'] for shot in survey['candidates']):
            reconciliation.append({'code': 'numbered_anchor_requires_reconciliation',
                'previous_capture': first['id'], 'capture': last['id'],
                'reason': 'New observations between reviewed anchors need original-position review.'})
    if reconciliation:
        # Continuous coverage adds evidence; it cannot erase an established
        # later occurrence just because its music has the same pixels.
        checks = {'producer': 'program', 'policy_version': PROGRAM_CHECK_VERSION,
            'method': 'numbered_anchor_revalidation_required', 'source_sha256': record['source']['sha256'],
            'scan': survey['scan'], 'unresolved': reconciliation + continuity.numbered_conflicts(record)}
        record.update(program_checks=checks, status='needs_source_review',
            source_review={'producer': 'program', 'complete': False, 'unresolved': checks['unresolved']})
        if 'row_manifest' in record:
            record['row_manifest'].update(continuity_complete=False, unresolved=checks['unresolved'])
            for row in record['row_manifest']['rows']:
                row.update(status='unresolved', issues=checks['unresolved'])
        record.pop('freeze', None)
        state.save(task, record)
        return {'status': 'blocked', 'checks': checks,
            **{key: record[key] for key in ('regions', 'rough', 'rough_chunks') if key in record},
            'resume': 'Review new observations and assemble confirmed original positions; existing materials are preserved.'}
    @lru_cache(maxsize=4)
    def native_mask(identifier):
        with Image.open(state.artifact(task,captures[identifier])) as image:
            return geometry.ink_mask(image)
    sparse = survey.get('mode') == 'sparse'
    if sparse:
        unresolved = [] if record.get('navigation', {}).get('status') == 'observed' else [
            {'code': 'navigation_incomplete', 'resume': 'stage'}]
        unresolved.extend(record.get('navigation', {}).get('unresolved', []))
    else:
        unresolved=[] if survey['scan']['complete'] else [{'code':'unobserved_interval','resume':'overview'}]
    unresolved.extend(continuity.numbered_conflicts(record))
    if survey['scan'].get('policy_version')!=SCAN_POLICY_VERSION:
        unresolved.append({'code':'scan_policy_changed','resume':'overview or prepare a new independent task'})
    chosen, previous, previous_signatures=[],[],[]
    events=[]
    deferred=[]
    observations=[]
    # First discover every observation, so a later complete view can resolve an
    # earlier viewport fragment without inventing its hidden portion.
    signature_pixels=0
    interned_signatures={}
    canonical_spacing=None
    for occurrence,shot in enumerate(survey['candidates']):
        with Image.open(state.artifact(task,shot)) as image:
            regions,risks,partial=detect(image)
            risks+=_apply_revisions(task,record,shot,regions)
            systems=[{**r,'capture':shot['id']} for r in regions if r['kind']=='system']
            if systems and canonical_spacing is None:
                canonical_spacing=max(1,round(float(np.median([r['staff_spacing'] for r in systems]))))
            signatures=[score_geometry.row_signature(image,r,spacing=canonical_spacing) for r in systems]
            cores=[score_geometry.row_signature(image,r,core=True,spacing=canonical_spacing) for r in systems]
            header_signatures=[geometry.ink_mask(image.crop(r['bbox']))
                for r in regions if r['kind']=='header']
            if sparse:
                import row_anchors
                anchors = row_anchors.readings(record, shot, image, regions, task=task)
                unresolved.extend(row_anchors.missing(record, shot, anchors))
        for values in (signatures,cores):
            for index,signature in enumerate(values):
                key=(signature.shape,hashlib.sha256(signature.tobytes()).digest())
                if key in interned_signatures:
                    values[index]=interned_signatures[key]
                else:
                    interned_signatures[key]=signature
                    signature_pixels+=signature.size
        if signature_pixels>SIGNATURE_PIXELS:
            unresolved.append({'code':'matching_pixel_budget','capture':shot['id'],'resume':'resample'})
            break
        observations.append((occurrence,shot,regions,systems,signatures,risks,cores,header_signatures))
        deferred.extend({'capture':shot['id'],**p} for p in partial)
    observation_index={item[1]['id']:index for index,item in enumerate(observations)}
    # A temporal occurrence can contain many compression/highlight candidates.
    # Preserve all observations, but use its adjacent layout occurrence as the
    # complete source of a viewport fragment, with unchanged full rows as anchors.
    groups=[]
    for index,item in enumerate(observations):
        stable=False
        if groups:
            prior=observations[groups[-1][-1]]
            stable=(len(item[3])==len(prior[3]) and len(item[3])>=2 and
                sum(score_geometry.same_ink(a,b) for a,b in zip(item[4],prior[4]))>=2)
            if (not stable and len(item[3]) == len(prior[3]) and len(item[3]) >= 2 and
                    all(abs(a['bbox'][1]+a['staff_top']-b['bbox'][1]-b['staff_top']) <= 2
                        for a, b in zip(prior[3], item[3]))):
                with Image.open(state.artifact(task, prior[1])) as before, \
                        Image.open(state.artifact(task, item[1])) as after:
                    stable = all(score_geometry.same_row(before, a, after, b, canonical_spacing)
                                 for a, b in zip(prior[3], item[3]))
        if stable:
            groups[-1].append(index)
        else:
            groups.append([index])
    group_index={index:g for g,indices in enumerate(groups) for index in indices}
    for partial in deferred:
        index=observation_index[partial['capture']]
        group=group_index[index]
        indices=[]
        if group>0:
            indices.append(groups[group-1][-1])
        if group+1<len(groups):
            indices.append(groups[group+1][0])
        neighbours=[observations[i] for i in indices]
        atlas=[]
        # Only neighbouring observations can establish a viewport continuation.
        # Load bounded local patches instead of a quadratic whole-song atlas.
        for neighbour in neighbours:
            if not neighbour[3]:
                continue
            with Image.open(state.artifact(task,neighbour[1])) as image:
                native=geometry.ink_mask(image)
            for row in neighbour[3]:
                box=row['bbox']
                atlas.append((row,native[box[1]:box[3],box[0]:box[2]].copy()))
        partial['resolved']=_partial_recovered(task,partial,atlas,captures,observations,neighbours,native_mask,
                                              record if sparse else None)
        if not partial['resolved']:
            unresolved.append({**partial,'code':'incomplete_system'})
    risk_by_position={}
    previous_cores=[]
    previous_header_signatures=[]
    for occurrence,shot,regions,systems,signatures,risks,cores,header_signatures in observations:
        if not systems:
            events.append({'capture':shot['id'],'pts':shot['pts'],'kind':'no_complete_staff'})
            previous,previous_signatures,previous_cores=[],[],[]
            continue
        unresolved.extend({'capture':shot['id'],**risk} for risk in risks if not any(
            risk['bbox'][1]<row['bbox'][3] and risk['bbox'][3]>row['bbox'][1] for row in systems))
        signatures=list(signatures)
        numbered_join = previous and continuity.numbered_evidence(record, captures[previous[0]['capture']], shot)
        anchor_comparison = None
        if sparse and previous and not numbered_join:
            anchor_comparison = continuity.compare(task, record, captures[previous[0]['capture']], shot)
            if anchor_comparison.get('reason') in ('printed_bar_gap_needs_continuation', 'printed_bar_content_conflict'):
                numbered_join = True
        if (not numbered_join and previous and len(previous) == len(systems) and
                all(abs(new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top']) <= 2
                    for old, new in zip(previous, systems))):
            with Image.open(state.artifact(task, captures[previous[0]['capture']])) as old_image, \
                    Image.open(state.artifact(task, shot)) as new_image:
                if score_geometry.same_observation(old_image, new_image):
                    signatures, cores = list(previous_signatures), list(previous_cores)
        ambiguous_change=False
        stationary=(not numbered_join and len(previous)==len(systems) and len(systems)>=3 and
            all(abs(new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top'])<=2
                for old,new in zip(previous,systems)) and
            sum(score_geometry.same_ink(a,b) for a,b in zip(previous_signatures,signatures))>=2)
        if stationary:
            for index,(first,second) in enumerate(zip(previous_signatures,signatures)):
                if score_geometry.same_ink(first,second):
                    continue
                kernel=np.ones((3,3),np.uint8)
                unmatched=((first>0)&(cv2.dilate(second,kernel)==0))|((second>0)&(cv2.dilate(first,kernel)==0))
                yy,xx=np.where(unmatched)
                if len(xx)==1:
                    row=systems[index]
                    old=previous[index]
                    source=next((r for r in chosen if r.get('position')==old['position']),old)
                    edge=any(r['code']=='crop_edge' and r['bbox'][1]<row['bbox'][3] and
                        r['bbox'][3]>row['bbox'][1] for r in risks)
                    if edge and not risk_by_position.get(old['position']) and score_geometry.native_visible_match(source,row,native_mask):
                        continue
                    ambiguous_change=True
                    top=round(systems[index]['bbox'][1]+systems[index]['staff_top'])-8*canonical_spacing
                    unresolved.append({'code':'ambiguous_visible_ink_change','capture':shot['id'],
                        'previous_capture':previous[index]['capture'],
                        'bbox':[int(xx[0]),int(yy[0]+top),int(xx[0])+1,int(yy[0]+top)+1],
                        'reason':'A single unmatched native pixel cannot establish new music or raster noise.'})
        if ambiguous_change:
            for row,old in zip(systems,previous):
                row['position']=old['position']
            events.append({'capture':shot['id'],'pts':shot['pts'],'kind':'systems',
                'visual_decision_needed':True,'positions':[r['position'] for r in systems]})
            previous,previous_signatures,previous_cores=systems,signatures,cores
            previous_header_signatures=header_signatures
            continue
        spatial={} if numbered_join else score_geometry.spatial_continuation(previous,systems,previous_cores,cores,native_mask)
        if anchor_comparison and anchor_comparison.get('reason') == 'printed_bar_overlap':
            spatial = anchor_comparison['matches']
        if spatial:
            shift=round(float(np.median([systems[j]['bbox'][1]+systems[j]['staff_top']-
                previous[i]['bbox'][1]-previous[i]['staff_top'] for j,i in spatial.items()])))
            old_native=native_mask(previous[0]['capture'])
            new_native=native_mask(shot['id'])
            for index,header in enumerate(r for r in regions if r['kind']=='header'):
                x0,y0,x1,y1=header['bbox']
                recovered=(0<=y0-shift<y1-shift<=old_native.shape[0] and
                    score_geometry.same_ink(old_native[y0-shift:y1-shift,x0:x1],new_native[y0:y1,x0:x1]))
                if recovered:
                    unresolved=[r for r in unresolved if not (r.get('capture')==shot['id'] and
                        r.get('bbox')==header['bbox'])]
                elif not any(score_geometry.same_ink(header_signatures[index],signature) for signature in previous_header_signatures):
                    chosen.append({**header,'capture':shot['id'],'position':f'event-{occurrence}-header'})
            for index,row in enumerate(systems):
                row_risks=[{'capture':shot['id'],**risk} for risk in risks if
                    risk['bbox'][1]<row['bbox'][3] and risk['bbox'][3]>row['bbox'][1]]
                if index in spatial:
                    old=previous[spatial[index]]
                    row['position']=old['position']
                    old_risks=risk_by_position.get(old['position'],[])
                    if old_risks and not row_risks and score_geometry.native_visible_match(old,row,native_mask):
                        chosen=[row if r.get('position')==old['position'] else r for r in chosen]
                        risk_by_position[old['position']]=[]
                    elif not old_risks and all(r['code']=='crop_edge' for r in row_risks):
                        row_risks=[]
                else:
                    row['position']=f'event-{occurrence}-row-{index}'
                    chosen.append(row)
                if row_risks:
                    risk_by_position.setdefault(row['position'],[]).extend(row_risks)
            previous,previous_signatures,previous_cores=systems,signatures,cores
            previous_header_signatures=header_signatures
            events.append({'capture':shot['id'],'pts':shot['pts'],'kind':'systems',
                'spatial_continuation':True,'matched_rows':spatial,
                'positions':[r['position'] for r in systems]})
            continue
        resolved_edges=set()
        for index,row in enumerate(systems if not numbered_join else []):
            row_risks=[risk for risk in risks if risk['bbox'][1]<row['bbox'][3] and risk['bbox'][3]>row['bbox'][1]]
            if not row_risks or any(risk['code']!='crop_edge' for risk in row_risks):
                continue
            for old_index,old in enumerate(previous):
                source=next((r for r in chosen if r.get('position')==old['position']),old)
                if risk_by_position.get(old['position']) or not score_geometry.native_visible_match(source,row,native_mask):
                    continue
                shift=row['bbox'][1]+row['staff_top']-old['bbox'][1]-old['staff_top']
                anchored_other=any(score_geometry.same_ink(previous_signatures[i],signatures[j]) and
                    abs((new['bbox'][1]+new['staff_top']-prior['bbox'][1]-prior['staff_top'])-shift)<=2
                    for i,prior in enumerate(previous) for j,new in enumerate(systems) if i!=old_index and j!=index)
                if anchored_other:
                    signatures[index]=previous_signatures[old_index]
                    resolved_edges.add(index)
                    break
        # A damaged observation may be replaced only with spatially anchored
        # clean evidence. Matching surrounding systems establish its position.
        anchored=(not numbered_join and len(systems)==len(previous) and len(systems)>=2 and
            any(score_geometry.same_ink(a,b) for a,b in zip(previous_signatures,signatures)) and
            any(risk_by_position.get(r['position']) for r in previous))
        if anchored and not risks and all(score_geometry.same_ink(a,b) for a,b in zip(previous_cores,cores)) and _compatible_repair(task,previous,systems,risk_by_position,captures):
            positions=[r['position'] for r in previous]
            for index,row in enumerate(systems):
                row['position']=positions[index]
                if risk_by_position.get(positions[index]):
                    chosen=[row if r.get('position')==positions[index] else r for r in chosen]
                    risk_by_position[positions[index]]=[]
            previous,previous_signatures,previous_cores=systems,signatures,cores
            events.append({'capture':shot['id'],'pts':shot['pts'],'kind':'systems',
                'replacement_of_damaged_observation':True,'positions':positions})
            continue
        overlaps=[] if numbered_join else score_geometry.overlap_sizes(previous_signatures, signatures)
        prefix=0
        # Fixed upper systems are anchors only when a lower row visibly moves
        # upwards into the old suffix. Equal prefixes alone do not dedup pages.
        while not numbered_join and prefix<min(len(previous),len(systems)) and score_geometry.same_ink(previous_signatures[prefix],signatures[prefix]):
            prefix+=1
        moving=[]
        if prefix and prefix<min(len(previous),len(systems)):
            moving=score_geometry.overlap_sizes(previous_signatures[prefix:], signatures[prefix:])
        if moving:
            overlaps=moving
        else:
            prefix=0
        if len(overlaps)>1:
            unresolved.append({'code':'ambiguous_overlap','capture':shot['id']})
            overlap=0
        else:
            overlap=overlaps[0] if overlaps else 0
        headers=[r for r in regions if r['kind']=='header']
        for index,header in enumerate(headers):
            if not any(score_geometry.same_ink(header_signatures[index],signature) for signature in previous_header_signatures):
                chosen.append({**header,'capture':shot['id'],'position':f'event-{occurrence}-header'})
        for index,row in enumerate(systems):
            if index<prefix:
                row['position']=previous[index]['position']
            elif index<prefix+overlap:
                row['position']=previous[-overlap+index-prefix]['position']
            else:
                row['position']=f'event-{occurrence}-row-{index}'
                chosen.append(row)
            row_risks=[{'capture':shot['id'],**risk} for risk in risks if
                risk.get('bbox') and not (risk['bbox'][3]<=row['bbox'][1] or risk['bbox'][1]>=row['bbox'][3])]
            if index in resolved_edges and any(r.get('position')==row['position'] for r in chosen):
                row_risks=[]
            if row_risks:
                risk_by_position.setdefault(row['position'],[]).extend(row_risks)
        previous,previous_signatures,previous_cores=systems,signatures,cores
        previous_header_signatures=header_signatures
        events.append({'capture':shot['id'],'pts':shot['pts'],'kind':'systems',
            'fixed_prefix_rows':prefix,'overlap_rows':overlap,'positions':[r['position'] for r in systems]})
    unresolved.extend(risk for risks in risk_by_position.values() for risk in risks)
    if sparse:
        prior = None
        for event in events:
            if event['kind'] != 'systems':
                continue
            if prior:
                first, last = captures[prior['capture']], captures[event['capture']]
                numbered = continuity.numbered_evidence(record, first, last)
                if numbered:
                    event['numbered_continuation'] = numbered
                elif continuity.covered(record, first, last):
                    event['continuous_transition'] = [first['timestamp'], last['timestamp']]
                elif not (event.get('spatial_continuation') or event.get('overlap_rows') or
                          event.get('replacement_of_damaged_observation')):
                    unresolved.append({'code': 'unproved_row_continuation', 'capture': event['capture'],
                                       'previous_capture': prior['capture'], 'resume': 'stage'})
            prior = event
    if not any(r['kind']=='system' for r in chosen):
        unresolved.append({'code':'no_complete_system'})
    unresolved = list({json.dumps(issue, sort_keys=True): issue for issue in unresolved}.values())
    import row_manifest
    row_manifest.update(task, record, chosen, observations, events, unresolved)
    checks={'producer':'program','policy_version':PROGRAM_CHECK_VERSION,'method':
        'five_line_geometry_and_sparse_continuation' if sparse else 'five_line_geometry_and_continuous_temporal_observation',
        'source_sha256':record['source']['sha256'],'scan':survey['scan'], 'events':events,
        'first':next((e for e in events if e['kind']=='systems'),None),
        'last':next((e for e in reversed(events) if e['kind']=='systems'),None),
        'unresolved':unresolved,'deferred_partial_observations':deferred,
        'warnings':['bar_numbers_unreadable'], 'bar_ranges':None,
        'limitation':'Geometry and visible page order only; no symbol-by-symbol musical verification.'}
    fields=('capture','kind','bbox','staff_top','staff_spacing','position')
    same_materials=([tuple(r.get(key) for key in fields) for r in chosen]==
        [tuple(r.get(key) for key in fields) for r in record.get('regions',[])])
    if unresolved:
        # Scan each actual risk neighbourhood until its evidence frontier stops
        # changing. There is no per-doubt round budget; decode/cache limits apply.
        frontier=hashlib.sha256(json.dumps({'unresolved':unresolved,
            'candidates':[c['sha256'] for c in survey['candidates']]},sort_keys=True).encode()).hexdigest()
        attempted=record.setdefault('automatic_resampling',[])
        if not sparse and not any(item['frontier']==frontier for item in attempted):
            points={captures[r['capture']]['timestamp'] for r in unresolved if r.get('capture') in captures}
            if points:
                intervals=[[max(0,t-.5),min(record['source']['duration'],t+.5)] for t in sorted(points)]
                item={'frontier':frontier,'intervals':intervals,
                    'reason':'music, continuity or crop risk','outcome':'pending'}
                attempted.append(item)
                if survey['scan']['complete']:
                    # Every native PTS in these neighbourhoods is already
                    # observed. Reuse that evidence instead of decoding the
                    # identical pixels again and pretending to gain a view.
                    item.update(new_candidates=[],outcome='no_new_temporal_evidence',
                        reused_continuous_evidence=True,unresolved=unresolved)
                    survey['resamples'].append({'intervals':intervals,
                        'reason':'automatic risk neighbourhood','new_candidates':[],
                        'unresolved':unresolved,'method':'cached_continuous_interval'})
                else:
                    state.save(task,record)
                    supplement=resample(task,intervals,'automatic risk neighbourhood')
                    refreshed=state.load(task)
                    item=refreshed['automatic_resampling'][-1]
                    item['new_candidates']=supplement['resamples'][-1]['new_candidates']
                    item['outcome']='new_evidence' if item['new_candidates'] else 'no_new_temporal_evidence'
                    item['unresolved']=supplement['resamples'][-1]['unresolved']
                    state.save(task,refreshed)
                    if item['new_candidates']:
                        return auto_freeze(task,title)
                    record=refreshed
        if chosen and not same_materials:
            state.invalidate_selection(record)
            try:
                record.update(**geometry.build_selection(task,chosen,captures))
            except state.ReconstructionError as error:
                checks['material_error']=str(error)
        record.update(program_checks=checks,source_review={'producer':'program','complete':False,'unresolved':unresolved},
            status='needs_source_review')
        row_manifest.bind(record)
        record.pop('freeze',None)
        state.save(task,record)
        return {'status':'blocked','checks':checks,
            **{k:record[k] for k in ('regions','rough','rough_chunks') if k in record},
            'resume':'resample or revise-crop, then auto-freeze; unresolved source identity requires Agent review and assemble'}
    if same_materials:
        materials={key:record[key] for key in ('regions','rough','rough_chunks')}
    else:
        materials=geometry.build_selection(task,chosen,captures)
        state.invalidate_selection(record)
    record.update(**materials,title=(title or record.get('title') or 'Score').strip(),
        program_checks=checks,source_review={'producer':'program','complete':True,'unresolved':[]},
        status='ready_to_redraw')
    row_manifest.bind(record)
    freeze(record,'program')
    state.save(task,record)
    return {'status':'frozen','freeze':record['freeze'],'checks':checks,**materials,
        'next':{'operation':'redraw-inputs','host':'host-imagegen'}}


def revise_crop(task, index, bbox):
    record=state.load(task)
    if (record.get('freeze', {}).get('producer') == 'agent' or
            record.get('agent_review_contract') and record.get('source_review', {}).get('producer') != 'program'):
        if type(index) is not int or not 0 <= index < len(record['regions']):
            raise state.ReconstructionError('裁剪引用无效。', code='invalid_request', field='index')
        if any(not r.get('position') for r in record['regions']):
            regions = [{**r, 'position': r.get('position') or str(i)} for i, r in enumerate(record['regions'])]
            region = regions[index]
        else:
            regions = None
            region = dict(record['regions'][index])
        if region['kind'] == 'system' and isinstance(bbox, list) and len(bbox) == 4 and all(type(v) is int for v in bbox):
            region['staff_top'] += region['bbox'][1] - bbox[1]
        region['bbox'] = bbox
        if regions is not None:
            review = {**record['source_review'], 'complete': False,
                      'unresolved': ['局部裁剪已修改，等待实际审阅。']}
            return state.assemble(task, record['title'], regions, review)
        from score_workflow import revise_selection
        return revise_selection(task, [{'position': region['position'], 'region': region}])
    if type(index) is not int or not 0<=index<len(record['regions']):
        raise state.ReconstructionError('裁剪引用无效。')
    regions=[dict(r) for r in record['regions']]
    original_box=list(regions[index]['bbox'])
    old=regions[index]
    if old['kind']=='system' and isinstance(bbox,list) and len(bbox)==4 and all(type(v) is int for v in bbox):
        old['staff_top']+=old['bbox'][1]-bbox[1]
    old['bbox']=bbox
    materials=geometry.build_selection(task,regions,{c['id']:c for c in record['captures']})
    state.invalidate_selection(record)
    record.update(**materials,status='needs_source_review',redraw_pages=[],
        source_review={'producer':'program','complete':False,'unresolved':[{'code':'crop_revision_needs_check'}]})
    record.pop('freeze',None)
    state.invalidate_output(record, 'crop_revision')
    record.setdefault('crop_revisions',[]).append({'index':index,'capture':old['capture'],
        'original_bbox':original_box,'bbox':bbox,'source_sha256':old['source_sha256']})
    import row_manifest
    row_manifest.from_selection(record)
    state.save(task,record)
    return record
