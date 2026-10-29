"""ReportLab implementation of the PDF-writing subset used by the kit.

Coordinates retain the kit's top-left convention. Grayscale values are embedded
as RGB for the website's temporary print layout, without changing geometry.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def paper_size(name):
    if name.lower() != 'a4':
        raise ValueError('Only A4 is used by the kit')
    # MuPDF's integer A4 size is part of the supplied pagination geometry.
    return round(A4[0]), round(A4[1])


def Rect(left, top, right, bottom):
    return left, top, right, bottom


class _Page:
    def __init__(self, document, height):
        self.document = document
        self.height = height

    def insert_image(self, rect, *, stream):
        left, top, right, bottom = rect
        with Image.open(BytesIO(stream)) as source, source.convert('RGB') as image:
            self.document.drawImage(ImageReader(image), left, self.height - bottom,
                                    width=right - left, height=bottom - top)


class _Document:
    def __init__(self):
        self.buffer = BytesIO()
        self.canvas = canvas.Canvas(self.buffer, invariant=1, pageCompression=1)
        self.pages = 0

    def new_page(self, *, width, height):
        if self.pages:
            self.canvas.showPage()
        self.canvas.setPageSize((width, height))
        self.pages += 1
        return _Page(self.canvas, height)

    def save(self, output, **kwargs):
        self.canvas.save()
        with Path(output).open('xb') as stream:
            stream.write(self.buffer.getvalue())

    def __len__(self):
        return self.pages

    def close(self):
        self.buffer.close()


def open():
    return _Document()
