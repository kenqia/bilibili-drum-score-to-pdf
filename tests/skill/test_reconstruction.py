"""New local-video workflow boundary, agreed in Issue #54."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/bilibili-drum-score-to-pdf/scripts'))
import reconstruction as workflow
from score_fixtures import controlled_reselection


class LocalScoreWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        picture = Image.new('RGB', (640, 320), 'white')
        draw = ImageDraw.Draw(picture)
        draw.text((20, 15), 'Test Score   quarter=120   4/4', fill='black')
        for y in (100, 110, 120, 130, 140):
            draw.line((20, y, 620, y), fill='black')
        draw.ellipse((110, 121, 125, 130), fill='black')
        draw.line((125, 125, 125, 85), fill='black', width=2)
        picture.save(self.root / 'score.png')
        self.video = self.root / 'score.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(self.root / 'score.png'),
                        '-t', '1', '-r', '5', '-pix_fmt', 'yuv420p', '-y', str(self.video)], check=True)
        self.task = self.root / 'task'

    def tearDown(self):
        self.tmp.cleanup()

    def select(self):
        workflow.prepare(self.video, self.task)
        shot = workflow.capture(self.task, 0)
        workflow.assemble(self.task, 'Test Score', [
            {'capture': shot['id'], 'bbox': [0, 0, 640, 65], 'kind': 'header'},
            {'capture': shot['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system',
             'staff_top': 35, 'staff_spacing': 10}],
            {'viewed_captures': [shot['id']], 'complete': True, 'notes': 'One complete score system; title, tempo, meter and ending visible.'})
        return shot

    def test_capture_and_record_writes_reject_external_symlinks(self):
        for component in ('captures','record.tmp','captures/capture-0001.png'):
            with self.subTest(component=component):
                task=self.root/component.replace('.','-').replace('/','-')
                workflow.prepare(self.video,task)
                external=self.root/(component.replace('/','-')+'-external');external.mkdir()
                sentinel=external/'capture-0001.png';sentinel.write_bytes(b'keep')
                target=external if component=='captures' else sentinel
                (task/component).parent.mkdir(parents=True,exist_ok=True)
                (task/component).symlink_to(target,target_is_directory=component=='captures')
                with self.assertRaises(workflow.ReconstructionError):workflow.capture(task,0)
                self.assertEqual(sentinel.read_bytes(),b'keep')

    def test_local_video_delivers_reviewed_named_vector_pdf(self):
        self.select()
        result = workflow.export_vector(self.task)
        self.assertEqual(Path(result['pdf']).name, 'Test Score.pdf')
        self.assertEqual(result['page_count'], 1)
        self.assertEqual(result['status'], 'needs_pdf_review')
        subprocess.run(['pdftoppm', '-scale-to', '600', '-png', '-singlefile',
                        str(self.task / result['pdf']), str(self.root / 'page')], check=True, capture_output=True)
        self.assertTrue((self.root / 'page.png').exists())
        final = workflow.review_pdf(self.task, [1], 'Checked title, tempo, meter, first/last system and no clipping.', output_revision=result['output_revision'])
        self.assertEqual(final['status'], 'reviewed')
        record = json.loads((self.task / 'record.json').read_text())
        self.assertEqual(record['captures'][0]['pts'], 0)
        self.assertEqual(record['output']['method'], 'geometric_contours_and_staff_lines')
        self.assertFalse(record['output']['semantic_transcription'])
        self.assertIsNone(record['metrics']['model_cost'])

    def test_corrupt_redraw_is_rejected_on_resume(self):
        self.select()
        result = workflow.export_vector(self.task)
        (self.task / result['vector']['path']).write_text('{}')
        with self.assertRaises(workflow.ReconstructionError):
            workflow.export_vector(self.task)

    def test_invalid_local_media_has_no_success_record(self):
        invalid = self.root / 'broken.mp4'
        invalid.write_bytes(b'not a movie')
        with self.assertRaises(workflow.ConversionError):
            workflow.prepare(invalid, self.task)
        self.assertFalse((self.task / 'record.json').exists())

    def test_corrupt_original_or_crop_blocks_delivery(self):
        for target in ('source', 'capture', 'crop'):
            with self.subTest(target=target):
                self.task = self.root / target
                shot = self.select()
                record = workflow.load(self.task)
                path = self.video if target == 'source' else self.task / (shot['path'] if target == 'capture' else record['regions'][0]['path'])
                original = path.read_bytes()
                path.write_bytes(b'corrupt')
                with self.assertRaises(workflow.ReconstructionError):
                    workflow.export_vector(self.task)
                path.write_bytes(original)

    def test_unresolved_notation_cannot_be_exported(self):
        shot = self.select()
        record = workflow.load(self.task)
        workflow.assemble(self.task, 'Test Score', record['regions'],
                          {'viewed_captures': [shot['id']], 'complete': True,
                           'notes': 'Hidden symbol needs another frame.', 'unresolved': ['hidden note']})
        with self.assertRaises(workflow.ReconstructionError):
            workflow.export_vector(self.task)

    def test_failed_new_selection_preserves_previous_work(self):
        self.select()
        before = workflow.load(self.task)
        selections = [dict(r) for r in before['regions']]
        selections[0]['bbox'] = [0, 0, 500, 50]
        selections[1]['bbox'] = [0, 0, 9999, 50]
        with self.assertRaises(workflow.ReconstructionError):
            workflow.assemble(self.task, 'Test Score', selections, before['source_review'])
        self.assertEqual(workflow.load(self.task)['regions'], before['regions'])

    def test_existing_user_directory_is_preserved(self):
        self.task.mkdir()
        precious = self.task / 'rough.png'
        precious.write_bytes(b'user artifact')
        with self.assertRaises(workflow.ReconstructionError):
            workflow.prepare(self.video, self.task)
        self.assertEqual(precious.read_bytes(), b'user artifact')

    def test_failed_seek_keeps_actual_consumed_budget(self):
        workflow.prepare(self.video, self.task)
        with self.assertRaises(workflow.ConversionError):
            workflow.capture(self.task, 0.99)
        record = workflow.load(self.task)
        self.assertEqual(record['metrics']['seek_count'], 1)
        self.assertGreater(record['metrics']['decode_elapsed'], 0)
        self.assertEqual(record['last_decode_error'], 'decode_failed')

    def test_repeated_music_and_short_ending_keep_order_across_a4_pages(self):
        shot = self.select()
        initial = workflow.load(self.task)
        regions = [initial['regions'][0]]
        regions += [{**initial['regions'][1], 'score_position': position} for position in range(16)]
        regions[-1] = {**regions[-1], 'bbox': [0, 65, 320, 180]}
        controlled_reselection(self.task, 'Test Score', regions,
                          {'viewed_captures': [shot['id']], 'complete': True,
                           'notes': 'Controlled score: 16 successive repeated passages and a short final system.'})
        result = workflow.export_vector(self.task)
        self.assertEqual(result['page_count'], 3)
        self.assertEqual([p['region'] for p in result['placements']], list(range(17)))
        self.assertEqual(len({p['scale'] for p in result['placements']}), 1)
        final_box = result['placements'][-1]['bbox']
        self.assertAlmostEqual(final_box[2] - final_box[0], 273.6377952755906)
        listed = subprocess.run(['pdfimages', '-list', str(self.task / result['pdf'])],
                                check=True, capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(len(listed), 2)

    def test_reselect_same_title_preserves_old_pdf_and_unknown_user_file(self):
        self.select()
        first = workflow.export_vector(self.task)
        workflow.review_pdf(self.task, [1], 'Controlled test review, not actual visual acceptance.', output_revision=first['output_revision'])
        old_pdf = self.task / first['pdf']
        old_bytes = old_pdf.read_bytes()
        user_pdf = self.task / 'Test Score.pdf'
        user_pdf.write_bytes(b'user-owned PDF')
        record = workflow.load(self.task)
        corrected = [dict(region) for region in record['regions']]
        corrected[0]['bbox'] = [0, 0, 640, 60]
        controlled_reselection(self.task, 'Test Score', corrected, record['source_review'])
        second = workflow.export_vector(self.task)
        self.assertEqual(Path(second['pdf']).name, 'Test Score.pdf')
        self.assertNotEqual(second['pdf'], first['pdf'])
        self.assertEqual(second['status'], 'needs_pdf_review')
        self.assertEqual(old_pdf.read_bytes(), old_bytes)
        self.assertEqual(user_pdf.read_bytes(), b'user-owned PDF')
        self.assertEqual(workflow.export_vector(self.task), second)

    def test_resume_after_export_record_write_interrupt_preserves_sources_and_budget(self):
        self.select()
        before = workflow.load(self.task)
        # Controlled interruption at the persistence boundary, after PDF save.
        with patch.object(Path, 'replace', autospec=True,
                          side_effect=OSError('controlled record write interruption')):
            with self.assertRaises(OSError):
                workflow.export_vector(self.task)
        orphan_pdfs = list(self.task.rglob('*.pdf'))
        self.assertEqual(len(orphan_pdfs), 1)
        orphan = orphan_pdfs[0]
        old_bytes = orphan.read_bytes()
        incomplete = workflow.load(self.task)
        self.assertNotIn('output', incomplete)
        resumed = workflow.export_vector(self.task)
        after = workflow.load(self.task)
        self.assertEqual(Path(resumed['pdf']).name, 'Test Score.pdf')
        self.assertEqual(resumed['status'], 'needs_pdf_review')
        self.assertNotEqual(self.task / resumed['pdf'], orphan)
        self.assertEqual(orphan.read_bytes(), old_bytes)
        self.assertEqual(after['source'], before['source'])
        self.assertEqual(after['captures'], before['captures'])
        self.assertEqual(after['metrics'], before['metrics'])
        self.assertEqual(workflow.export_vector(self.task), resumed)


if __name__ == '__main__':
    unittest.main()
