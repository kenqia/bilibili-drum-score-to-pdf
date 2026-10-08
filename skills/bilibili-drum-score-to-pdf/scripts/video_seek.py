"""Bounded native frame decoding with actual source PTS."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from PIL import Image


class ConversionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def probe_video(source):
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                  '-show_entries', 'stream=width,height:format=duration', '-of', 'json', str(source)],
                                 capture_output=True, timeout=30, check=True)
        data = json.loads(process.stdout)
        stream = data['streams'][0]
        metadata = {'width': stream['width'], 'height': stream['height'], 'duration': float(data['format']['duration'])}
        if metadata['duration'] <= 0:
            raise ValueError
        return metadata
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError, OSError):
        raise ConversionError('invalid_input', '无法读取本地视频。请提供可播放的视频文件。') from None


class VideoReader:
    def __init__(self, source, metadata, metrics):
        self.source, self.metadata, self.metrics = Path(source), metadata, metrics
        self.scratch = tempfile.TemporaryDirectory(prefix='score-seek-')

    def close(self):
        self.scratch.cleanup()

    def read(self, timestamp=None):
        tail = timestamp is None
        start = max(0, self.metadata['duration'] - 1) if tail else timestamp
        path = Path(self.scratch.name) / 'frame.png'
        command = ['ffmpeg', '-v', 'info', '-nostdin', '-copyts', '-ss', f'{start:.6f}',
                   '-threads', '2', '-i', str(self.source), '-vf', 'showinfo', '-an', '-vsync', '0', '-threads', '1']
        command += ['-update', '1'] if tail else ['-frames:v', '1']
        command += ['-y', str(path)]
        began = time.monotonic()
        self.metrics['seek_count'] += 1
        try:
            budget = min(60, 600 - self.metrics['decode_elapsed'])
            if budget <= 0:
                raise ValueError
            process = subprocess.run(command, capture_output=True, check=True, timeout=budget)
            times = [float(value) for value in re.findall(r'\bpts_time:([0-9.eE+-]+)', process.stderr.decode(errors='replace'))]
            if not times or not path.exists():
                raise ValueError
            self.metrics['decoded_reported_frames'] += len(times)
            self.metrics['peak_temp_disk'] = max(self.metrics['peak_temp_disk'], path.stat().st_size)
            with Image.open(path) as image:
                result = image.convert('RGB')
            return (times[-1] if tail else times[0]), result
        except (subprocess.SubprocessError, ValueError, OSError):
            raise ConversionError('decode_failed', '视频解码失败，无法建立原帧与时间的对应记录。') from None
        finally:
            self.metrics['decode_elapsed'] += time.monotonic() - began
