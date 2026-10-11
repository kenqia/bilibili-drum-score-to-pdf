"""Title-named primary PDF with source material kept in one directory."""
import re
from pathlib import Path
from video_seek import ConversionError

MATERIALS = '材料'


def pdf_name(title):
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ConversionError('invalid_input', '谱名须为1至200个字符。')
    # Windows and WSL share these outputs. Keep Unicode, remove path syntax.
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', title).strip().rstrip('. ')
    if not stem:
        raise ConversionError('invalid_input', '谱名没有可用的文件名字符。')
    if stem.upper().split('.')[0].rstrip(' .') in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        stem = '_' + stem
    # Bound UTF-8 bytes for common filesystem component limits.
    while len(stem.encode('utf-8')) > 240:
        stem = stem[:-1]
    return stem + '.pdf'


def package(output, result, title):
    output = Path(output)
    name = pdf_name(title)
    paths = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    def relocate(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('path','image','original_image','source_frame','screenshot') and isinstance(item, str) and item in paths:
                    value[key] = f'{MATERIALS}/{item}'
                else:
                    relocate(item)
        elif isinstance(value, list):
            for item in value:
                relocate(item)
    # Render first, then move the unchanged PDF and exact source pixels.
    material = output / MATERIALS
    material.mkdir()
    for item in list(output.iterdir()):
        if item.name not in ('score.pdf', MATERIALS):
            item.rename(material / item.name)
    (output / 'score.pdf').rename(output / name)
    relocate(result)
    result.update(pdf=name, title=title.strip(), manifest=f'{MATERIALS}/manifest.json')
    return result
