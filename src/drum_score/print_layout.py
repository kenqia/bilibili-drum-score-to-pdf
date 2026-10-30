"""Image-only print layout, without downloading or musical recognition."""
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A3, A4, A5
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from .imaging import system_groups
from .staff_boundaries import split, crop
from .video_seek import ConversionError

PAPERS = {'A3': A3, 'A4': A4, 'A5': A5}
MAX_PIXELS = 20_000_000
MAX_PAGES = 64


def render(image, output, *, paper='A4', rows=None):
    """Keep safe groups and all marks at one uniform scale."""
    if paper not in PAPERS or (rows is not None and (type(rows) is not int or not 1 <= rows <= 16)):
        raise ConversionError('invalid_layout', '请选择 A4、A3 或 A5，每页目标行数须为 1 至 16。')
    if image.width * image.height > MAX_PIXELS:
        raise ConversionError('resource_limit', '谱面超出重新排版像素限制。')
    groups, staffs = system_groups(image, detailed=True)
    cuts, boundary_analysis = split(image, groups, staffs, max_output_pixels=MAX_PIXELS)
    parts = []
    for upper, lower, count in zip(cuts, cuts[1:], boundary_analysis['staffs_per_group']):
        start, end = int(np.median(upper)), int(np.median(lower))
        offset, part = crop(image, upper, lower)
        with part:
            ink = np.flatnonzero((np.min(np.asarray(part.convert('RGB')), axis=2) < 255).any(axis=1))
        top = max(offset, offset + int(ink[0]) - 4) if len(ink) else offset
        bottom = min(int(lower.max()), offset + int(ink[-1]) + 5) if len(ink) else int(lower.max())
        parts.append((top, bottom, count, start, end, upper, lower))
    width, height = PAPERS[paper]
    margin, minimum_gap = 12, 8
    usable = height - 2 * margin
    scale = min((width - 2 * margin) / image.width,
                usable / max(bottom - top for top, bottom, *_ in parts))
    target = rows or 16
    pages, current, used, count = [], [], 0, 0
    for part in parts:
        top, bottom, number, *_ = part
        size = (bottom - top) * scale
        gap = minimum_gap if current else 0
        if current and (count + number > target or used + gap + size > usable + 1e-6):
            pages.append(current)
            current, used, count, gap = [], 0, 0, 0
        current.append(part)
        used += gap + size
        count += number
    if current:
        pages.append(current)
    if len(pages) > MAX_PAGES:
        raise ConversionError('resource_limit', '排版超过 64 页限制，请增加每页目标行数。')
    output = Path(output)
    pdf = output / 'score.pdf'
    if pdf.exists() or any(output.glob('page-*.png')):
        raise ConversionError('output_exists', '排版输出已存在。')
    document = canvas.Canvas(str(pdf), pagesize=(width, height), invariant=1)
    regions = []
    for page in pages:
        ink_height = sum((bottom - top) * scale for top, bottom, *_ in page)
        gap = min(48, max(minimum_gap, (usable - ink_height) / (len(page) - 1))) if len(page) > 1 else 0
        y = height - margin
        for top, bottom, _, _, _, upper, lower in page:
            offset, masked = crop(image, upper, lower)
            with masked, masked.crop((0, top - offset, image.width, bottom - offset)) as part:
                y -= part.height * scale
                document.drawImage(ImageReader(part), (width - image.width * scale) / 2, y,
                                   width=image.width * scale, height=part.height * scale)
                y -= gap
        regions.append([page[0][3], page[-1][4]])
        document.showPage()
    document.save()
    try:
        subprocess.run(['pdftoppm', '-png', '-scale-to', '1400', str(pdf), str(output / 'page')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise ConversionError('preview_failed', '无法生成全部页面预览。') from None
    previews = sorted(output.glob('page-*.png'))
    if len(previews) != len(pages):
        raise ConversionError('preview_failed', '页面预览不完整。')
    actual = max(sum(part[2] for part in page) for page in pages)
    adjusted = rows is not None and any(sum(part[2] for part in page) != rows for page in pages[:-1])
    if rows is not None and (actual > rows or (len(pages) == 1 and actual < rows)):
        adjusted = True
    message = f'已自动调整为每页最多 {actual} 行。' if adjusted else f'共 {len(pages)} 页 {paper}。'
    return {'page_count': len(pages), 'paper': paper, 'target_rows': rows, 'actual_rows': actual,
            'adjusted': adjusted, 'staff_count': len(staffs), 'page_regions': regions,
            'boundary_analysis': boundary_analysis,
            'message': message}


def extract(pdf, output):
    """Recover embedded RGB images in page/paint order from our own PDF."""
    try:
        listing = subprocess.run(['pdfimages', '-list', str(pdf)], check=True,
                                 capture_output=True, timeout=15).stdout.splitlines()[2:]
        records = [line.split() for line in listing]
        if not records or len(records) > 512:
            raise ValueError
        sizes = [(int(row[3]), int(row[4])) for row in records]
        if any(row[2] != b'image' or row[5] != b'rgb' or row[7] != b'8' for row in records):
            raise ValueError
        if len({w for w, h in sizes}) != 1 or sum(w * h for w, h in sizes) > MAX_PIXELS:
            raise ValueError
        subprocess.run(['pdfimages', '-png', str(pdf), str(output / 'source')], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        paths = sorted(output.glob('source-*.png'))
        if len(paths) != len(sizes):
            raise ValueError
        width = sizes[0][0]
        total = sum(h for w, h in sizes) + 8 * (len(sizes) - 1)
        if width * total > MAX_PIXELS:
            raise ValueError
        image = Image.new('RGB', (width, total), 'white')
        top = 0
        for path, size in zip(paths, sizes):
            with Image.open(path) as part:
                if part.size != size:
                    raise ValueError
                image.paste(part, (0, top))
                top += part.height + 8
        return image
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        raise ConversionError('layout_unavailable', '无法安全提取谱面，默认 PDF 仍可下载。') from None
