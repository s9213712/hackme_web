import sys
import threading
from collections import deque
from datetime import datetime


class RuntimeOutputBuffer:
    def __init__(self, max_lines=2000):
        self.max_lines = max(100, int(max_lines or 2000))
        self._lines = deque(maxlen=self.max_lines)
        self._partials = {}
        self._lock = threading.Lock()
        self._next_id = 1

    def append(self, stream_name, text):
        if not text:
            return
        with self._lock:
            pending = self._partials.get(stream_name, "") + str(text)
            parts = pending.splitlines(keepends=True)
            self._partials[stream_name] = ""
            for part in parts:
                if part.endswith("\n") or part.endswith("\r"):
                    self._append_line_locked(stream_name, part.rstrip("\r\n"))
                else:
                    self._partials[stream_name] = part

    def _append_line_locked(self, stream_name, line):
        self._lines.append({
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "stream": stream_name,
            "line": line,
        })
        self._next_id += 1

    def tail(self, limit=200):
        try:
            limit = int(limit or 200)
        except Exception:
            limit = 200
        limit = max(1, min(limit, 1000))
        with self._lock:
            rows = list(self._lines)[-limit:]
            for stream_name, partial in self._partials.items():
                if partial:
                    rows.append({
                        "id": self._next_id,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "stream": stream_name,
                        "line": partial,
                        "partial": True,
                    })
            return {"lines": rows, "max_lines": self.max_lines}


class TeeStream:
    def __init__(self, original, buffer, stream_name, log_path=None):
        self.original = original
        self.buffer = buffer
        self.stream_name = stream_name
        self.log_path = log_path
        self._file_lock = threading.Lock()

    def write(self, data):
        if not isinstance(data, str):
            data = str(data)
        try:
            self.original.write(data)
        except Exception:
            pass
        self.buffer.append(self.stream_name, data)
        if self.log_path:
            try:
                with self._file_lock:
                    with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass

    def isatty(self):
        return bool(getattr(self.original, "isatty", lambda: False)())

    def fileno(self):
        return self.original.fileno()

    def writable(self):
        return True

    def __getattr__(self, name):
        return getattr(self.original, name)

    @property
    def encoding(self):
        return getattr(self.original, "encoding", "utf-8")


_BUFFER = RuntimeOutputBuffer()
_INSTALLED = False


def install_runtime_output_capture(log_path=None):
    global _INSTALLED
    if _INSTALLED:
        return _BUFFER
    sys.stdout = TeeStream(sys.stdout, _BUFFER, "stdout", log_path=log_path)
    sys.stderr = TeeStream(sys.stderr, _BUFFER, "stderr", log_path=log_path)
    _INSTALLED = True
    return _BUFFER


def get_runtime_output(limit=200):
    return _BUFFER.tail(limit=limit)
