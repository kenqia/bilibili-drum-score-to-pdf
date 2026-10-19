"""Bounded native frame decoding with actual source PTS."""
import json
from functools import lru_cache
import math
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


@lru_cache(maxsize=4)
def frame_sync_args(executable='ffmpeg'):
    """Prefer fps_mode only when this binary advertises it; 4.4 uses vsync."""
    try:
        result = subprocess.run([executable, '-hide_banner', '-h', 'full'],
                                capture_output=True, timeout=5, check=True)
        help_text = (result.stdout + result.stderr).decode(errors='replace')
        if re.search(r'(?m)^\s*-fps_mode(?:\s|\[)', help_text):
            return ('-fps_mode', 'passthrough')
    except (OSError, subprocess.SubprocessError):
        pass
    return ('-vsync', '0')


def probe_video(source):
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                  '-show_entries', 'stream=width,height,avg_frame_rate:format=duration', '-of', 'json', str(source)],
                                 capture_output=True, timeout=30, check=True)
        data = json.loads(process.stdout)
        stream = data['streams'][0]
        metadata = {'width': stream['width'], 'height': stream['height'], 'duration': float(data['format']['duration'])}
        numerator, denominator = map(int, stream.get('avg_frame_rate','0/1').split('/'))
        if numerator > 0 and denominator > 0:
            metadata['frame_duration'] = denominator / numerator
        if not math.isfinite(metadata['duration']) or metadata['duration'] <= 0:
            raise ValueError
        return metadata
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError, OSError):
        raise ConversionError('invalid_input', '无法读取本地视频。请提供可播放的视频文件。') from None


class VideoReader:
    def __init__(self, source, metadata, metrics):
        self.source, self.metadata, self.metrics = Path(source), dict(metadata), metrics
        if 'frame_duration' not in self.metadata:
            self.metadata.update(probe_video(self.source))
        self.scratch = tempfile.TemporaryDirectory(prefix='score-seek-')

    def close(self):
        self.scratch.cleanup()

    def read(self, timestamp=None):
        record, image = self.read_record(timestamp)
        return record["timestamp"], image

    def read_record(self, timestamp=None):
        tail = timestamp is None
        start = max(0, self.metadata['duration'] - 1) if tail else timestamp
        path = Path(self.scratch.name) / 'frame.png'
        command = ['ffmpeg', '-v', 'info', '-nostdin', '-copyts', '-ss', str(math.floor(start * 1_000_000) / 1_000_000),
                   '-threads', '2', '-i', str(self.source), '-vf', 'showinfo', '-an', *frame_sync_args(), '-threads', '1']
        command += ['-update', '1'] if tail else ['-frames:v', '1']
        command += ['-y', str(path)]
        began = time.monotonic()
        self.metrics['seek_count'] += 1
        try:
            budget = min(60, 600 - self.metrics['decode_elapsed'])
            if budget <= 0:
                raise ValueError
            process = subprocess.run(command, capture_output=True, check=True, timeout=budget)
            diagnostic = process.stderr.decode(errors='replace')
            base = re.search(r'config in time_base:\s*(\d+)/(\d+)', diagnostic)
            pts = [int(value) for value in re.findall(r'\bpts:\s*(-?\d+)', diagnostic)]
            if not base or int(base[2]) == 0:
                raise ValueError
            times = [value * int(base[1]) / int(base[2]) for value in pts]
            if not times or not path.exists():
                raise ValueError
            self.metrics['decoded_reported_frames'] += len(times)
            self.metrics['peak_temp_disk'] = max(self.metrics['peak_temp_disk'], path.stat().st_size)
            with Image.open(path) as image:
                result = image.convert('RGB')
            index = -1 if tail else 0
            return {"timestamp": times[index], "pts": pts[index],
                    "time_base": [int(base[1]), int(base[2])]}, result
        except (subprocess.SubprocessError, ValueError, OSError):
            raise ConversionError('decode_failed', '视频解码失败，无法建立原帧与时间的对应记录。') from None
        finally:
            self.metrics['decode_elapsed'] += time.monotonic() - began


    def scan(self, start=0, end=None):
        """Yield every decoded native frame and actual PTS under shared deadlines.

        The caller checkpoints each observed frame. No sparse interval is promoted
        to continuous coverage. Pipe decoding keeps temporary storage bounded.
        """
        import queue
        import threading
        end = self.metadata['duration'] if end is None else end
        if not 0 <= start < end <= self.metadata['duration']:
            raise ConversionError('invalid_input', '扫描区间越界。')
        budget = min(60, 600 - self.metrics['decode_elapsed'])
        if budget <= 0:
            raise ConversionError('decode_failed', '累计解码期限已用尽。')
        command = ['ffmpeg', '-v', 'info', '-nostdin', '-copyts', '-ss', str(start),
            '-t', str(end-start), '-threads', '2', '-i', str(self.source),
            '-vf', 'showinfo', '-an', *frame_sync_args(), '-threads', '1',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
        began = time.monotonic()
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            raise ConversionError('decode_failed', '无法启动视频解码器。') from None
        timer = threading.Timer(budget, process.kill)
        timer.start()
        positions = queue.Queue()
        def diagnostics():
            base = None
            for line in process.stderr:
                line = line.decode(errors='replace')
                match = re.search(r'config in time_base:\s*(\d+)/(\d+)', line)
                if match:
                    base = [int(match[1]), int(match[2])]
                match = re.search(r'\bpts:\s*(-?\d+)', line)
                if match and base and base[1]:
                    pts = int(match[1])
                    positions.put({'pts': pts, 'time_base': base,
                        'timestamp': pts * base[0] / base[1]})
            positions.put(None)
        reader = threading.Thread(target=diagnostics, daemon=True)
        reader.start()
        size = self.metadata['width'] * self.metadata['height'] * 3
        self.metrics['seek_count'] += 1
        last_position = None
        try:
            while True:
                data = process.stdout.read(size)
                if not data:
                    break
                if len(data) != size:
                    raise ConversionError('decode_failed', '扫描帧不完整。')
                position = positions.get(timeout=max(1, budget))
                if position is None:
                    raise ConversionError('decode_failed', '扫描缺少实际 PTS。')
                last_position = position
                self.metrics['decoded_reported_frames'] += 1
                yield position, Image.frombytes('RGB', (self.metadata['width'], self.metadata['height']), data)
            if process.wait() != 0:
                raise ConversionError('decode_failed', '扫描解码失败或超时。')
            allowance = self.metadata.get('frame_duration', 0)
            if last_position is None or last_position['timestamp'] + allowance + 1e-6 < end:
                raise ConversionError('decode_incomplete', '扫描未实际抵达区间末端，保留已观察进度。')
        except queue.Empty:
            raise ConversionError('decode_failed', '扫描缺少实际 PTS 或解码已超时。') from None
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=1)
            process.stdout.close()
            process.stderr.close()
            self.metrics['decode_elapsed'] += time.monotonic() - began
