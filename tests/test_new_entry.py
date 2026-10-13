"""Public reconstruction CLI, source safety and old task refusal."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from score_fixtures import CLI, score_frame, video_from_image

class NewEntryTests(unittest.TestCase):
    def call(self,*args):
        p=subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True)
        return p,json.loads(p.stdout) if p.stdout else None

    def test_default_prepares_current_task_and_resumes_without_midi(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);video=video_from_image(score_frame(),base);task=base/'task'
            p,r=self.call(video,'--output',task)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(r['schema'],'score-reconstruction/1')
            self.assertEqual(r['status'],'needs_source_review')
            self.assertFalse((task/'midi-record.json').exists())
            p,resumed=self.call('--operation','resume','--task',task)
            self.assertEqual(resumed['source']['sha256'],r['source']['sha256'])

    def test_old_task_and_unknown_operation_preserve_user_files(self):
        with tempfile.TemporaryDirectory() as d:
            task=Path(d);(task/'task.json').write_text('old task');(task/'notes.txt').write_text('keep')
            p,r=self.call('--operation','resume','--task',task)
            self.assertEqual(p.returncode,2)
            self.assertEqual(r['error']['code'],'invalid_request')
            self.assertEqual((task/'notes.txt').read_text(),'keep')
            p,r=self.call('--operation','convert','--task',task)
            self.assertEqual(p.returncode,2)
            self.assertNotIn('Traceback',p.stderr)

    def test_public_requests_deliver_reviewed_vector_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);video=video_from_image(score_frame(row_count=1),base);task=base/'task'
            self.call(video,'--output',task)
            def operation(name,payload):
                path=base/'request.json';path.write_text(json.dumps(payload))
                p,r=self.call('--operation',name,'--task',task,'--request',path)
                self.assertEqual(p.returncode,0,(p.stderr,r))
                return r
            shot=operation('capture',{'seconds':0})
            operation('present',{'identifiers':[shot['id']],'notes':'Controlled fixture, no live visual claim.'})
            operation('assemble',{'title':'Fixture song','regions':[
                {'capture':shot['id'],'bbox':[100,65,1180,120],'kind':'header','position':'title'},
                {'capture':shot['id'],'bbox':[100,175,1180,340],'kind':'system','staff_top':45,'staff_spacing':12,'position':'written-1'}],
                'review':{'viewed_captures':[shot['id']],'complete':True,'notes':'One-system controlled source.','continuity':'Static fixture.','first_last':'Complete first and final system.'}})
            pages=operation('redraw-inputs',{})
            for page in pages:operation('fail-redraw',{'identifier':page['id'],'notes':'Forced absent host in synthetic fixture.'})
            pdf=operation('export',{})
            self.assertEqual(pdf['page_count'],1)
            self.assertEqual(Path(pdf['pdf']).name,'Fixture song.pdf')
            self.assertTrue((task/pdf['pdf']).is_file())
            reviewed=operation('review-pdf',{'pages':[1],'notes':'Controlled fixture receipt only.'})
            self.assertEqual(reviewed['status'],'reviewed')

    def test_malformed_request_does_not_expose_traceback_or_payload(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);request=base/'request.json'
            request.write_text('{"seconds":{"secret":"SIGNATURE_TEST_SENTINEL"}}')
            p,r=self.call('--operation','capture','--task',base/'missing','--request',request)
            self.assertEqual(p.returncode,2)
            self.assertNotIn('SIGNATURE_TEST_SENTINEL',p.stdout+p.stderr)
            self.assertNotIn('Traceback',p.stderr)
