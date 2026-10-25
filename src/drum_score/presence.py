"""Ephemeral approximate visitors, never associated with task capabilities."""
import threading
from time import monotonic
from .jobs import JobError


class Presence:
    def __init__(self):
        self.visitors = {}
        self.lock = threading.Lock()

    def heartbeat(self, visitor):
        now = monotonic()
        with self.lock:
            self.visitors = {key: seen for key, seen in self.visitors.items() if now - seen < 60}
            if visitor not in self.visitors and len(self.visitors) >= 4096:
                raise JobError('service_busy', '在线统计暂时不可用。', 503)
            self.visitors[visitor] = now
            return {'online': len(self.visitors)}
