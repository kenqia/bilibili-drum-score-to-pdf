"""Synthetic contracts for the unmodified kit and its PDF adapter."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ExpertKit(unittest.TestCase):
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
