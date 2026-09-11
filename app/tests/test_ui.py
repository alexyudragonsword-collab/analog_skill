"""Tests for the GUI layer — the shared job protocol, the main window's
ngspice wiring, and that every tab builds.

Scope is deliberate. What is worth testing here is the plumbing every tab
shares and gets wrong in the same way: which reply belongs to which tab,
what happens to the run buttons when ngspice disappears, whether a failure
reaches the log. Pixel layout and widget geometry are not tested — they
change constantly and break tests without finding bugs.

Everything runs under offscreen Qt (conftest sets QT_QPA_PLATFORM), and no
test here opens a modal dialog: exec() blocks until someone presses OK, and
in CI nobody can.
"""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from app import paths
paths.init_runtime()

from app.core.worker import Job, SimWorker
from app.ui.job_mixin import JobTabMixin, error_summary, fail_text


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def worker(qapp):
    """A real SimWorker that is never start()ed — submit() only queues, so
    the job protocol can be driven by emitting the signals by hand."""
    w = SimWorker()
    yield w
    w.stop()


class _Tab(JobTabMixin):
    """Minimal tab: records what the mixin hands back."""

    def __init__(self, worker):
        self.finished, self.failed = [], []
        self.init_job_runner(worker)

    def on_job_finished(self, slot, result):
        self.finished.append((slot, result))

    def on_job_failed(self, slot, err):
        self.failed.append((slot, err))


def _job(label='x'):
    return Job(kind='test', fn=lambda: None, label=label)


# ── the shared job protocol ──────────────────────────────────────────────────
def test_reply_comes_back_under_the_slot_that_asked(worker):
    """A slot is the tab's name for a kind of work; several can be in
    flight, and each reply has to find its own."""
    tab = _Tab(worker)
    build = tab.submit_job('build', _job())
    check = tab.submit_job('check', _job())
    assert tab.has_job('build') and tab.has_job('check')

    worker.job_finished.emit(check, 'check-result')
    assert tab.finished == [('check', 'check-result')]
    assert not tab.has_job('check')      # done...
    assert tab.has_job('build')          # ...and the other one is untouched

    worker.job_failed.emit(build, 'Traceback\nBoom: no')
    assert tab.failed == [('build', 'Traceback\nBoom: no')]
    assert not tab.has_job('build')


def test_a_tab_ignores_another_tabs_reply(worker):
    """Every tab connects to the same worker signals, so each one sees all
    of them and must drop the ones it did not submit."""
    mine, theirs = _Tab(worker), _Tab(worker)
    job_id = theirs.submit_job('gen', _job())
    worker.job_finished.emit(job_id, 'result')
    assert theirs.finished == [('gen', 'result')] and mine.finished == []

    worker.job_finished.emit('an-id-nobody-submitted', 'result')
    assert mine.finished == [] and len(theirs.finished) == 1


def test_has_job_is_what_guards_a_second_click(worker):
    """The re-entrancy guard every tab writes as `if self.has_job(...)`."""
    tab = _Tab(worker)
    assert not tab.has_job('build')
    job_id = tab.submit_job('build', _job())
    assert tab.has_job('build')
    worker.job_finished.emit(job_id, None)
    assert not tab.has_job('build')      # clicking again is allowed now


def test_failure_text_is_the_cause_not_the_traceback():
    """The blob is already in the log panel; the tab shows one red line."""
    assert error_summary('Traceback ...\nValueError: bad bounds') == \
        'ValueError: bad bounds'
    assert error_summary('   ') == 'failed'
    text = fail_text('Traceback ...\nValueError: bad bounds')
    assert 'ValueError: bad bounds' in text and 'see log panel' in text
    assert 'Traceback' not in text


# ── the main window ──────────────────────────────────────────────────────────
@pytest.fixture(scope='module')
def window(qapp):
    """One MainWindow for the module — building it starts a worker thread
    and constructs all six tabs, which is most of a second."""
    from app.ui.main_window import MainWindow
    win = MainWindow()
    yield win
    win.close()          # closeEvent stops and joins the worker


def test_main_window_builds_every_tab(window):
    from PySide6.QtWidgets import QTabWidget
    tabs = window.centralWidget().findChild(QTabWidget)
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert labels == ['gm/ID Designer', 'ngspice Examples', 'Curve Browser',
                      'Comparison', 'Circuits', 'Sizing']
    assert all(tabs.widget(i) is not None for i in range(tabs.count()))


def test_missing_ngspice_disables_every_tab_and_says_so(window, monkeypatch):
    """The banner, the status button and the run buttons all hang off one
    locate() call — if a tab is left out of that loop it stays clickable
    with no simulator behind it."""
    from app.core import ngspice_locator
    import app.ui.main_window as mw
    tabs = (window.gmid_tab, window.examples_tab, window.browser_tab,
            window.comparison_tab, window.circuits_tab, window.sizing_tab)
    seen = {}
    for tab in tabs:
        monkeypatch.setattr(tab, 'set_sim_enabled',
                            lambda ok, t=tab: seen.__setitem__(t, ok))

    monkeypatch.setattr(mw, 'locate', lambda: ngspice_locator.NgspiceStatus(
        exe=None, version=None))
    window.refresh_ngspice_status()
    assert set(seen.values()) == {False} and len(seen) == len(tabs)
    assert window._banner.isVisibleTo(window)
    assert 'not found' in window._ngspice_btn.text()

    monkeypatch.setattr(mw, 'locate', lambda: ngspice_locator.NgspiceStatus(
        exe='/usr/bin/ngspice', version='ngspice-42'))
    window.refresh_ngspice_status()
    assert set(seen.values()) == {True}
    assert not window._banner.isVisibleTo(window)
    assert 'ngspice-42' in window._ngspice_btn.text()


def test_a_failed_job_reaches_the_log_panel(window):
    """Every line of the traceback, not just the summary — the log panel is
    where the detail is supposed to live, which is why the tabs only show a
    one-liner."""
    window.log_panel.clear()
    window._on_job_failed('some-id', 'Traceback ...\nRuntimeError: boom')
    assert 'failed' in window._job_lbl.text()
    text = window.log_panel.toPlainText()
    assert 'Traceback ...' in text and 'RuntimeError: boom' in text


# ── the settings dialog ──────────────────────────────────────────────────────
def test_settings_dialog_round_trips_the_llm_config(qapp, isolated_settings):
    """What the dialog writes on OK is what get_config() reads back."""
    from app.core import llm_client
    from app.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog()
    dlg._llm_provider.setCurrentIndex(1)             # anthropic
    dlg._llm_base.setText(' https://api.example/v1 ')
    dlg._llm_key.setText('sk-typed-in')
    dlg._llm_model.setText('claude-test')
    dlg._accept()                                    # what OK does
    cfg = llm_client.get_config()
    assert cfg['provider'] == 'anthropic'
    assert cfg['base_url'] == 'https://api.example/v1'   # stripped
    assert cfg['api_key'] == 'sk-typed-in'
    assert cfg['model'] == 'claude-test'


def test_settings_dialog_will_not_save_an_env_supplied_key(qapp, monkeypatch,
                                                           isolated_settings):
    """OK saves every field.  If it saved this one, the key the user put in
    the environment to keep off disk would land on disk anyway."""
    from PySide6.QtCore import QSettings
    from app.core import llm_client
    from app.ui.settings_dialog import SettingsDialog
    monkeypatch.delenv(llm_client.ENV_API_KEY, raising=False)
    llm_client.set_config('openai', '', 'sk-on-disk', 'm')

    monkeypatch.setenv(llm_client.ENV_API_KEY, 'sk-from-env')
    dlg = SettingsDialog()
    assert dlg._llm_key.text() == 'sk-from-env'      # shown...
    assert dlg._llm_key.isReadOnly()                 # ...but not editable
    dlg._accept()
    assert str(QSettings().value(llm_client.KEY_API_KEY, '')) == 'sk-on-disk'


# ── the manual viewer ────────────────────────────────────────────────────────
def test_manual_viewer_shows_both_languages(qapp, isolated_settings):
    """Both manual files must actually be on disk in the resources tree —
    the viewer falls back to a "file missing" page rather than failing, so
    a packaging mistake here is otherwise silent until a user presses F1."""
    from app.ui.manual_dialog import LANGS, ManualDialog
    dlg = ManualDialog()
    for idx, (code, _label, _file) in enumerate(LANGS):
        dlg._lang_combo.setCurrentIndex(idx)         # fires _on_lang
        text = dlg._browser.toPlainText()
        assert 'Manual file missing' not in text, f'{code} manual not shipped'
        assert len(text) > 500
    from PySide6.QtCore import QSettings
    assert str(QSettings().value('manual_lang', '')) == LANGS[-1][0]
