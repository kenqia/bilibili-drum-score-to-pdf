"""Public CLI cache behavior; synthetic frames are not music review."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from PIL import Image
import test_reconstruction as fixtures

SCRIPT = Path(__file__).resolve().parents[2] / 'skills/bilibili-drum-score-to-pdf/scripts/convert.py'

class NativeCacheCLI(unittest.TestCase):
    setUp = fixtures.LocalScoreWorkflow.setUp
    tearDown = fixtures.LocalScoreWorkflow.tearDown

    def cli(self, operation, **payload):
        if operation == 'assemble':
            from score_fixtures import controlled_source_review
            payload['review'] = controlled_source_review(payload['regions'], payload['review'])
            self.cli('present', identifiers=payload['review']['viewed_captures'], notes='Controlled synthetic presentation.')
        request = self.root / 'request.json'
        request.write_text(json.dumps(payload))
        args = [sys.executable, str(SCRIPT), '--operation', operation, '--request', str(request)]
        args += [str(self.video), '--output', str(self.task)] if operation == 'prepare' else ['--task', str(self.task)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_resumed_navigation_promotes_native_without_another_decode(self):
        self.cli('prepare')
        first = self.cli('navigate', seconds=0, width=240)
        before = self.cli('resume')['metrics']
        self.cli('prepare')
        second = self.cli('navigate', seconds=0, width=480)
        shot = self.cli('promote', identifier=first['id'])
        record = self.cli('resume')
        self.assertEqual(record['metrics']['seek_count'], before['seek_count'])
        self.assertEqual(record['metrics']['decoded_reported_frames'], before['decoded_reported_frames'])
        self.assertEqual(second['pts'], shot['pts'])
        with Image.open(self.task / shot['path']) as image:
            self.assertEqual(image.size, (640, 320))
        self.assertEqual(self.cli('cache-report')['promotions'], 1)

    def test_eviction_keeps_promoted_evidence_and_missing_cache_is_redecoded(self):
        self.cli('prepare')
        first = self.cli('navigate', seconds=0)
        shot = self.cli('promote', identifier=first['id'])
        self.cli('cache-limits', max_entries=1, max_bytes=1000000)
        second = self.cli('navigate', seconds=.4)
        before = self.cli('cache-report')
        self.assertEqual(before['evictions'], 1)
        self.assertTrue((self.task / shot['path']).is_file())
        self.cli('promote', identifier=first['id'])
        self.assertEqual(self.cli('cache-report')['actual_decodes'], before['actual_decodes'])
        entry = self.cli('resume')['native_cache']['entries'][0]
        (self.task / entry['path']).write_bytes(b'synthetic corruption')
        self.cli('promote', identifier=second['id'])
        after = self.cli('cache-report')
        self.assertEqual(after['actual_decodes'], before['actual_decodes'] + 1)
        self.assertEqual(after['duplicate_decodes'], 1)
        self.assertEqual(after['events'][-1]['reason'], 'corrupt')

    def test_changed_source_rejects_cache_resume(self):
        self.cli('prepare')
        self.cli('navigate', seconds=0)
        self.video.write_bytes(b'changed synthetic source')
        result = subprocess.run([sys.executable, str(SCRIPT), '--operation', 'resume',
            '--task', str(self.task)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'failed')

    def test_uncertain_call_recovery_keeps_budget_and_returns_complete_materials(self):
        self.cli('prepare')
        shot = self.cli('capture', seconds=0)
        regions = [{'capture': shot['id'], 'bbox': [0, 0, 640, 65],
            'kind': 'header', 'position': 'title'}] + [
            {'capture': shot['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system',
             'staff_top': 35, 'staff_spacing': 10, 'position': f'row-{i}'}
            for i in range(3)]
        self.cli('assemble', title='Synthetic score', regions=regions, review={
            'viewed_captures': [shot['id']], 'complete': True, 'notes': 'Controlled selection.',
            'continuity': 'Synthetic ordered rows.', 'first_last': 'Whole synthetic source.'})
        groups = self.cli('redraw-inputs', groups=[[0, 1], [2, 3]])
        first = groups[0]['id']
        request = self.cli('begin-redraw', identifier=first, viewed_notes='Controlled input review.')
        self.cli('prepare')
        (self.root / 'request.json').write_text(json.dumps(
            {'identifier': first, 'viewed_notes': 'Cannot repeat unknown pending call.'}))
        rejected = subprocess.run([sys.executable, str(SCRIPT), '--operation', 'begin-redraw',
            '--task', str(self.task), '--request', str(self.root / 'request.json')],
            capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        resumed = self.cli('redraw-inputs')
        self.assertEqual(resumed[0]['attempts'][0]['request'], request['request'])
        self.cli('finish-redraw', identifier=first, request=request['request'],
            output=str(self.root / 'score.png'), tool='host-imagegen', receipt='controlled result')
        self.cli('review-redraw', identifier=first, accepted=False, notes='Controlled notation difference.')
        correction = self.cli('begin-redraw', identifier=first, viewed_notes='Directed correction.', correction=True)
        self.cli('prepare')
        self.assertEqual(self.cli('redraw-inputs')[0]['corrections_used'], 1)
        self.cli('finish-redraw', identifier=first, request=correction['request'],
            output=str(self.root / 'score.png'), tool='host-imagegen', receipt='controlled correction')
        self.cli('review-redraw', identifier=first, accepted=True,
            notes='Controlled acceptance; not actual music review.', boundaries=[[0,0,640,65],[0,65,640,180]])
        second = groups[1]['id']
        self.cli('begin-redraw', identifier=second, viewed_notes='Controlled input.')
        self.cli('fail-redraw', identifier=second, notes='Unknown result; recovery unavailable, use vector.', outcome='unknown')
        self.assertEqual(self.cli('resume')['redraw_pages'][1]['attempts'][0]['status'], 'unknown')
        rows = self.cli('generation-materials')
        self.assertEqual([r['source_region'] for r in rows], [0,1,2,3])
        self.assertEqual([r['route'] for r in rows], ['imagegen','imagegen','vector','vector'])
        self.assertEqual(rows[1]['crop_bbox'], [0,65,640,180])
        self.assertEqual(rows[1]['source']['capture'], shot['id'])
        self.assertEqual(rows[2]['music_recognition'], False)
        output = self.cli('export')
        self.assertEqual(output['routes'], ['imagegen','vector'])

    def test_evicted_or_missing_candidate_is_a_reported_miss_after_restart(self):
        self.cli('prepare')
        first = self.cli('navigate', seconds=0)
        self.cli('cache-limits', max_entries=1, max_bytes=1000000)
        self.cli('navigate', seconds=.4)
        self.cli('prepare')
        self.cli('promote', identifier=first['id'])
        report = self.cli('cache-report')
        self.assertEqual(report['actual_decodes'], 3)
        self.assertEqual(report['duplicate_decodes'], 1)
        self.assertIn({'reason': 'evicted', 'seconds': 0}, report['events'])
        self.cli('navigate', seconds=.8)
        entry = self.cli('resume')['native_cache']['entries'][0]
        (self.task / entry['path']).unlink()
        self.cli('capture', seconds=.8)
        self.assertEqual(self.cli('cache-report')['events'][-1]['reason'], 'missing')

    def test_default_groups_cover_continuous_rows_independently_of_a4(self):
        self.cli('prepare')
        shot = self.cli('capture', seconds=0)
        regions = [{'capture': shot['id'], 'bbox': [0,0,640,65],
            'kind': 'header', 'position': 'title'}] + [
            {'capture': shot['id'], 'bbox': [0,65,640,180], 'kind': 'system',
             'staff_top': 35, 'staff_spacing': 10, 'position': f'row-{i}'}
            for i in range(12)]
        self.cli('assemble', title='Synthetic long source', regions=regions, review={
            'viewed_captures': [shot['id']], 'complete': True, 'notes': 'Controlled selection.',
            'continuity': 'Ordered fixture rows.', 'first_last': 'Whole synthetic score.'})
        groups = self.cli('redraw-inputs')
        self.assertEqual([g['regions'] for g in groups], [list(range(9)),list(range(9,13))])
        for group in groups:
            self.cli('fail-redraw', identifier=group['id'], notes='Controlled no-tool fallback.')
        printed = self.cli('export')
        self.assertNotEqual([p['region'] for p in printed['placements'] if p['page'] == 1],
            groups[0]['regions'])

    def test_default_grouping_limits_effective_small_symbol_resolution(self):
        tall = self.root / 'tall.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.video), '-vf',
            'scale=640:1200', '-y', str(tall)], check=True)
        self.video = tall
        self.cli('prepare')
        shot = self.cli('capture', seconds=0)
        regions = [{'capture': shot['id'], 'bbox': [0,0,640,65],
            'kind': 'header', 'position': 'title'}] + [
            {'capture': shot['id'], 'bbox': [0,0,640,1200], 'kind': 'system',
             'staff_top': 35, 'staff_spacing': 5, 'position': f'row-{i}'}
            for i in range(8)]
        self.cli('assemble', title='Tall synthetic source', regions=regions, review={
            'viewed_captures': [shot['id']], 'complete': True, 'notes': 'Controlled fixture.',
            'continuity': 'Ordered synthetic rows.', 'first_last': 'Whole synthetic source.'})
        groups = self.cli('redraw-inputs')
        self.assertEqual([g['regions'] for g in groups], [list(range(5)), list(range(5,9))])
