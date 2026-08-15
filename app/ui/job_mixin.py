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
    """The one red one-liner every tab shows on failure.

    Kept in one place so the wording and the "see log panel" pointer stay
    identical across tabs — the full traceback is already in the log.
    """
    return (f'<font color="red">Failed: {error_summary(err)} '
            f'(see log panel)</font>')


class JobTabMixin:
    """Job bookkeeping for one tab: submit by slot, get the reply back.

    A *slot* is the tab's own name for a kind of work ('build', 'check',
    'gen'), not a job id.  It lets one tab keep several independent jobs in
    flight and still know which reply is which, and it makes "is this
    already running?" a question about the slot rather than about a stored
    id.  Replies for jobs this tab did not submit are filtered out, so
    every tab may connect to the same worker signals.
    """

    def init_job_runner(self, worker: SimWorker):
        """Wire this tab to the shared worker.  Call once, in __init__."""
        self._worker = worker
        self._jobs: dict[str, str] = {}      # job_id -> slot name
        worker.job_finished.connect(self._dispatch_finished)
        worker.job_failed.connect(self._dispatch_failed)

    def has_job(self, slot: str) -> bool:
        """Is work of this kind still in flight?  Guard re-entrant clicks."""
        return slot in self._jobs.values()

    def submit_job(self, slot: str, job: Job) -> str:
        """Queue `job` on the worker and remember it under `slot`.

        Returns the job id, which the caller rarely needs — the slot comes
        back with the result.
        """
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
        """Called on the GUI thread with the value the job returned.

        `slot` is what the tab passed to submit_job().  Rendering belongs
        here rather than in the job: matplotlib is not thread-safe, so jobs
        return a render closure and this is where it runs.
        """
        raise NotImplementedError

    def on_job_failed(self, slot: str, err: str):
        """Called on the GUI thread when the job raised.

        `err` is the formatted traceback; show fail_text(err), not the blob
        — the full text is already in the log panel.
        """
        raise NotImplementedError
