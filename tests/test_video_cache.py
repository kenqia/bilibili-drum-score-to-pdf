"""Cache behavior through HTTP and real workers; only anonymous metadata/HTTP is offline."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

import test_web_worker as web_fixture
from record_contracts import assert_record

NETWORK = r'''import hashlib, io, json, os, time
from pathlib import Path
from drum_score import bbdown_cli, anonymous_network, anonymous_backend
root=Path(os.environ['SYNTHETIC_NETWORK_ROOT'])
def inspect(origin, staging):
    duration=float((root/'duration').read_text()) if (root/'duration').exists() else 2.0
    version=(root/'version').read_text() if (root/'version').exists() else 'first'
    return {'cid':100+origin['page'],'aid':1,'duration':duration,'backend_build':'synthetic',
        'backend_sha256':'a'*64,'play':{'dash':{'video':[{'id':32,'width':1,'height':1,
        'codecs':'avc1','baseUrl':'https://synthetic.bilivideo.com/media/'+str(origin['page'])+'?version='+version}]}}}
class Response(io.BytesIO):
    def __init__(self,data,headers,status):
        super().__init__(data); self.headers=headers; self.status=status
class Transport:
    def __init__(self,*args,**kwargs): self.stage='metadata'; self.backend_error_type=None
    def open(self,url,headers=None,data=None):
        payload=(root/'input.mp4').read_bytes()
        etag='"'+(root/'version').read_text().strip()+'"' if (root/'version').exists() else '"first"'
        values={'ETag':etag,'Content-Length':str(len(payload))}
        if headers and headers.get('Range'):
            values.update({'Content-Range':'bytes 0-0/'+str(len(payload)),'Content-Length':'1'})
            return Response(payload[:1],values,206)
        descriptor=os.open(root/'fetches',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        os.write(descriptor,b'fetch\n'); os.close(descriptor)
        (root/'fetch-started').touch()
        while (root/'mode').read_text()=='wait' and not (root/'release').exists(): time.sleep(.02)
        return Response(payload,values,200)
bbdown_cli.inspect=inspect
anonymous_network.PublicTransport=Transport
anonymous_backend.PublicTransport=Transport
'''

@unittest.skipUnless(Path('/proc').is_dir(), 'Linux process lifecycle')
class VideoCache(unittest.TestCase):
    setUp = web_fixture.WebsiteWorker.setUp
    tearDown = web_fixture.WebsiteWorker.tearDown
    worker = web_fixture.WebsiteWorker.worker
    submit = web_fixture.WebsiteWorker.submit
    state = web_fixture.WebsiteWorker.state
    until = web_fixture.WebsiteWorker.until

    def prepare(self):
        (self.network/'sitecustomize.py').write_text(NETWORK)
        (self.network/'duration').write_text('2.0')

    def test_fresh_description_rejects_existing_cache_without_new_media_fetch(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write("\noriginal_inspect=inspect\ndef checked_inspect(origin,staging):\n    from drum_score.description_policy import check\n    policy=check('synthetic ♥' if (root/'reject-heart').exists() else 'ordinary',origin)\n    result=original_inspect(origin,staging)\n    result['description_policy']=policy\n    return result\nbbdown_cli.inspect=checked_inspect\n")
        first, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        self.assertEqual(self.state(first, auth)['state'], 'complete')
        (self.network/'reject-heart').touch()
        second, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        state = self.state(second, auth)
        self.assertEqual(state['state'], 'failed', state)
        self.assertEqual(state['error']['code'], 'unsupported_source')
        self.assertEqual((self.network/'fetches').read_text().splitlines(), ['fetch'])
        from drum_score.jobs import Jobs
        record = Jobs(self.data).records.query(task=second)[0]
        self.assertEqual(record['error']['code'], 'description_policy_rejected')
        self.assertEqual(record['description_policy']['codepoints'], ['U+2665'])

    def test_cache_fetch_failure_preserves_verified_description_and_source(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write("\noriginal_inspect=inspect\ndef checked_inspect(origin,staging):\n    from drum_score.description_policy import check\n    result=original_inspect(origin,staging)\n    result['description_policy']=check('ordinary',origin)\n    return result\nbbdown_cli.inspect=checked_inspect\noriginal_open=Transport.open\ndef fail_media(self,url,headers=None,data=None):\n    if not (headers and headers.get('Range')):\n        from drum_score.public_video import InputError\n        raise InputError('incomplete_video','synthetic incomplete media')\n    return original_open(self,url,headers,data)\nTransport.open=fail_media\n")
        task, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        self.assertEqual(self.state(task, auth)['error']['code'], 'incomplete_video')
        from drum_score.jobs import Jobs
        record = Jobs(self.data).records.query(task=task)[0]
        self.assertEqual(record['input']['resolved_url'], 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2')
        self.assertTrue(record['description_policy']['valid_description'])
        self.assertFalse(record['description_policy']['matched'])

    def test_second_submission_reuses_verified_media_and_keeps_original_deadline(self):
        self.prepare()
        first, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        before = self.state(first,auth)
        self.assertEqual(before['state'],'complete',before)
        assert_record(self, first, auth, status='complete', cache='fill')
        second, auth2 = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        after=self.state(second,auth2)
        self.assertEqual(after['state'],'complete',after)
        assert_record(self, second, auth2, status='complete', cache='hit')
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch'])
        source=after['result']['source']
        self.assertEqual(source['cache']['status'],'hit')
        self.assertEqual(source['cache']['expires_at'],before['result']['source']['cache']['expires_at'])
        self.assertEqual(source['kind'],'bilibili')
        self.assertEqual(source['sha256'],before['result']['source']['sha256'])
        self.assertEqual(self.client.get(f'/api/tasks/{second}/pdf',headers=auth2).status_code,200)

    def test_cancelling_initial_waiter_preserves_shared_fetch_and_other_task(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare()
        (self.network/'mode').write_text('wait')
        first,auth=self.submit()
        process=self.worker(concurrency=2)
        self.until(lambda:(self.network/'fetch-started').exists())
        with TestClient(create_app(self.data),client=('198.51.100.8',2000)) as other:
            second,auth2=self.submit(other)
        self.until(lambda:self.state(second,auth2)['stage']=='source_wait')
        self.client.post(f'/api/tasks/{first}/cancel',headers=auth)
        self.until(lambda:self.state(first,auth)['state']=='cancelled')
        self.assertEqual(self.state(second,auth2)['state'],'running')
        (self.network/'release').touch()
        self.until(lambda:self.state(second,auth2)['state']=='complete')
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch'],self.state(second,auth2)['result']['source']['cache'])
        self.assertEqual(self.state(second,auth2)['result']['source']['cache']['status'],'coalesced')
        assert_record(self, first, auth, status='cancelled')
        assert_record(self, second, auth2, status='complete', cache='coalesced')
        process.terminate();self.assertEqual(process.wait(timeout=15),0)

    def test_shared_download_failure_and_http_retry_keep_independent_complete_records(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare()
        (self.network / 'mode').write_text('wait')
        with (self.network / 'sitecustomize.py').open('a') as script:
            script.write("\noriginal_open=Transport.open\ndef fail_shared(self,url,headers=None,data=None):\n    result=original_open(self,url,headers,data)\n    if not (headers and headers.get('Range')) and not (root/'retry-ready').exists():\n        from drum_score.public_video import InputError\n        raise InputError('incomplete_video','SYNTHETIC_SIGNED_ADDRESS_AND_PRIVATE_PATH')\n    return result\nTransport.open=fail_shared\n")
        first, auth = self.submit()
        process = self.worker(concurrency=2)
        self.until(lambda: (self.network / 'fetch-started').exists())
        with TestClient(create_app(self.data), client=('198.51.100.8', 2000)) as other:
            second, auth2 = self.submit(other)
        self.until(lambda: self.state(second, auth2)['stage'] == 'source_wait')
        (self.network / 'release').touch()
        self.until(lambda: all(self.state(task, a)['state'] == 'failed'
                              for task, a in ((first, auth), (second, auth2))))
        failures = [assert_record(self, task, a, status='failed')
                    for task, a in ((first, auth), (second, auth2))]
        self.assertNotEqual(failures[0]['id'], failures[1]['id'])
        self.assertEqual((self.network / 'fetches').read_text().splitlines(), ['fetch'])
        for failure in failures:
            self.assertEqual(failure['input']['resolved_url'], failure['input']['url'])
            self.assertEqual(failure['error']['code'], 'incomplete_video')
        (self.network / 'retry-ready').touch()
        self.assertEqual(self.client.post(f'/api/tasks/{first}/retry', headers=auth).status_code, 200)
        self.until(lambda: self.state(first, auth)['state'] == 'complete')
        completed = assert_record(self, first, auth, status='complete', operation='retry', cache='fill')
        self.assertNotEqual(completed['id'], failures[0]['id'])
        from drum_score.jobs import Jobs
        self.assertEqual(next(r for r in Jobs(self.data).records.query(task=first)
                              if r['id'] == failures[0]['id']), failures[0])
        process.terminate()
        self.assertEqual(process.wait(timeout=15), 0)

    def test_weak_version_keeps_ordinary_conversion_and_never_reuses_media(self):
        self.prepare()
        (self.network/'version').write_text('weak')
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write("\noriginal_open=Transport.open\ndef weak_open(self,*args,**kwargs):\n response=original_open(self,*args,**kwargs)\n response.headers['ETag']='W/'+response.headers['ETag']\n return response\nTransport.open=weak_open\n")
        for _ in range(2):
            task,auth=self.submit()
            self.assertEqual(self.worker(once=True).wait(timeout=30),0)
            result=self.state(task,auth)
            self.assertEqual(result['state'],'complete',result)
            self.assertEqual(result['result']['source']['cache']['status'],'bypass_version')
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch','fetch'])
        self.assertEqual(list((self.data/'cache').rglob('*.mp4')),[])

    def test_explicit_backup_restore_keeps_cache_expiry_and_registers_new_file_identity(self):
        self._cache_snapshot_roundtrip()

    def test_explicit_v4_upgrade_keeps_cache_usable_and_original_deadline(self):
        self._cache_snapshot_roundtrip(legacy=True)

    def _cache_snapshot_roundtrip(self, legacy=False):
        import subprocess
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare()
        first,auth=self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        before=self.state(first,auth)['result']['source']['cache']
        snapshot=self.root/'snapshot';restored=self.root/'restored'
        for operation,args in [('backup',['--data-root',str(self.data),'--output',str(snapshot),'--services-stopped']),
            ('verify',['--backup-root',str(snapshot)]),('restore',['--backup-root',str(snapshot),'--output',str(restored)])]:
            result=subprocess.run([sys.executable,'-m','drum_score.maintenance',operation,*args,'--min-free-mib','1'],env=self.env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        if legacy:
            import hashlib
            import sqlite3
            with sqlite3.connect(snapshot/'tasks.sqlite3') as db:
                db.execute('DROP TABLE processing_records')
                db.execute('PRAGMA user_version=4')
            manifest=json.loads((snapshot/'snapshot.json').read_text())
            manifest['schema']=4
            entry=next(e for e in manifest['files'] if e['path']=='tasks.sqlite3')
            payload=(snapshot/'tasks.sqlite3').read_bytes()
            entry.update(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
            (snapshot/'snapshot.json').write_text(json.dumps(manifest))
            restored=self.root/'upgraded'
            result=subprocess.run([sys.executable,'-m','drum_score.maintenance','upgrade-v4','--backup-root',str(snapshot),'--output',str(restored),'--min-free-mib','1'],env=self.env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        original=next((self.data/'cache').rglob('video.mp4'));copy=next((restored/'cache').rglob('video.mp4'))
        self.assertNotEqual(original.stat().st_ino,copy.stat().st_ino)
        self.client.close();self.data=restored
        self.client=TestClient(create_app(self.data),client=('198.51.100.9',2000))
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        after=self.state(task,auth)
        self.assertEqual(after['state'],'complete',after)
        self.assertEqual(after['result']['source']['cache']['status'],'hit')
        self.assertEqual(after['result']['source']['cache']['expires_at'],before['expires_at'])
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch'])

    def test_crash_after_media_publication_never_hits_partial_cache_and_cleans_registered_bytes(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
import sqlite3
original_connect=sqlite3.connect
class Connection(sqlite3.Connection):
    def execute(self,sql,*args,**kwargs):
        if sql.startswith("UPDATE video_cache SET state='ready'") and not (root/'untrap').exists():
            (root/'publication-trapped').touch()
            while not (root/'untrap').exists(): time.sleep(.02)
        return super().execute(sql,*args,**kwargs)
def connect(database,*args,**kwargs):
    if str(database).endswith('tasks.sqlite3'): kwargs['factory']=Connection
    return original_connect(database,*args,**kwargs)
sqlite3.connect=connect
''')
        task,auth=self.submit();process=self.worker()
        self.until(lambda:(self.network/'publication-trapped').exists())
        self.assertEqual(len(list((self.data/'cache').rglob('video.mp4'))),1)
        process.kill();process.wait(timeout=10)
        (self.network/'untrap').touch()
        self.assertEqual(self.worker(once=True).wait(timeout=15),0)
        self.assertEqual(self.state(task,auth)['state'],'interrupted')
        self.assertEqual(list((self.data/'cache').rglob('video.mp4')),[])
        self.client.post(f'/api/tasks/{task}/retry',headers=auth)
        self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        self.assertEqual(self.state(task,auth)['state'],'complete')
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch','fetch'])

    def test_cache_hit_still_rejects_updated_overlong_original_before_any_media_request(self):
        self.prepare()
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        self.assertEqual(self.state(task,auth)['state'],'complete')
        (self.network/'duration').write_text('601')
        created=self.client.post('/api/tasks',json={'url':'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2','options':{'end_seconds':1}}).json()
        auth2={'Authorization':'Bearer '+created['capability']}
        self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(created['id'],auth2)
        self.assertEqual(result['state'],'failed',result)
        self.assertEqual(result['error']['code'],'resource_limit')
        self.assertEqual((self.network/'fetches').read_text().splitlines(),['fetch'])
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf',headers=auth).status_code,200)

    def test_changed_media_version_and_page_do_not_reuse_old_source(self):
        self.prepare()
        for index,url in enumerate(('https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2',
                'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2',
                'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=3')):
            if index==1:(self.network/'version').write_text('second')
            created=self.client.post('/api/tasks',json={'url':url}).json()
            auth={'Authorization':'Bearer '+created['capability']}
            self.assertEqual(self.worker(once=True).wait(timeout=30),0)
            result=self.state(created['id'],auth)
            self.assertEqual(result['state'],'complete',result)
            self.assertEqual(result['result']['source']['cache']['status'],'fill')
        self.assertEqual(len((self.network/'fetches').read_text().splitlines()),3)

    def test_too_small_cache_falls_back_and_keeps_unknown_files_and_pdf(self):
        import subprocess
        self.prepare()
        cache=self.data/'cache';cache.mkdir();unknown=cache/'operator-note';unknown.write_text('SYNTHETIC_UNKNOWN')
        for _ in range(2):
            task,auth=self.submit()
            process=subprocess.Popen([sys.executable,'-m','drum_score.worker','--data-root',str(self.data),'--once','--cache-mib','.5'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.processes.append(process);self.assertEqual(process.wait(timeout=30),0)
            result=self.state(task,auth);self.assertEqual(result['state'],'complete',result)
            self.assertEqual(result['result']['source']['cache']['status'],'bypass_capacity')
            self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf',headers=auth).status_code,200)
        self.assertEqual(unknown.read_text(),'SYNTHETIC_UNKNOWN')
        self.assertEqual(list(self.data.rglob('video.mp4')),[])
        self.assertEqual(len((self.network/'fetches').read_text().splitlines()),2)

    def test_last_waiter_does_not_settle_before_acquisition_guardian_releases(self):
        import signal
        self.prepare();(self.network/'mode').write_text('wait')
        task,auth=self.submit();process=self.worker()
        self.until(lambda:(self.network/'fetch-started').exists())
        guardians=self.until(lambda:web_fixture.WebsiteWorker.guardians(self,process))
        guardian=guardians[0];os.kill(guardian,signal.SIGSTOP)
        try:
            self.client.post(f'/api/tasks/{task}/cancel',headers=auth)
            time.sleep(.4)
            self.assertEqual(self.state(task,auth)['state'],'cancelling')
        finally:
            os.kill(guardian,signal.SIGCONT)
        self.until(lambda:self.state(task,auth)['state']=='cancelled')
        self.assertEqual(list(self.data.rglob('video.mp4')),[])
        process.terminate();self.assertEqual(process.wait(timeout=15),0)

    def test_replaced_cache_symlink_is_preserved_without_reading_synthetic_target(self):
        self.prepare()
        first,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        self.assertEqual(self.state(first,auth)['state'],'complete')
        cached=next((self.data/'cache').rglob('video.mp4'))
        sentinel=self.root/'synthetic-private';sentinel.write_bytes(b'SYNTHETIC_DO_NOT_READ')
        cached.unlink();cached.symlink_to(sentinel)
        second,auth2=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(second,auth2)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['cache']['status'],'bypass_capacity')
        self.assertTrue(cached.is_symlink());self.assertEqual(sentinel.read_bytes(),b'SYNTHETIC_DO_NOT_READ')
        self.assertEqual(len((self.network/'fetches').read_text().splitlines()),2)

    def test_cache_file_replaced_after_hit_is_consumed_through_held_descriptor(self):
        self.prepare()
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        before=self.state(task,auth)['result']['source']['sha256']
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
original_setsid=os.setsid
def setsid():
    result=original_setsid()
    counter=root/'setsid-count'
    count=int(counter.read_text())+1 if counter.exists() else 1
    counter.write_text(str(count))
    if count==2:
        (root/'conversion-starting').touch()
        while not (root/'resume-conversion').exists():time.sleep(.01)
    return result
os.setsid=setsid
''')
        second,auth2=self.submit();process=self.worker(once=True)
        self.until(lambda:(self.network/'conversion-starting').exists())
        cached=next((self.data/'cache').rglob('video.mp4'))
        sentinel=self.root/'synthetic-other';sentinel.write_bytes(b'SYNTHETIC_NOT_MEDIA')
        cached.unlink();cached.symlink_to(sentinel)
        (self.network/'resume-conversion').touch()
        self.assertEqual(process.wait(timeout=30),0)
        result=self.state(second,auth2)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['sha256'],before)
        self.assertEqual(result['result']['source']['cache']['status'],'hit')
        self.assertTrue(cached.is_symlink())

    def test_two_inflight_sources_reserve_capacity_before_writing_media(self):
        import subprocess
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare();(self.network/'mode').write_text('wait')
        first,auth=self.submit()
        with TestClient(create_app(self.data),client=('198.51.100.8',2000)) as other:
            created=other.post('/api/tasks',json={'url':'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=3'}).json()
            second,auth2=created['id'],{'Authorization':'Bearer '+created['capability']}
        process=subprocess.Popen([sys.executable,'-m','drum_score.worker','--data-root',str(self.data),'--concurrency','2','--max-temp-mib','64','--cache-mib','1.1'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process)
        self.until(lambda:(self.network/'fetches').exists() and len((self.network/'fetches').read_text().splitlines())==2)
        (self.network/'release').touch()
        self.until(lambda:self.state(first,auth)['state']=='complete' and self.state(second,auth2)['state']=='complete')
        statuses={self.state(task,a)['result']['source']['cache']['status'] for task,a in ((first,auth),(second,auth2))}
        self.assertEqual(statuses,{'fill','bypass_capacity'})
        actual=sum(p.stat().st_size for p in (self.data/'cache').rglob('*') if p.is_file())
        self.assertLessEqual(actual,int(1.1*1024**2))
        process.terminate();self.assertEqual(process.wait(timeout=15),0)

    def test_preferred_stream_failure_preserves_existing_format_fallback(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
original_inspect=bbdown_cli.inspect
def multi_inspect(origin,staging):
    result=original_inspect(origin,staging)
    top=dict(result['play']['dash']['video'][0]);top['baseUrl']='https://synthetic.bilivideo.com/bad';top['height']=2;top['id']=64
    result['play']['dash']['video'].insert(0,top)
    return result
bbdown_cli.inspect=multi_inspect
original_open=Transport.open
def fallback_open(self,url,headers=None,data=None):
    if '/bad' in url and not (headers and headers.get('Range')):
        from urllib.error import HTTPError
        raise HTTPError(url,403,'Synthetic unavailable',{},io.BytesIO())
    return original_open(self,url,headers,data)
Transport.open=fallback_open
''')
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(task,auth)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['selected_format']['format_id'],'32')

    def test_expired_cache_is_removed_while_pdf_keeps_its_own_deadline(self):
        import subprocess
        self.prepare()
        task,auth=self.submit()
        process=subprocess.Popen([sys.executable,'-m','drum_score.worker','--data-root',str(self.data),'--once','--cache-retention-seconds','.2'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process);self.assertEqual(process.wait(timeout=30),0)
        self.assertEqual(self.state(task,auth)['state'],'complete')
        first_expiry=self.state(task,auth)['result']['source']['cache']['expires_at']
        self.assertLess(first_expiry,self.state(task,auth)['expires_at'])
        time.sleep(.25)
        second,auth2=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(second,auth2)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['cache']['status'],'fill')
        self.assertEqual(len((self.network/'fetches').read_text().splitlines()),2)
        self.assertEqual(len(list((self.data/'cache').rglob('video.mp4'))),1)
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf',headers=auth).status_code,200)

    def test_expired_held_source_stays_registered_while_second_task_bypasses(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare()
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
from types import SimpleNamespace
from drum_score import video_cache
clock=video_cache.time
video_cache.time=SimpleNamespace(time=lambda:clock.time()+(90000 if (root/'expire-cache').exists() else 0),monotonic=clock.monotonic,sleep=clock.sleep)
original_setsid=os.setsid
def setsid():
    result=original_setsid();counter=root/'setsid-count'
    count=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(count))
    if count==2:
        (root/'held-conversion').touch()
        while not (root/'resume-conversion').exists():time.sleep(.01)
    return result
os.setsid=setsid
''')
        first,auth1=self.submit();process=self.worker(concurrency=2)
        self.until(lambda:(self.network/'held-conversion').exists())
        cached=next((self.data/'cache').rglob('video.mp4'))
        (self.network/'expire-cache').touch()
        with TestClient(create_app(self.data),client=('198.51.100.8',2000)) as other:
            second,auth2=self.submit(other)
        self.until(lambda:self.state(second,auth2)['state'] in ('complete','failed'))
        result=self.state(second,auth2)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['cache']['status'],'bypass_capacity')
        self.assertTrue(cached.exists(),'held original must remain registered and present')
        (self.network/'resume-conversion').touch()
        self.until(lambda:self.state(first,auth1)['state']=='complete')
        process.terminate();self.assertEqual(process.wait(timeout=15),0)

    def test_backup_resource_with_same_validator_is_not_published_as_preferred_version(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
original_inspect=bbdown_cli.inspect
def backup_inspect(origin,staging):
    result=original_inspect(origin,staging)
    result['play']['dash']['video'][0]['backupUrl']=['https://synthetic.bilivideo.com/other-resource']
    return result
bbdown_cli.inspect=backup_inspect
original_open=Transport.open
def backup_open(self,url,headers=None,data=None):
    if '/media/' in url and not (headers and headers.get('Range')):
        from urllib.error import HTTPError
        raise HTTPError(url,403,'Synthetic unavailable',{},io.BytesIO())
    return original_open(self,url,headers,data)
Transport.open=backup_open
''')
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(task,auth)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['cache']['status'],'bypass_transfer')
        self.assertTrue(result['result']['source']['backup_used'])

    def test_short_transfer_cannot_publish_cache_using_declared_length(self):
        self.prepare()
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
original_open=Transport.open
def short_open(self,url,headers=None,data=None):
    response=original_open(self,url,headers,data)
    if headers and headers.get('Range'):
        size=int(response.headers['Content-Range'].split('/')[-1])+100
        response.headers['Content-Range']='bytes 0-0/'+str(size)
    else:
        response.headers['Content-Length']=str(int(response.headers['Content-Length'])+100)
    return response
Transport.open=short_open
''')
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        result=self.state(task,auth)
        self.assertEqual(result['state'],'failed',result)
        self.assertEqual(result['error']['code'],'source_changed',result)
        self.assertEqual(list((self.data/'cache').rglob('video.mp4')),[])

    def test_unlinked_held_media_still_counts_against_cache_capacity(self):
        import subprocess
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        self.prepare()
        task,auth=self.submit();self.assertEqual(self.worker(once=True).wait(timeout=30),0)
        original_hash=self.state(task,auth)['result']['source']['sha256']
        cached=next((self.data/'cache').rglob('video.mp4'));size=cached.stat().st_size
        with (self.network/'sitecustomize.py').open('a') as script:
            script.write(r'''
original_setsid=os.setsid
def setsid():
    result=original_setsid();counter=root/'setsid-count'
    count=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(count))
    if count==2:
        (root/'held-conversion').touch()
        while not (root/'resume-conversion').exists():time.sleep(.01)
    return result
os.setsid=setsid
''')
        first,auth1=self.submit()
        budget=(1024**2+1.9*size)/1024**2
        process=subprocess.Popen([sys.executable,'-m','drum_score.worker','--data-root',str(self.data),'--concurrency','2','--cache-mib',str(budget)],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process)
        self.until(lambda:(self.network/'held-conversion').exists());cached.unlink()
        with TestClient(create_app(self.data),client=('198.51.100.8',2000)) as other:
            created=other.post('/api/tasks',json={'url':'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=3'}).json()
            second,auth2=created['id'],{'Authorization':'Bearer '+created['capability']}
        self.until(lambda:self.state(second,auth2)['state'] in ('complete','failed'))
        result=self.state(second,auth2)
        self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['result']['source']['cache']['status'],'bypass_capacity')
        (self.network/'resume-conversion').touch()
        self.until(lambda:self.state(first,auth1)['state']=='complete')
        self.assertEqual(self.state(first,auth1)['result']['source']['sha256'],original_hash)
        process.terminate();self.assertEqual(process.wait(timeout=15),0)
