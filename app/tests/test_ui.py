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


# ── what every tab must do with a reply ──────────────────────────────────────
#: (tab attribute, its primary button, job slot, the label a failure lands in)
#: gm/ID reports build failures in the range label rather than a status line.
TABS = [
    ('examples_tab',   'run_btn',   'run',   '_status'),
    ('browser_tab',    'gen_btn',   'gen',   '_status'),
    ('comparison_tab', 'gen_btn',   'gen',   '_status'),
    ('circuits_tab',   'run_btn',   'run',   '_status'),
    ('sizing_tab',     'run_btn',   'opt',   '_status'),
    ('gmid_tab',       'build_btn', 'build', '_range_lbl'),
]


@pytest.mark.parametrize('tab_name, btn, slot, status', TABS,
                         ids=[t[0] for t in TABS])
def test_a_failure_never_leaves_the_button_stuck(window, tab_name, btn, slot,
                                                 status):
    """The failure path re-enables the control the user pressed and says why.
    A tab that forgets is dead until restart — the job is gone, and nothing
    else will ever re-enable the button."""
    tab = getattr(window, tab_name)
    getattr(tab, btn).setEnabled(False)          # as _run() leaves it
    tab.on_job_failed(slot, 'Traceback ...\nRuntimeError: ngspice died')
    assert getattr(tab, btn).isEnabled()
    text = getattr(tab, status).text()
    assert 'RuntimeError: ngspice died' in text
    assert 'Traceback' not in text               # the blob stays in the log


#: Tabs whose result is a render closure run on the GUI thread, and the
#: shape they hand it back in: matplotlib is single-threaded, so the job
#: returns a closure and the tab draws.  A closure that raises must not take
#: the GUI thread with it.
RENDER_TABS = [
    ('examples_tab',   'run_btn', 'run', 'callable'),
    ('browser_tab',    'gen_btn', 'gen', 'callable'),
    ('comparison_tab', 'gen_btn', 'gen', 'callable'),
    ('circuits_tab',   'run_btn', 'run', 'method'),
]


@pytest.mark.parametrize('tab_name, btn, slot, shape', RENDER_TABS,
                         ids=[t[0] for t in RENDER_TABS])
def test_a_render_that_raises_is_reported_not_propagated(window, tab_name,
                                                         btn, slot, shape):
    """on_job_finished draws on the GUI thread, so an exception here is an
    exception inside a Qt slot — reported as red text, never raised."""
    tab = getattr(window, tab_name)

    def boom():
        raise ValueError('no data to plot')

    result = boom if shape == 'callable' else type(
        'R', (), {'render': staticmethod(boom)})()
    getattr(tab, btn).setEnabled(False)
    tab.on_job_finished(slot, result)            # must not raise
    assert getattr(tab, btn).isEnabled()
    assert 'no data to plot' in tab._status.text()


# ── the Sizing tab's round trip ──────────────────────────────────────────────
@pytest.fixture
def fake_run():
    from app.tests.test_sizing import _fake_run
    return _fake_run


def test_sizing_start_from_best_known_point(window, tmp_path, monkeypatch,
                                            fake_run):
    """The checkbox sends the archive's best point under the current
    targets as the search's start; with nothing archived it refuses
    rather than silently searching from the default."""
    from app.core import sizing
    monkeypatch.setattr(sizing.runs, 'runs_dir', lambda: tmp_path)
    tab = window.sizing_tab
    tab.circuit_combo.setCurrentIndex(
        tab.circuit_combo.findData('amp_hoilee_affc'))
    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('diff_evolution'))
    monkeypatch.setattr(sizing, 'archive_best', lambda *a, **k: None)
    monkeypatch.setattr(sizing, 'archive_size', lambda *a, **k: 0)
    tab._refresh_known()
    assert 'no archived' in tab._known_lbl.text()
    jobs = []
    monkeypatch.setattr(tab, 'submit_job', lambda slot, job: jobs.append(job))
    monkeypatch.setattr(tab, 'has_job', lambda slot: False)
    tab.known_chk.setChecked(True)
    tab._run()
    assert not jobs and 'No archived' in tab._status.text()

    point = {v.name: v.default for v in
             sizing.parse_variables('amp_hoilee_affc')}
    monkeypatch.setattr(sizing, 'archive_best', lambda key, names, ov=None:
                        {'cost': 1.2345, 'values': point, 'metrics': {},
                         'n': 7})
    tab._refresh_known()
    assert '7 archived' in tab._known_lbl.text()
    assert '1.2345' in tab._known_lbl.text()
    seen = {}
    monkeypatch.setattr(sizing, 'optimize',
                        lambda key, variables, **kw: seen.update(kw)
                        or fake_run())
    tab._run()
    jobs[-1].fn()
    assert seen['start'] == point
    assert 'best known point' in tab._status.text()
    tab.known_chk.setChecked(False)
    tab._run()
    jobs[-1].fn()
    assert seen['start'] is None


def test_sizing_menu_offers_characterise_and_model_proposals(window):
    """The amortised surrogate is two menu entries behind the existing
    seam: a Sobol characterisation and, with scikit-learn present, the
    models' proposals; both run through the same Optimize button."""
    from app.core import sizing
    tab = window.sizing_tab
    assert tab.algo_combo.findData('sobol') >= 0
    assert (tab.algo_combo.findData('model_propose') >= 0) == \
        sizing.models_available()
    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('sobol'))
    tab._update_estimate()
    if sizing.models_available():
        tab.algo_combo.setCurrentIndex(
            tab.algo_combo.findData('model_propose'))
        tab._update_estimate()
        assert 'proposals verified' in tab._estimate.text()
    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('diff_evolution'))


def test_sizing_run_round_trip(window, tmp_path, monkeypatch, fake_run):
    """Press Run, then hand the tab the reply it would have got: buttons and
    report have to come back consistent, and the run has to be saved."""
    from app.core import sizing
    monkeypatch.setattr(sizing.runs, 'runs_dir', lambda: tmp_path)
    tab = window.sizing_tab
    tab.circuit_combo.setCurrentIndex(
        tab.circuit_combo.findData('amp_hoilee_affc'))

    submitted = []
    monkeypatch.setattr(tab, 'submit_job',
                        lambda slot, job: submitted.append((slot, job.label)))
    tab._run()
    assert submitted and submitted[0][0] == 'opt'
    assert not tab.run_btn.isEnabled() and tab.cancel_btn.isEnabled()

    run = fake_run()
    tab.on_job_finished('opt', run)
    assert tab.run_btn.isEnabled() and not tab.cancel_btn.isEnabled()
    assert '3.400' in tab._status.text() and '1.200' in tab._status.text()
    assert tab.export_btn.isEnabled() and tab.waves_btn.isEnabled()
    assert 'HoiLee' in tab._report.toPlainText()
    assert list(tmp_path.glob('*.json')), 'the run was not saved'


def test_sizing_will_not_start_a_second_run(window, monkeypatch):
    """has_job('opt') is the re-entrancy guard; without it a second click
    queues a duplicate optimization behind the first."""
    tab = window.sizing_tab
    monkeypatch.setattr(tab, 'has_job', lambda slot: slot == 'opt')
    submitted = []
    monkeypatch.setattr(tab, 'submit_job',
                        lambda *a: submitted.append(a))
    tab._run()
    assert submitted == []


# ── the gm/ID tab's two guards ───────────────────────────────────────────────
def test_gmid_discards_a_table_built_for_other_parameters(window):
    """The build runs on the worker while the spin boxes stay live. A table
    for the old W/L must not be installed as if it described the current
    ones — the numbers would be wrong and nothing would say so."""
    tab = window.gmid_tab
    stale = type('T', (), {'model': 'nonesuch', 'W': 1e-6, 'L': 1e-6,
                           'vds': 0.9})()
    tab._tbl = None
    tab.on_job_finished('build', stale)
    assert tab._tbl is None
    assert 'Parameters changed' in tab._range_lbl.text()
    assert not tab.size_btn.isEnabled()


def test_gmid_failed_rebuild_stops_the_old_table_answering(window):
    """A failed rebuild leaves the previous table in memory unless it is
    cleared — and the lookup tools would keep answering from it."""
    tab = window.gmid_tab
    tab._tbl = object()
    tab.size_btn.setEnabled(True)
    tab.lk_btn.setEnabled(True)
    tab.on_job_failed('build', 'Traceback ...\nOSError: no such model')
    assert tab._tbl is None and tab._curves is None
    assert not tab.size_btn.isEnabled() and not tab.lk_btn.isEnabled()
    assert 'OSError: no such model' in tab._range_lbl.text()


# ── the Sizing tab's time estimate ───────────────────────────────────────────
def test_estimate_counts_the_ai_rounds_not_just_the_simulations(window,
                                                                monkeypatch):
    """An LLM round is one model call plus min(workers, 4) evaluations, and
    the call can outlast an evaluation by two orders of magnitude.  Counting
    only ngspice read "2 min" for something closer to an hour."""
    from app.core import llm_client
    monkeypatch.setattr(llm_client, 'round_seconds',
                        lambda cfg=None, effort=None: 100.0)
    tab = window.sizing_tab
    tab.circuit_combo.setCurrentIndex(
        tab.circuit_combo.findData('amp_hoilee_affc'))
    tab.budget_spin.setValue(150)
    tab.workers_spin.setValue(4)

    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('sobol_powell'))
    sims_only = tab._estimate.text()

    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('llm'))
    with_ai = tab._estimate.text()

    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('de_llm_finish'))
    one_call = tab._estimate.text()

    assert 'AI rounds' in with_ai and 'AI rounds' not in sims_only
    assert '38 AI rounds' in with_ai            # ceil(150 / 4)
    assert 'up to 3 AI rounds of 3 calls' in one_call   # not a loop
    minutes = lambda s: int(s.split('≈')[1].split('min')[0].strip())
    assert minutes(with_ai) > minutes(sims_only) * 10


def test_sizing_default_algorithm_is_the_measured_one(monkeypatch):
    """CMA-ES when the package is there, with the finish when a model is
    configured; DE otherwise.  The table behind it is in
    cairn/pitfalls.md — the default is not a preference."""
    pytest.importorskip('cma')
    from app.core import llm_client
    from app.core.worker import SimWorker
    from app.ui.sizing_tab import SizingTab
    worker = SimWorker()
    try:
        monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: False)
        assert SizingTab(worker).algo_combo.currentData() == 'cmaes'
        monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: True)
        assert SizingTab(worker).algo_combo.currentData() == \
            'cmaes_llm_finish'
    finally:
        worker.stop()


def test_sizing_seed_reaches_the_search_and_try_next_applies_the_step(
        window, tmp_path, monkeypatch, fake_run):
    """The seed box is what makes the measured order — seed, budget,
    finish — something a user can follow without editing code; Try-next
    is the order itself, one click per step."""
    from app.core import llm_client, sizing
    monkeypatch.setattr(sizing.runs, 'runs_dir', lambda: tmp_path)
    monkeypatch.setattr(llm_client, 'configured', lambda cfg=None: False)
    tab = window.sizing_tab
    tab.circuit_combo.setCurrentIndex(
        tab.circuit_combo.findData('amp_hoilee_affc'))
    assert tab.seed_spin.value() == 0
    # the module shares one window; an earlier test may have left the
    # AI algorithm selected, which the not-configured guard would refuse
    tab.algo_combo.setCurrentIndex(tab.algo_combo.findData('diff_evolution'))
    assert tab.algo_combo.findData('de_portfolio') < 0     # removed

    jobs = []
    monkeypatch.setattr(tab, 'submit_job', lambda slot, job: jobs.append(job))
    seen = {}
    monkeypatch.setattr(sizing, 'optimize',
                        lambda key, variables, **kw: seen.update(kw)
                        or fake_run())
    tab.seed_spin.setValue(5)
    # the real button: clicked() hands _run a `checked` bool, which once
    # arrived as the run to resume and broke Optimize in the GUI while
    # every test called _run() directly
    tab.run_btn.click()
    jobs[-1].fn()
    assert seen['seed'] == 5 and seen['budget'] == tab.budget_spin.value()
    assert seen['resume'] is None

    # a run that ends far from feasible: the status names the misses and
    # the button offers the next seed
    run = fake_run(cost=1.5)
    run.algo, run.seed, run.budget = 'diff_evolution', 5, 600
    tab.on_job_finished('opt', run)
    assert tab.next_btn.isEnabled()
    assert 'MISSING' in tab._status.text() or 'want' in tab._status.text()
    assert 'Try seed' in tab._status.text()
    assert 'search notes' not in tab._report.toPlainText()

    monkeypatch.setattr(tab, 'has_job', lambda slot: False)
    n = len(jobs)
    tab.next_btn.click()
    assert len(jobs) == n + 1 and tab.seed_spin.value() != 5
    assert not tab.next_btn.isEnabled()          # until that run reports
