"""Synthetic contracts for the unmodified kit and its PDF adapter."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ExpertKit(unittest.TestCase):
    def test_fallback_keeps_kit_uncertainty_and_supports_existing_relayout(self):
        from drum_score.core import ConversionError, ResourceBudget
        from drum_score.expert_fallback import process
        from drum_score.print_layout import extract, render
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = video_from_image(score_frame().crop((70, 40, 1210, 910)), root)
            output = root / 'result'
            budget = ResourceBudget(None)
            budget.root = root
            stages = []
            with patch.dict(sys.modules, {'fitz': None, 'pytesseract': None}):
                result = process(video, output, root / 'scratch', {'duration': 2}, stages.append,
                                 budget, ConversionError('discontinuity', 'synthetic'))
            self.assertEqual(stages, ['expert_fallback', 'paginating'])
            self.assertEqual(result['staff_count'], 3)
            self.assertEqual(len(result['pages']), 1)
            self.assertEqual(result['expert']['audit_status'], 'partial_evidence')
            self.assertTrue(result['conversion']['needs_review'])
            self.assertEqual(result['conversion']['engine'], 'expert_v6')
            self.assertFalse(result['expert']['native_timestamps_recorded'])
            self.assertTrue(all(row['pts'] is None and row['time_base'] is None for row in result['expert']['rows']))
            self.assertEqual(result['samples'], [])
            self.assertNotIn(str(root), json.dumps(result))
            self.assertEqual({path.name for path in output.iterdir()}, {'score.pdf', 'page-1.png'})
            layout = root / 'layout'
            layout.mkdir()
            with extract(output / 'score.pdf', layout) as image:
                self.assertEqual(render(image, layout, paper='A5', rows=1)['paper'], 'A5')

    def test_route_only_retries_default_website_algorithm_failures(self):
        from drum_score.core import _convert, ConversionError
        from drum_score.expert_fallback import ELIGIBLE_ERRORS
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = video_from_image(score_frame(), root)
            cases = [
                (False, None, 'discontinuity', False),
                (True, None, 'discontinuity', True),
                (True, {}, 'unsupported_layout', True),
                (True, {'start_seconds': .5}, 'discontinuity', False),
                (True, {'end_seconds': 1}, 'discontinuity', False),
                (True, {'region_percent': [0, 0, 100, 100]}, 'discontinuity', False),
                (True, {'ignore_fixed_overlays': False}, 'discontinuity', False),
            ]
            cases.extend((True, None, code, False) for code in
                         ('resource_limit', 'cancelled', 'invalid_request', 'source_changed',
                          'decode_failed', 'conversion_failed', 'unsafe_media_target', 'preview_failed'))
            for index, (website, options, code, expected) in enumerate(cases):
                with self.subTest(website=website, options=options, code=code):
                    output = root / str(index)
                    error = ConversionError(code, 'synthetic')
                    with patch('drum_score.core._process', side_effect=error), patch('drum_score.expert_fallback.process') as expert:
                        # Stop at dispatch; a real engine/delivery is tested separately.
                        expert.side_effect = ConversionError('expert_failed', 'synthetic')
                        with self.assertRaises(ConversionError) as caught:
                            _convert(video, output, options=options, expert_fallback=website)
                        self.assertEqual(expert.call_count, int(expected))
                        self.assertEqual(caught.exception.code, 'expert_failed' if expected else code)
                        self.assertFalse(output.exists())
                        if expected:
                            args = expert.call_args.args
                            self.assertEqual(args[0], video)
                            self.assertIs(args[-1], error)
            self.assertEqual(ELIGIBLE_ERRORS, {'unsupported_layout', 'discontinuity'})

    def test_successful_primary_never_loads_expert(self):
        from drum_score.core import _convert
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = video_from_image(score_frame(), root)
            with patch('drum_score.expert_fallback.process', side_effect=AssertionError('must not run')):
                first = _convert(video, root / 'plain')
                second = _convert(video, root / 'website', expert_fallback=True)
            self.assertEqual(first['pdf']['sha256'], second['pdf']['sha256'])
            self.assertEqual(first['longshot']['sha256'], second['longshot']['sha256'])
            self.assertNotIn('expert', second)

    def test_non_import_algorithm_ast_matches_supplied_kit(self):
        from drum_score import expert_v6
        root = Path(expert_v6.__file__).parent
        origin = json.loads((root / 'ORIGIN.json').read_text())

        class WithoutImports(ast.NodeTransformer):
            def visit_Import(self, node):
                return None

            def visit_ImportFrom(self, node):
                return None

        for name, identity in origin['files'].items():
            with self.subTest(module=name):
                tree = WithoutImports().visit(ast.parse((root / name).read_text()))
                # Python 3.13's ast.dump omits empty lists; normalize versions.
                for node in ast.walk(tree):
                    for field, value in ast.iter_fields(node):
                        if value == []:
                            delattr(node, field)
                digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
                self.assertEqual(digest, identity['algorithm_ast_sha256'])

    def test_pdf_adapter_keeps_crops_coordinates_and_original_a4_packing(self):
        import numpy as np
        from PIL import Image
        from drum_score.expert_v6.staff_integrity import emit_images_pdf
        # Distinct grayscale values catch color conversion and row ordering.
        images = [np.full((100, 800), 32 + index * 16, dtype=np.uint8) for index in range(10)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(emit_images_pdf(images, root / 'score.pdf'), 2)
            subprocess.run(['pdfimages', '-png', str(root / 'score.pdf'), str(root / 'row')], check=True)
            extracted = sorted(root.glob('row-*.png'))
            self.assertEqual(len(extracted), len(images))
            for path, original in zip(extracted, images):
                with Image.open(path) as actual:
                    self.assertEqual(actual.mode, 'RGB')
                    np.testing.assert_array_equal(np.asarray(actual), np.repeat(original[:, :, None], 3, axis=2))
            subprocess.run(['pdftoppm', '-r', '72', '-png', str(root / 'score.pdf'), str(root / 'page')],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with Image.open(root / 'page-1.png') as page:
                self.assertEqual(page.size, (595, 842))
                self.assertEqual(page.getpixel((40, 40)), (32, 32, 32))
                # Row two begins after the original 8pt gap.
                self.assertEqual(page.getpixel((40, 109)), (48, 48, 48))
                self.assertEqual(page.getpixel((10, 10)), (255, 255, 255))
            with Image.open(root / 'page-2.png') as page:
                self.assertEqual(page.getpixel((40, 40)), (160, 160, 160))
            with self.assertRaises(FileExistsError):
                emit_images_pdf(images, root / 'score.pdf')

    def test_original_missing_staff_boundary_rule_is_retained(self):
        from drum_score.expert_v6.staff_integrity import median_staff_spacing, lattice_centers
        staves = [(84., 7., 0, 1), (270., 7., 0, 1), (360., 7., 0, 1)]
        gap = median_staff_spacing(staves)
        self.assertAlmostEqual(gap, 92.0, delta=2.2)
        centers, virtual = lattice_centers(staves, 360, gap)
        self.assertTrue(virtual)
        self.assertTrue(any(abs(center - 177) < 2 for center in centers))
