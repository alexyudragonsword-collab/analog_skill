"""Single background simulation worker.

All ngspice-bound jobs from every tab go through one SimWorker with a FIFO
queue.  Serializing jobs also prevents collisions on the persistent scratch
files the gm/ID sweeps write into logs/ (filenames are keyed only by
model/L/bias, so two concurrent identical sweeps would clobber each other).

Skill code reports progress via print(); the worker captures stdout/stderr
during a job and re-emits complete lines as the ``log_line`` signal.  The
redirect is process-global, which is safe here because only one job runs at
a time and app/ code never prints.
"""

import io
import queue
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from contextlib import redirect_stdout, redirect_stderr


@dataclass
class Job:
    """One unit of work for the SimWorker.

    `fn` runs on the worker thread and must do no Qt or matplotlib work —
    for anything that draws, return a render closure and let the tab call it
    on the GUI thread.  `log_dir` is only consulted on failure, to attach
    the tail of the newest ngspice log to the error text.
    """

    kind: str                       # 'gmid_table' | 'example' | 'browser_plot'
    fn: Callable[[], Any]
    label: str
    log_dir: Path | None = None     # where to look for ngspice logs on failure
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class EmittingStream(io.TextIOBase):
    """File-like object that emits complete lines through a Qt signal."""

    def __init__(self, emit: Callable[[str], None]):
        super().__init__()
        self._emit = emit
        self._buf = ''

    def writable(self):
        return True

    def write(self, text):
        self._buf += text
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            self._emit(line)
        return len(text)

    def flush(self):
        if self._buf:
            self._emit(self._buf)
            self._buf = ''


def _tail_newest_log(log_dir: Path, n_lines: int = 20) -> str:
    """Last lines of the most recent *.log under log_dir, for error context."""
    try:
        logs = sorted(log_dir.glob('*.log'),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return ''
        lines = logs[0].read_text(errors='replace').splitlines()[-n_lines:]
        return f'\n--- tail of {logs[0].name} ---\n' + '\n'.join(lines)
    except OSError:
        return ''


class SimWorker(QThread):
    """The single background thread every simulation runs on.

    One thread, not a pool: the skills' scripts write scratch files to
    fixed paths, so two concurrent gm/ID sweeps would overwrite each
    other's intermediates.  Jobs therefore queue and run in submission
    order.  (The Sizing optimizer parallelizes *inside* its own job, where
    it controls the scratch layout.)

    Everything a job prints — including the skills' own progress output —
    is captured and re-emitted as `log_line` on the GUI thread.
    """

    job_started = Signal(str, str)      # job_id, label
    log_line = Signal(str)
    job_finished = Signal(str, object)  # job_id, result
    job_failed = Signal(str, str)       # job_id, error text
    queue_size = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue[Job | None] = queue.Queue()

    def submit(self, job: Job) -> str:
        """Queue a job and return its id.  Safe from the GUI thread."""
        self._queue.put(job)
        self.queue_size.emit(self._queue.qsize())
        return job.job_id

    def stop(self):
        """Request shutdown: drop jobs that have not started, then signal.

        Without the drain, every queued simulation would still run before the
        sentinel is seen, and closeEvent's bounded wait() would tear down the
        QThread mid-job.
        """
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put(None)

    def run(self):
        """The worker loop.  Do not call — QThread.start() does.

        Each job runs with stdout/stderr redirected into the log signal and
        every exception caught, so one failing job can never take the loop
        down and strand a tab with its buttons disabled.
        """
        while True:
            job = self._queue.get()
            if job is None:
                break
            self.queue_size.emit(self._queue.qsize())
            self.job_started.emit(job.job_id, job.label)
            stream = EmittingStream(self.log_line.emit)
            try:
                with redirect_stdout(stream), redirect_stderr(stream):
                    result = job.fn()
                stream.flush()
                self.job_finished.emit(job.job_id, result)
            # BaseException: a job calling sys.exit() must not kill the
            # worker loop (that would leave the submitting tab's buttons
            # disabled forever)
            except BaseException:
                stream.flush()
                err = traceback.format_exc()
                if job.log_dir is not None:
                    err += _tail_newest_log(job.log_dir)
                self.job_failed.emit(job.job_id, err)
