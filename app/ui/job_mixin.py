"""Shared job-submission plumbing for tabs driving the SimWorker.

Every tab used to copy the same state machine: a pending job-id field, the
``if job_id != self._pending: return`` guard in both result handlers, and the
same red-error formatting line.  This mixin centralizes it, with named slots
so a tab can run several independent jobs (the gm/ID tab has 'build' and
'check').

Usage:
    class MyTab(QWidget, JobTabMixin):
        def __init__(self, worker):
            ...
            self.init_job_runner(worker)

        def _start(self):
            if self.has_job('gen'):
                return
            self.submit_job('gen', Job(...))

        def on_job_finished(self, slot, result): ...
        def on_job_failed(self, slot, err): ...
"""

from app.core.worker import Job, SimWorker


def error_summary(err: str) -> str:
    """Last line of a worker error blob — the human-readable cause."""
    return err.strip().splitlines()[-1] if err.strip() else 'failed'


def fail_text(err: str) -> str:
    return (f'<font color="red">Failed: {error_summary(err)} '
            f'(see log panel)</font>')


class JobTabMixin:
    def init_job_runner(self, worker: SimWorker):
        self._worker = worker
        self._jobs: dict[str, str] = {}      # job_id -> slot name
        worker.job_finished.connect(self._dispatch_finished)
        worker.job_failed.connect(self._dispatch_failed)

    def has_job(self, slot: str) -> bool:
        return slot in self._jobs.values()

    def submit_job(self, slot: str, job: Job) -> str:
        job_id = self._worker.submit(job)
        self._jobs[job_id] = slot
        return job_id

    # ── worker signal dispatch (filters out other tabs' jobs) ────────────
    def _dispatch_finished(self, job_id: str, result):
        slot = self._jobs.pop(job_id, None)
        if slot is not None:
            self.on_job_finished(slot, result)

    def _dispatch_failed(self, job_id: str, err: str):
        slot = self._jobs.pop(job_id, None)
        if slot is not None:
            self.on_job_failed(slot, err)

    # ── to be implemented by the tab ──────────────────────────────────────
    def on_job_finished(self, slot: str, result):
        raise NotImplementedError

    def on_job_failed(self, slot: str, err: str):
        raise NotImplementedError
