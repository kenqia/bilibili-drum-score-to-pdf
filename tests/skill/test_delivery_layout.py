import sys
from pathlib import Path
import unittest

class DeliveryLayoutTests(unittest.TestCase):
    def test_filename_is_portable_and_cannot_escape_output(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'skills/bilibili-drum-score-to-pdf/scripts'))
        from delivery_layout import pdf_name
        from video_seek import ConversionError
        for title in ('../曲名', 'CON', '曲'*200, 'A:B?C\\D'):
            name = pdf_name(title)
            self.assertEqual(Path(name).name, name)
            self.assertNotIn('\\', name)
            self.assertLessEqual(len(name.encode('utf-8')), 244)
        for title in ('', '   ', 'x'*201):
            with self.assertRaises(ConversionError):
                pdf_name(title)
