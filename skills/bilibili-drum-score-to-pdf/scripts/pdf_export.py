"""Whole native rows, grayscale only, on A4 portrait pages."""
from pathlib import Path
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from video_seek import ConversionError

PRINTABLE_WIDTH_INCHES = (A4[0] - 72) / 72


def write_pdf(output, header, rows):
    output = Path(output)
    canvas = Canvas(str(output / 'score.pdf'), pagesize=A4, pageCompression=1, invariant=1)
    width, height = A4
    margin, gap = 36, 12
    position, page = height - margin, 1
    for block in ([header] if header else []) + rows:
        with Image.open(output / block['image']) as image:
            drawn_width = width - margin * 2
            drawn_height = image.height * drawn_width / image.width
            printable = ImageReader(image.copy())
        if drawn_height > height - margin * 2:
            raise ConversionError('unsupported_layout', '完整谱行无法放入 A4 页面。')
        if position - drawn_height < margin:
            canvas.showPage()
            page += 1
            position = height - margin
        canvas.drawImage(printable, margin, position - drawn_height,
                         width=drawn_width, height=drawn_height)
        block.update(page=page, pdf_bbox=[margin, position - drawn_height, margin + drawn_width, position])
        position -= drawn_height + gap
    canvas.save()
    return page
