"""Title-named primary PDF with source material kept in one directory."""
import re
from pathlib import Path
from video_seek import ConversionError



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

