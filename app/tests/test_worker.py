"""Unit tests for SimWorker and EmittingStream (run offscreen)."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from app.core.worker import EmittingStream, Job, SimWorker


@pytest.fixture(scope='module')
def qapp():
    # QApplication, not QCoreApplication — see test_examples.py: the first
    # app created wins for the whole pytest process and must support widgets
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _spin_until(condition, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)

    def check():
        if condition():
            loop.quit()
    timer.timeout.connect(check)
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert condition(), 'timed out waiting for condition'


def test_emitting_stream_lines():
    lines = []
    s = EmittingStream(lines.append)
    s.write('hello ')
    s.write('world\npartial')
    assert lines == ['hello world']
    s.flush()
    assert lines == ['hello world', 'partial']


def test_worker_success_and_log(qapp):
    worker = SimWorker()
    worker.start()
    logs, finished = [], []
    worker.log_line.connect(logs.append)
    worker.job_finished.connect(lambda jid, res: finished.append((jid, res)))

    def fn():
        print('progress 1 of 2')
        print('progress 2 of 2')
        return 42

    jid = worker.submit(Job(kind='test', fn=fn, label='ok-job'))
    _spin_until(lambda: finished)
    assert finished[0] == (jid, 42)
    assert 'progress 1 of 2' in logs
    worker.stop()
    worker.wait(3000)


def test_worker_failure(qapp):
    worker = SimWorker()
    worker.start()
    failed = []
    worker.job_failed.connect(lambda jid, err: failed.append((jid, err)))

    def fn():
        raise RuntimeError('boom')

    jid = worker.submit(Job(kind='test', fn=fn, label='bad-job'))
    _spin_until(lambda: failed)
    assert failed[0][0] == jid
    assert 'boom' in failed[0][1]
    worker.stop()
    worker.wait(3000)
