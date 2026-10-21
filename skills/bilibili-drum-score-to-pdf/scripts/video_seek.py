"""Bounded native frame decoding with actual source PTS."""
import json
from functools import lru_cache
import math
from pathlib import Path
import re
import subprocess
import tempfile
import threading
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


class _MotionDiagnostics:
    """Drain bounded per-native-frame motion summaries, never raw log text.

    A separate thumbnail branch measures mean absolute luma change. The native
    RGB branch is untouched. These are heuristic motion observations, never
    source-integrity hashes or proof that every movement has been detected.
    """
    def __init__(self):
        self.time_base = None
        self.samples = []
        self.native = None
        self.native_count = 0
        self.values_count = 0
        self.maximum = 0.0
        self.last_sample_native_count = 0
        self.pending = None
        self.invalid = False

    def _finish_sample(self, pts):
        if self.native is None or self.native[0] != pts or self.native[1] is None:
            self.invalid = True
        if len(self.samples) >= 4097:
            self.invalid = True
            return
        skipped = max(0, self.native_count - self.last_sample_native_count - 1)
        self.samples.append((pts, self.maximum, skipped))
        self.last_sample_native_count = self.native_count
        self.maximum = 0.0
        self.pending = None

    def drain(self, stream):
        try:
            for line in iter(lambda: stream.readline(4096), b''):
                text = line.decode(errors='replace')
                if 'metadata@motion' in text:
                    header = re.search(r'frame:(\d+)\s+pts:(-?\d+)', text)
                    if header:
                        if int(header[1]) != self.native_count or self.native_count != self.values_count:
                            self.invalid = True
                        pts = int(header[2])
                        if self.native is not None and pts <= self.native[0]:
                            self.invalid = True
                        self.native_count += 1
                        self.native = (pts, None)
                    value = re.search(r'lavfi.signalstats.YDIF=([0-9.eE+-]+)', text)
                    if value:
                        difference = float(value[1])
                        if (self.native is None or self.native[1] is not None
                                or not math.isfinite(difference) or not 0 <= difference <= 255):
                            self.invalid = True
                            continue
                        self.native = (self.native[0], difference)
                        self.values_count += 1
                        self.maximum = max(self.maximum, difference)
                        if self.pending is not None:
                            self._finish_sample(self.pending)
                if 'showinfo@sample' not in text:
                    continue
                base = re.search(r'config in time_base:\s*(\d+)/(\d+)', text)
                if base:
                    value = [int(base[1]), int(base[2])]
                    if not value[1] or self.time_base not in (None, value):
                        self.invalid = True
                    self.time_base = value
                frame = re.search(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)', text)
                if frame:
                    if int(frame[1]) != len(self.samples) or self.pending is not None:
                        self.invalid = True
                    pts = int(frame[2])
                    if self.native is not None and self.native[0] == pts and self.native[1] is not None:
                        self._finish_sample(pts)
                    else:
                        self.pending = pts
        except (OSError, ValueError):
            self.invalid = True

    def records(self, count):
        if (self.invalid or not self.time_base or len(self.samples) != count or not count
                or self.pending is not None or self.native_count != self.values_count):
            raise ConversionError('decode_failed', '实际时间戳与原生运动观察记录不完整。')
        numerator, denominator = self.time_base
        records = [{'pts': pts, 'time_base': self.time_base,
                    'timestamp': pts * numerator / denominator,
                    'native_motion_max_luma_difference': difference,
                    'native_intermediate_frames': skipped}
                   for pts, difference, skipped in self.samples]
        records[-1]['native_trailing_motion_max_luma_difference'] = self.maximum
        records[-1]['native_trailing_frames'] = self.native_count - self.last_sample_native_count
        return records


class VideoReader:
    def __init__(self, source, metadata, metrics):
        self.source, self.metadata, self.metrics = Path(source), dict(metadata), metrics
        if 'frame_duration' not in self.metadata:
            self.metadata.update(probe_video(self.source))
        self.scratch = tempfile.TemporaryDirectory(prefix='score-seek-')

    def close(self):
        self.scratch.cleanup()

    def sample_records(self, interval, consume, *, verify_motion=False):
        """Stream native RGB samples and return actual source PTS, without caching video frames."""
        if not math.isfinite(interval) or interval <= 0 or self.metadata['duration'] / interval > 4096:
            raise ConversionError('invalid_request', '采样间隔无效或采样数量超出资源限制。')
        width, height = self.metadata['width'], self.metadata['height']
        if not 1 <= width * height <= 20_000_000:
            raise ConversionError('resource_limit', '视频画面超出解码资源限制。')
        budget = min(60, 600 - self.metrics['decode_elapsed'])
        if budget <= 0:
            raise ConversionError('decode_failed', '视频解码期限已耗尽。')
        selection = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{interval:.9f})'"
        filters = ('split=2[keep][motion];[motion]'
                   'scale=128:128:force_original_aspect_ratio=decrease,format=yuv444p,'
                   'signalstats,metadata@motion=print:key=lavfi.signalstats.YDIF,nullsink;'
                   '[keep]' + selection + ',showinfo@sample'
                   if verify_motion else selection + ',showinfo')
        command = ['ffmpeg', '-v', 'info', '-nostdin', '-copyts', '-threads', '2',
                   '-filter_threads', '1', '-i', str(self.source), '-vf',
                   filters,
                   '-an', *frame_sync_args(), '-threads', '1', '-pix_fmt', 'rgb24',
                   '-f', 'rawvideo', 'pipe:1']
        began = time.monotonic()
        self.metrics['seek_count'] += 1
        count = 0
        try:
            with tempfile.TemporaryFile() as diagnostic:
                observations = _MotionDiagnostics() if verify_motion else None
                process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE if verify_motion else diagnostic)
                monitor = None
                if observations is not None:
                    monitor = threading.Thread(target=observations.drain, args=(process.stderr,), daemon=True)
                    monitor.start()
                timer = threading.Timer(budget, process.kill)
                timer.daemon = True
                timer.start()
                try:
                    size = width * height * 3
                    while True:
                        data = bytearray()
                        while len(data) < size:
                            chunk = process.stdout.read(size - len(data))
                            if not chunk:
                                break
                            data.extend(chunk)
                        if not data:
                            break
                        if len(data) != size or count >= 4097:
                            raise ConversionError('decode_failed', '采样帧不完整或数量过多。')
                        with Image.frombytes('RGB', (width, height), bytes(data)) as image:
                            consume(count, image)
                        count += 1
                    if process.wait() != 0:
                        raise ConversionError('decode_failed', '连续解码失败或超过期限。')
                finally:
                    timer.cancel()
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    process.stdout.close()
                    if monitor is not None:
                        monitor.join(timeout=5)
                        if monitor.is_alive():
                            raise ConversionError('decode_failed', '原生运动观察未在期限内结束。')
                        process.stderr.close()
                if observations is not None:
                    records = observations.records(count)
                    self.metrics['decoded_reported_frames'] += count
                    self.metrics['native_motion_observations'] = observations.native_count
                    return records
                diagnostic.seek(0)
                text = diagnostic.read().decode(errors='replace')
            base = re.search(r'config in time_base:\s*(\d+)/(\d+)', text)
            pts = [int(v) for v in re.findall(r'\bpts:\s*(-?\d+)', text)]
            if not base or int(base[2]) == 0 or len(pts) != count or not pts:
                raise ConversionError('decode_failed', '实际时间戳记录不完整。')
            time_base = [int(base[1]), int(base[2])]
            self.metrics['decoded_reported_frames'] += count
            return [{'pts': value, 'time_base': time_base,
                     'timestamp': value * time_base[0] / time_base[1]} for value in pts]
        except (subprocess.SubprocessError, OSError):
            raise ConversionError('decode_failed', '连续采样解码失败或超时；未发布长截图。') from None
        finally:
            self.metrics['decode_elapsed'] += time.monotonic() - began

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
