"""Large registered export provenance does not relax external input limits."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
from agent_delivery import confirm, MAX_EXPORTED_MANIFEST
from agent_workflow import load_json, digest, MAX_JSON
from video_seek import ConversionError


class DeliveryManifestTests(unittest.TestCase):
    def test_registered_large_manifest_accepted_with_separate_bounded_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            out = base / 'output'
            out.mkdir()
            (out / 'score.pdf').write_bytes(b'controlled fixture')
            observation = {'source': {'sha256': 'a' * 64}}
            decision = {'controlled_fixture': True}
            saved = base / 'accepted.json'
            saved.write_text(json.dumps(decision))
            state = dict(task_id='task', phase='accepted', complete=True,
                         observation_sha256='b' * 64,
                         decision_history=[dict(path=saved.name, sha256=digest(saved))])
            manifest = dict(status='success', complete=True, task_id='task',
                            observation_sha256='b' * 64, decision=decision,
                            source=observation['source'], page_count=1)
            manifest_path = out / 'manifest.json'
            manifest_path.write_text(json.dumps(manifest) + ' ' * MAX_JSON)
            receipt = dict(schema_version=1, review_id='fixture-review', task_id='task',
                           lifecycle_id='fixture-lifecycle', observation_sha256='b' * 64,
                           decision_sha256=digest(saved), pdf_sha256=digest(out / 'score.pdf'),
                           manifest_sha256=digest(manifest_path),
                           reviewer=dict(kind='controlled_fixture', id='fixture'),
                           source_manifest_verified=True, complete_score_verified=True,
                           pages=[dict(page=1, evidence='Controlled fixture review.')])
            path = base / 'receipt.json'
            path.write_text(json.dumps(receipt))
            artifact = {k: receipt[k] for k in ('pdf_sha256', 'manifest_sha256',
                                               'observation_sha256', 'decision_sha256')}
            artifact['directory'] = str(out.resolve())
            recorder = SimpleNamespace(directory=base, confirmation=None,
                data=dict(lifecycle_id='fixture-lifecycle', operations=[dict(
                    operation='export', status='success', artifact=artifact)], delivery_history=[]))
            with self.assertRaises(ConversionError):
                load_json(manifest_path)
            result = confirm(out, path, recorder, state, observation, load_json, digest)
            self.assertEqual(result['phase'], 'delivery_confirmed')
            self.assertIsNotNone(recorder.confirmation)
            manifest_path.write_text(json.dumps(manifest) + ' ' * MAX_EXPORTED_MANIFEST)
            receipt['manifest_sha256'] = artifact['manifest_sha256'] = digest(manifest_path)
            path.write_text(json.dumps(receipt))
            with self.assertRaises(ConversionError):
                confirm(out, path, recorder, state, observation, load_json, digest)
            path.write_text(json.dumps(receipt) + ' ' * MAX_JSON)
            with self.assertRaises(ConversionError):
                load_json(path)
