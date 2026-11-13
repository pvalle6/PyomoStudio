"""Pyomo Studio main window (PySide6, Windows 11 Fluent 2 style)."""
from __future__ import annotations

import copy
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QMainWindow,
                               QMenu, QMessageBox, QProgressBar, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from .. import codegen
from .. import engine as E
from .. import schedule as SCH
from .. import spec as S
from .pages import (EXAMPLES_DIR, ComponentPage, GuidePage, HomePage, PlanPage, ResultsPage, SchedulePage,
                    SettingsPage, SolvePage, UncertaintyPage)
from .theme import Fonts, Theme, apply_window_effects, mica_supported, palette, stylesheet, system_is_dark
from .widgets import Icons, NavigationView, button, label, tool


class Job(QThread):
    """Runs engine work off the interface thread."""
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.log.emit))
        except (E.EngineError, S.SpecError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # show the cause; the window stays open
            self.failed.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc(limit=8)}")


PAGES = [
    # key, glyph, text, header-before, footer
    ("home", "home", "Home", None, False),
    ("sets", "sets", "Sets", "Model", False),
    ("params", "params", "Parameters", None, False),
    ("variables", "variables", "Variables", None, False),
    ("expressions", "expressions", "Expressions", None, False),
    ("constraints", "constraints", "Constraints", None, False),
    ("objectives", "objectives", "Objectives", None, False),
    ("uncertainty", "uncertainty", "Uncertainty", None, False),
    ("solve", "solve", "Solve", "Run", False),
    ("results", "results", "Results", "Output", False),
    ("schedule", "schedule", "Schedule", None, False),
    ("plan", "plan", "Plan", None, False),
    ("guide", "guide", "User guide", None, True),
    ("settings", "settings", "Settings", None, True),
]


class StudioWindow(QMainWindow):
    def __init__(self, settings: QSettings):
        super().__init__()
        self.settings = settings
        self.spec = S.new_spec()
        self.path: str | None = None
        self.dirty = False
        self.result = None
        self.result_spec = None
        self.analysis = None
        self.schedules: dict = {}
        self.schedule_error = ""
        self.results_stale = False
        self.job: Job | None = None
        self._names: set[str] = set()

        root = QWidget()
        root.setObjectName("Root")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = NavigationView()
        h.addWidget(self.nav)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        h.addLayout(right, 1)

        bar = QWidget()
        bar.setObjectName("CommandBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.setSpacing(4)
        self.title_label = label("", "strong")
        bl.addWidget(self.title_label)
        bl.addStretch(1)
        self.t_new = tool("New", "new", "New model (Ctrl+N)")
        self.t_open = tool("Open", "open", "Open a model (Ctrl+O)")
        self.t_save = tool("Save", "save", "Save (Ctrl+S)")
        self.t_examples = tool("Examples", "folder")
        self.t_examples.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for p in sorted(EXAMPLES_DIR.glob("*.json")):
            act = QAction(p.stem.replace("_", " "), self)
            act.triggered.connect(lambda _=False, pp=p: self.open_model(str(pp)))
            menu.addAction(act)
        self.t_examples.setMenu(menu)
        self.t_validate = tool("Validate", "check", "Find errors (F7)")
        self.b_solve = button("Solve", "solve", accent=True, tip="Solve (F5)")
        self.t_analyze = tool("Analyze", "analyze", "Stochastic analysis: EVPI and VSS (F6)")
        for w in (self.t_new, self.t_open, self.t_save, self.t_examples):
            bl.addWidget(w)
        sep = QFrame()
        sep.setProperty("divider", True)
        sep.setFixedSize(1, 20)
        bl.addWidget(sep)
        for w in (self.t_validate, self.t_analyze, self.b_solve):
            bl.addWidget(w)
        right.addWidget(bar)

        self.content = QFrame()
        self.content.setObjectName("Content")
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        cl.addWidget(self.progress)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(36, 4, 24, 6)
        self.status_label = label("Ready.", "caption")
        foot.addWidget(self.status_label, 1)
        cl.addLayout(foot)
        right.addWidget(self.content, 1)

        self.pages: dict[str, QWidget] = {}
        self.page_index: dict[str, int] = {}
        for key, glyph, text, header, footer in PAGES:
            if header:
                self.nav.add_header(header)
            idx = self.nav.add_item(glyph, text, footer=footer)
            page = self._make_page(key)
            self.stack.addWidget(page)
            self.pages[key] = page
            self.page_index[key] = idx
        self.nav.currentChanged.connect(self._go)

        self.t_new.clicked.connect(self.new_model)
        self.t_open.clicked.connect(lambda: self.open_model())
        self.t_save.clicked.connect(self.save)
        self.t_validate.clicked.connect(self.validate)
        self.b_solve.clicked.connect(self.solve)
        self.t_analyze.clicked.connect(self.analyze)
        for seq, fn in (("Ctrl+N", self.new_model), ("Ctrl+O", lambda: self.open_model()), ("Ctrl+S", self.save),
                        ("Ctrl+Shift+S", self.save_as), ("F5", self.solve), ("F6", self.analyze),
                        ("F7", self.validate), ("Ctrl+E", self.export_script)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(fn)

        self.resize(1360, 880)
        geo = settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.update_title()
        self.nav.set_current(0)

    def _make_page(self, key: str) -> QWidget:
        if key in S.COMPONENT_KINDS:
            return ComponentPage(self, key)
        return {"home": HomePage, "uncertainty": UncertaintyPage, "solve": SolvePage,
                "results": ResultsPage, "schedule": SchedulePage, "plan": PlanPage,
                "guide": GuidePage, "settings": SettingsPage}[key](self)

    # -- navigation -------------------------------------------------------------
    def _go(self, idx: int):
        key = PAGES[idx][0]
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if hasattr(page, "on_show"):
            page.on_show()

    def go_page(self, key: str):
        self.nav.set_current(self.page_index[key])

    # -- state ------------------------------------------------------------------
    def names(self) -> set[str]:
        return self._names

    def mark_dirty(self, results_too: bool = True):
        self.dirty = True
        if results_too and self.result is not None:
            self.results_stale = True
        self._names = set(S.component_names(self.spec))
        self.update_title()

    def update_title(self):
        name = self.spec.get("name") or "Untitled model"
        star = " *" if self.dirty else ""
        self.title_label.setText(f"{name}{star}")
        file = f" - {Path(self.path).name}" if self.path else ""
        self.setWindowTitle(f"{name}{star}{file} - {APP_NAME}")

    def status(self, text: str):
        self.status_label.setText(text)

    def last_dir(self, filename: str = "") -> str:
        d = self.settings.value("last_dir", str(Path.home()))
        return str(Path(d) / filename) if filename else d

    def _remember_dir(self, path: str):
        self.settings.setValue("last_dir", str(Path(path).parent))

    def refresh_current(self):
        page = self.stack.currentWidget()
        if hasattr(page, "on_show"):
            page.on_show()

    # -- files ------------------------------------------------------------------
    def maybe_save(self) -> bool:
        if not self.dirty:
            return True
        ans = QMessageBox.question(self, APP_NAME, "Save the changes to the model?",
                                   QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                   | QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Cancel:
            return False
        if ans == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def set_spec(self, spec: dict, path: str | None):
        self.spec = spec
        self.path = path
        self.dirty = False
        self.result = None
        self.result_spec = None
        self.analysis = None
        self.schedules = {}
        self.results_stale = False
        self._names = set(S.component_names(spec))
        self.update_title()
        self.pages["results"].info.hide()
        self.pages["schedule"].load()
        self.pages["plan"].load()
        self.refresh_current()

    def new_model(self):
        if self.maybe_save():
            self.set_spec(S.new_spec(), None)
            self.go_page("home")

    def open_model(self, path: str | None = None):
        if not self.maybe_save():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Open model", self.last_dir(),
                                                  "Pyomo Studio model (*.json);;All files (*)")
            if not path:
                return
        try:
            spec = S.load_spec(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, f"The program cannot open the file.\n\n{exc}")
            return
        is_example = Path(path).resolve().parent == EXAMPLES_DIR.resolve()
        self.set_spec(spec, None if is_example else path)
        if not is_example:
            self._remember_dir(path)
        self.status(f"Opened {Path(path).name}." + (" This is an example: Save makes a copy." if is_example else ""))
        self.go_page("home")

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            S.save_spec(self.spec, self.path)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"The program cannot save the file.\n\n{exc}")
            return False
        self.dirty = False
        self.update_title()
        self.status(f"Saved {Path(self.path).name}.")
        return True

    def save_as(self) -> bool:
        stem = (self.spec.get("name") or "model").replace(" ", "_")[:40]
        path, _ = QFileDialog.getSaveFileName(self, "Save model", self.last_dir(f"{stem}.json"),
                                              "Pyomo Studio model (*.json)")
        if not path:
            return False
        self.path = path
        self._remember_dir(path)
        return self.save()

    # -- engine work ---------------------------------------------------------------
    def _start(self, fn, on_done, busy_text: str):
        if self.job is not None and self.job.isRunning():
            self.status("A job is running. Wait until it stops.")
            return
        solve_page = self.pages["solve"]
        solve_page.set_busy(True)
        self.b_solve.setEnabled(False)
        self.t_analyze.setEnabled(False)
        self.progress.show()
        self.status(busy_text)
        self.job = Job(fn, self)
        self.job.log.connect(solve_page.append_log)
        self.job.done.connect(on_done)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._finished)
        self.job.start()

    def _finished(self):
        self.pages["solve"].set_busy(False)
        self.b_solve.setEnabled(True)
        self.t_analyze.setEnabled(True)
        self.progress.hide()

    def _failed(self, text: str):
        self.pages["solve"].info.show_message("critical", "Error", text)
        self.pages["solve"].append_log("ERROR: " + text)
        self.status("Stopped with an error.")
        self.go_page("solve")

    def _check(self) -> bool:
        rep = S.validate(self.spec)
        page = self.pages["solve"]
        if not rep.ok:
            page.info.show_message("critical", f"{len(rep.errors)} error(s)",
                                   "\n".join(f"{i.where}: {i.message}" for i in rep.errors[:12]))
            self.go_page("solve")
            return False
        warns = [i for i in rep.issues if i.level == "warning"]
        if warns:
            page.info.show_message("caution", "Warning", "\n".join(f"{i.where}: {i.message}" for i in warns))
        else:
            page.info.hide()
        return True

    def validate(self):
        if self._check():
            self.pages["solve"].info.show_message("success", "No errors", "The model is ready to solve.")
            self.go_page("solve")

    def build_only(self):
        if not self._check():
            return
        snap = copy.deepcopy(self.spec)

        def work(log):
            stats, text = E.build_summary(snap)
            log(text)
            return stats

        def done(stats):
            self.pages["solve"].info.show_message(
                "success", "Built", f"{stats['class']}: {stats['variables']:,} variables ({stats['binary']:,} binary, "
                f"{stats['integer']:,} integer), {stats['constraints']:,} constraints.")
            self.status("Model built.")
        self._start(work, done, "Building the model ...")

    def solve(self):
        if not self._check():
            return
        snap = copy.deepcopy(self.spec)
        self.pages["solve"].append_log(f"--- Solve {snap.get('name')} ---")
        self.go_page("solve")
        self._start(lambda log: E.solve(snap, None, log), lambda res: self.set_result(res, None, snap),
                    "Solving ...")

    def analyze(self):
        if not self.spec["stochastic"].get("enabled"):
            self.pages["solve"].info.show_message("info", "Stochastic analysis",
                                                  "Turn on the stochastic model on the Uncertainty page first.")
            self.go_page("solve")
            return
        if not self._check():
            return
        snap = copy.deepcopy(self.spec)
        self.pages["solve"].append_log(f"--- Stochastic analysis {snap.get('name')} ---")
        self.go_page("solve")
        self._start(lambda log: E.stochastic_analysis(snap, None, log),
                    lambda a: self.set_result(a["rp_result"], a, snap), "Stochastic analysis ...")

    def set_result(self, res, analysis, snap):
        self.result = res
        self.analysis = analysis
        self.result_spec = snap
        self.results_stale = False
        self.recompute_schedules(go=False)
        self.pages["results"].load(res, analysis)
        if res.ok:
            self.pages["solve"].info.show_message("success" if res.termination in ("optimal", "globallyOptimal")
                                                  else "caution", "Solved", res.message)
            self.status(f"{res.message}  {res.objective_name} = {res.objective:.6g}")
            self.go_page("schedule" if self.schedules else "results")
        else:
            self.pages["solve"].info.show_message("critical", "No solution", res.message)
            self.status(res.message)
            self.go_page("results")

    def recompute_schedules(self, go: bool = True):
        self.schedules = {}
        self.schedule_error = ""
        res = self.result
        if res is not None and res.ok:
            spec = copy.deepcopy(self.result_spec or self.spec)
            spec["schedule"] = copy.deepcopy(self.spec["schedule"])
            for sc in res.scenarios:
                try:
                    sched = SCH.compute_schedule(spec, res.built, sc.name)
                except SCH.ScheduleError as exc:
                    self.schedule_error = str(exc)
                    sched = None
                if sched is not None:
                    self.schedules[sc.name] = sched
        self.pages["schedule"].load()
        self.pages["plan"].load()
        if go:
            self.go_page("schedule")

    def detect_solvers(self):
        def done(found):
            ok = [n for n, v in found.items() if v]
            self.pages["solve"].found.setText("Installed: " + (", ".join(ok) if ok else
                                              "none. Install HiGHS with: pip install highspy"))
            self.status("Solver search done.")
        self._start(lambda log: E.detect_solvers(), done, "Finding solvers ...")

    # -- export ------------------------------------------------------------------
    def export_script(self):
        rep = S.validate(self.spec)
        if not rep.ok:
            self._check()
            return
        stem = (self.spec.get("name") or "model").split(" - ")[0].replace(" ", "_").lower()[:40]
        path, _ = QFileDialog.getSaveFileName(self, "Export Pyomo script", self.last_dir(f"{stem}.py"),
                                              "Python script (*.py)")
        if not path:
            return
        try:
            Path(path).write_text(codegen.generate(self.spec, Path(path).name), encoding="utf-8")
        except (S.SpecError, OSError) as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))
            return
        self.status(f"Pyomo script written to {Path(path).name}.")

    def write_model_file(self):
        if not self._check():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Write model file", self.last_dir("model.lp"),
                                              "LP file (*.lp);;MPS file (*.mps);;AMPL NL file (*.nl);;GAMS file (*.gms)")
        if not path:
            return
        snap = copy.deepcopy(self.spec)
        self._start(lambda log: E.write_model_file(snap, path),
                    lambda _r: self.status(f"Model written to {Path(path).name}."), "Writing the model file ...")

    def export_values_csv(self):
        from .. import report as R
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export values", self.last_dir("values.csv"), "CSV (*.csv)")
        if path:
            Path(path).write_text(R.values_csv(self.result_spec or self.spec, self.result), encoding="utf-8")

    def export_results_json(self):
        from .. import report as R
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", self.last_dir("results.json"), "JSON (*.json)")
        if path:
            Path(path).write_text(R.result_json(self.result, self.schedules), encoding="utf-8")

    # -- appearance ----------------------------------------------------------------
    def set_theme(self, pref: str):
        self.settings.setValue("theme", pref)
        apply_theme(QApplication.instance(), self)

    def set_mica(self, on: bool):
        self.settings.setValue("mica", on)
        self.status("Restart the program to apply the Mica setting.")

    def closeEvent(self, e):
        if self.job is not None and self.job.isRunning():
            if QMessageBox.question(self, APP_NAME, "A solve is running. Close the program?") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()


def resolve_mode(settings: QSettings) -> str:
    pref = settings.value("theme", "system")
    if pref == "system":
        return "dark" if system_is_dark() else "light"
    return "dark" if pref == "dark" else "light"


def apply_theme(app: QApplication, win: StudioWindow | None = None) -> None:
    settings = win.settings if win else QSettings()
    Theme.set_mode(resolve_mode(settings))
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())
    Icons.refresh()
    if win is not None:
        apply_window_effects(win, Theme.mode == "dark", Theme.mica)
        for page in win.pages.values():
            for bar in page.findChildren(QWidget):
                if hasattr(bar, "refresh_theme"):
                    bar.refresh_theme()
                if hasattr(bar, "hl"):
                    bar.hl.rehighlight()
        win.update()


def run(path: str | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PyomoStudio")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    Fonts.discover()
    settings = QSettings()
    want_mica = settings.value("mica", True, type=bool) and mica_supported()
    Theme.mica = want_mica
    Theme.set_mode(resolve_mode(settings))
    app.setFont(_app_font())
    win = StudioWindow(settings)
    if want_mica:
        win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        win.winId()  # make the native window now, before the backdrop is set
        Theme.mica = apply_window_effects(win, Theme.mode == "dark", True)
    apply_theme(app, win)
    try:  # follow the Windows light/dark setting while the program runs
        app.styleHints().colorSchemeChanged.connect(
            lambda _s: apply_theme(app, win) if settings.value("theme", "system") == "system" else None)
    except AttributeError:
        pass
    win.show()
    if path:
        QTimer.singleShot(0, lambda: win.open_model(path))
    return app.exec()


def _app_font():
    from .theme import font
    return font(14)


