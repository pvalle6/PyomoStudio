"""Windows 11 Fluent 2 theme for Qt: tokens, style sheet, fonts, icons, Mica.

* Light and dark token sets follow the WinUI 3 / Fluent 2 color ramps.
* Corner radii: 8 px for the window, the content layer and flyouts;
  4 px for controls (buttons, fields, lists, cards).
* Type ramp: Segoe UI Variable (Caption 12, Body 14, Subtitle 20, Title 28).
* Icons come from the Segoe Fluent Icons font, the Windows 11 font of the
  Fluent System Icons. On older systems Segoe MDL2 Assets is used.
* Mica uses the DWM system backdrop (Windows 11 22H2 and later). On other
  systems the solid Mica fallback color is used.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter,
                           QPalette, QPen, QPixmap)

RADIUS_WINDOW = 8
RADIUS_CONTROL = 4

TOKENS = {
    "light": {
        "base": "#F3F3F3", "layer": "rgba(255,255,255,128)", "layer_solid": "#F9F9F9",
        "card": "rgba(255,255,255,179)", "card_solid": "#FBFBFB", "flyout": "#F9F9F9",
        "stroke_card": "rgba(0,0,0,15)", "stroke_ctrl": "rgba(0,0,0,15)",
        "stroke_ctrl_bottom": "rgba(0,0,0,41)", "stroke_strong": "rgba(0,0,0,114)",
        "stroke_divider": "rgba(0,0,0,20)", "stroke_flyout": "rgba(0,0,0,26)",
        "ctrl": "rgba(255,255,255,179)", "ctrl_hover": "rgba(249,249,249,128)",
        "ctrl_pressed": "rgba(249,249,249,77)", "input": "rgba(255,255,255,179)",
        "input_focus": "#FFFFFF", "subtle_hover": "rgba(0,0,0,10)", "subtle_pressed": "rgba(0,0,0,6)",
        "subtle_selected": "rgba(0,0,0,15)",
        "text": "#1B1B1B", "text2": "rgba(0,0,0,155)", "text3": "rgba(0,0,0,114)",
        "text_disabled": "rgba(0,0,0,92)",
        "accent": "#005FB8", "accent_hover": "rgba(0,95,184,230)", "accent_pressed": "rgba(0,95,184,204)",
        "on_accent": "#FFFFFF", "accent_text": "#003E92", "selection": "rgba(0,95,184,46)",
        "success": "#0F7B0F", "success_bg": "#DFF6DD", "caution": "#9D5D00", "caution_bg": "#FFF4CE",
        "critical": "#C42B1C", "critical_bg": "#FDE7E9", "info": "#005FB8", "info_bg": "#F6F6F6",
        "scroll": "rgba(0,0,0,114)",
    },
    "dark": {
        "base": "#202020", "layer": "rgba(58,58,58,77)", "layer_solid": "#272727",
        "card": "rgba(255,255,255,13)", "card_solid": "#2B2B2B", "flyout": "#2C2C2C",
        "stroke_card": "rgba(0,0,0,26)", "stroke_ctrl": "rgba(255,255,255,18)",
        "stroke_ctrl_bottom": "rgba(255,255,255,12)", "stroke_strong": "rgba(255,255,255,139)",
        "stroke_divider": "rgba(255,255,255,21)", "stroke_flyout": "rgba(0,0,0,51)",
        "ctrl": "rgba(255,255,255,15)", "ctrl_hover": "rgba(255,255,255,21)",
        "ctrl_pressed": "rgba(255,255,255,8)", "input": "rgba(255,255,255,15)",
        "input_focus": "rgba(30,30,30,179)", "subtle_hover": "rgba(255,255,255,15)",
        "subtle_pressed": "rgba(255,255,255,10)", "subtle_selected": "rgba(255,255,255,15)",
        "text": "#FFFFFF", "text2": "rgba(255,255,255,200)", "text3": "rgba(255,255,255,139)",
        "text_disabled": "rgba(255,255,255,93)",
        "accent": "#60CDFF", "accent_hover": "rgba(96,205,255,230)", "accent_pressed": "rgba(96,205,255,204)",
        "on_accent": "#000000", "accent_text": "#99EBFF", "selection": "rgba(96,205,255,56)",
        "success": "#6CCB5F", "success_bg": "#393D1B", "caution": "#FCE100", "caution_bg": "#433519",
        "critical": "#FF99A4", "critical_bg": "#442726", "info": "#60CDFF", "info_bg": "#2B2B2B",
        "scroll": "rgba(255,255,255,139)",
    },
}

# Segoe Fluent Icons code points (the same points exist in Segoe MDL2 Assets).
GLYPH = {
    "nav": "", "home": "", "sets": "", "params": "", "variables": "",
    "expressions": "", "constraints": "", "objectives": "", "uncertainty": "",
    "view": "", "solve": "", "results": "", "schedule": "", "plan": "",
    "guide": "", "settings": "", "new": "", "open": "", "save": "",
    "add": "", "delete": "", "copy": "", "up": "", "down": "",
    "check": "", "analyze": "", "import": "", "export": "",
    "refresh": "", "warning": "", "error": "", "success": "",
    "info": "", "theme": "", "zoom_in": "", "zoom_out": "",
    "globe": "", "chevron_down": "", "close": "", "folder": "",
    "code": "", "search": "",
}

#: Plain Unicode stand-ins for systems without Segoe Fluent Icons (macOS, Linux).
FALLBACK_GLYPH = {
    "nav": "\u2630", "home": "\u2302", "sets": "\u2208", "params": "\u03b8", "variables": "x",
    "expressions": "\u0192", "constraints": "\u2264", "objectives": "\u25ce", "uncertainty": "\u2248",
    "view": "\u25eb", "solve": "\u25b6", "results": "\u25a4", "schedule": "\u25a5", "plan": "\u2261",
    "guide": "?", "settings": "\u2699", "new": "\u25a1", "open": "\u2197", "save": "\u21e9",
    "add": "+", "delete": "\u2715", "copy": "\u29c9", "up": "\u2191", "down": "\u2193",
    "check": "\u2713", "analyze": "\u2211", "import": "\u21e4", "export": "\u21e5",
    "refresh": "\u21bb", "warning": "!", "error": "\u2715", "success": "\u2713",
    "info": "i", "theme": "\u25d0", "zoom_in": "+", "zoom_out": "\u2212",
    "globe": "\u25cd", "chevron_down": "\u2304", "close": "\u2715", "folder": "\u25b8",
    "code": "{}", "search": "\u2315",
}


class Fonts:
    text = "Segoe UI"
    display = "Segoe UI"
    mono = "Consolas"
    icons: str | None = None

    @classmethod
    def discover(cls) -> None:
        fams = set(QFontDatabase.families())

        def pick(cands, default):
            for c in cands:
                if c in fams:
                    return c
            return default
        cls.text = pick(["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter",
                         "Noto Sans", "DejaVu Sans"], QGuiApplication.font().family())
        cls.display = pick(["Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI", cls.text], cls.text)
        cls.mono = pick(["Cascadia Code", "Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                         "Courier New"], "monospace")
        cls.icons = pick(["Segoe Fluent Icons", "Segoe MDL2 Assets"], None)


def font(size: int = 14, weight: int = 400, display: bool = False) -> QFont:
    f = QFont(Fonts.display if display else Fonts.text)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


def mono_font(size: int = 13) -> QFont:
    f = QFont(Fonts.mono)
    f.setPixelSize(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def qcolor(token: str) -> QColor:
    """Parse '#RRGGBB' or 'rgba(r,g,b,a)' (a 0-255)."""
    token = token.strip()
    if token.startswith("rgba"):
        r, g, b, a = (int(float(x)) for x in token[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(token)


class Theme:
    """The current theme. ``Theme.t`` holds the tokens of the active mode."""
    mode = "light"
    t = TOKENS["light"]
    mica = False
    _icon_cache: dict = {}
    _asset_dir = os.path.join(tempfile.gettempdir(), "pyomo_studio_theme")

    @classmethod
    def set_mode(cls, mode: str) -> None:
        cls.mode = mode
        cls.t = TOKENS[mode]
        cls._icon_cache.clear()

    @classmethod
    def c(cls, name: str) -> QColor:
        return qcolor(cls.t[name])


def system_is_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False
    return False


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

def glyph_pixmap(name: str, color: QColor, px: int = 16, dpr: float = 2.0) -> QPixmap:
    glyph = GLYPH.get(name, name)
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(color)
    if Fonts.icons:
        f = QFont(Fonts.icons)
        f.setPixelSize(px)
        p.setFont(f)
        p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, glyph)
    else:  # no icon font (macOS, Linux): a Unicode symbol from the text font
        text = FALLBACK_GLYPH.get(name, "\u2022")
        f = QFont(Fonts.text)
        f.setPixelSize(int(px * (0.8 if len(text) > 1 else 1.0)))
        f.setWeight(QFont.Weight.DemiBold if text.isascii() else QFont.Weight.Normal)
        p.setFont(f)
        p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


def icon(name: str, color_token: str = "text", px: int = 16) -> QIcon:
    key = (name, color_token, px, Theme.mode)
    if key not in Theme._icon_cache:
        ic = QIcon()
        ic.addPixmap(glyph_pixmap(name, Theme.c(color_token), px), QIcon.Mode.Normal)
        ic.addPixmap(glyph_pixmap(name, Theme.c("text_disabled"), px), QIcon.Mode.Disabled)
        Theme._icon_cache[key] = ic
    return Theme._icon_cache[key]


def _asset(name: str, painter_fn, size: int = 16) -> str:
    """Write a small PNG used by the style sheet (check marks, chevrons)."""
    os.makedirs(Theme._asset_dir, exist_ok=True)
    path = os.path.join(Theme._asset_dir, f"{name}_{Theme.mode}.png")
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter_fn(p, size)
    p.end()
    pm.save(path)
    return path.replace("\\", "/")


def _chevron(color: QColor):
    def fn(p: QPainter, s: int):
        p.setPen(QPen(color, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([_pt(s * 0.3, s * 0.4), _pt(s * 0.5, s * 0.6), _pt(s * 0.7, s * 0.4)])
    return fn


def _check(color: QColor):
    def fn(p: QPainter, s: int):
        p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([_pt(s * 0.25, s * 0.52), _pt(s * 0.43, s * 0.70), _pt(s * 0.76, s * 0.32)])
    return fn


def _pt(x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


# ---------------------------------------------------------------------------
# Style sheet
# ---------------------------------------------------------------------------

def stylesheet() -> str:
    t = Theme.t
    chev = _asset("chevron", _chevron(Theme.c("text2")))
    chk = _asset("check", _check(Theme.c("on_accent")))
    window_bg = "transparent" if Theme.mica else t["base"]
    return f"""
* {{ font-family: "{Fonts.text}"; font-size: 14px; color: {t['text']}; outline: 0; }}
QMainWindow, #Root {{ background: {window_bg}; }}
QWidget#NavRail, QWidget#CommandBar {{ background: transparent; }}
QFrame#Content {{ background: {t['layer']}; border: 1px solid {t['stroke_card']};
  border-top-left-radius: {RADIUS_WINDOW}px; border-right: 0; border-bottom: 0; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget#PageBody {{ background: transparent; border: 0; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-family: "{Fonts.display}"; font-size: 28px; font-weight: 600; }}
QLabel[role="subtitle"] {{ font-family: "{Fonts.display}"; font-size: 20px; font-weight: 600; }}
QLabel[role="strong"] {{ font-weight: 600; }}
QLabel[role="caption"] {{ font-size: 12px; color: {t['text2']}; }}
QLabel[role="secondary"] {{ color: {t['text2']}; }}
QLabel[role="error"] {{ font-size: 12px; color: {t['critical']}; }}
QLabel[role="metric"] {{ font-family: "{Fonts.display}"; font-size: 20px; font-weight: 600; }}
QFrame[card="true"] {{ background: {t['card']}; border: 1px solid {t['stroke_card']};
  border-radius: {RADIUS_CONTROL}px; }}
QFrame[infobar="success"] {{ background: {t['success_bg']}; border: 1px solid {t['stroke_card']}; border-radius: {RADIUS_CONTROL}px; }}
QFrame[infobar="caution"] {{ background: {t['caution_bg']}; border: 1px solid {t['stroke_card']}; border-radius: {RADIUS_CONTROL}px; }}
QFrame[infobar="critical"] {{ background: {t['critical_bg']}; border: 1px solid {t['stroke_card']}; border-radius: {RADIUS_CONTROL}px; }}
QFrame[infobar="info"] {{ background: {t['info_bg']}; border: 1px solid {t['stroke_card']}; border-radius: {RADIUS_CONTROL}px; }}
QFrame[divider="true"] {{ background: {t['stroke_divider']}; border: 0; max-height: 1px; min-height: 1px; }}

QPushButton {{ background: {t['ctrl']}; border: 1px solid {t['stroke_ctrl']};
  border-bottom-color: {t['stroke_ctrl_bottom']}; border-radius: {RADIUS_CONTROL}px;
  padding: 5px 12px; min-height: 20px; }}
QPushButton:hover {{ background: {t['ctrl_hover']}; }}
QPushButton:pressed {{ background: {t['ctrl_pressed']}; color: {t['text2']}; border-bottom-color: {t['stroke_ctrl']}; }}
QPushButton:disabled {{ color: {t['text_disabled']}; background: {t['ctrl_pressed']}; }}
QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['on_accent']};
  border: 1px solid {t['accent']}; }}
QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[accent="true"]:pressed {{ background: {t['accent_pressed']}; }}
QPushButton[accent="true"]:disabled {{ background: {t['stroke_strong']}; border-color: transparent; color: {t['on_accent']}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {RADIUS_CONTROL}px;
  padding: 5px 8px; }}
QToolButton:hover {{ background: {t['subtle_hover']}; }}
QToolButton:pressed {{ background: {t['subtle_pressed']}; color: {t['text2']}; }}
QToolButton:checked {{ background: {t['subtle_selected']}; }}
QToolButton:disabled {{ color: {t['text_disabled']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {{
  background: {t['input']}; border: 1px solid {t['stroke_ctrl']}; border-bottom: 1px solid {t['stroke_strong']};
  border-radius: {RADIUS_CONTROL}px; padding: 5px 10px; selection-background-color: {t['accent']};
  selection-color: {t['on_accent']}; }}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QDateTimeEdit:hover {{
  background: {t['ctrl_hover']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateTimeEdit:focus {{
  background: {t['input_focus']}; border-bottom: 2px solid {t['accent']}; padding-bottom: 4px; }}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{ color: {t['text_disabled']}; }}
QPlainTextEdit[code="true"], QTextEdit[code="true"] {{ font-family: "{Fonts.mono}"; font-size: 13px; }}
QTextBrowser {{ background: {t['card']}; border: 1px solid {t['stroke_card']}; border-radius: {RADIUS_CONTROL}px; padding: 8px 12px; }}
QComboBox::drop-down {{ border: 0; width: 28px; }}
QComboBox::down-arrow {{ image: url("{chev}"); width: 16px; height: 16px; }}
QComboBox QAbstractItemView {{ background: {t['flyout']}; border: 1px solid {t['stroke_flyout']};
  border-radius: {RADIUS_WINDOW}px; padding: 4px; selection-background-color: {t['subtle_hover']};
  selection-color: {t['text']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
  width: 0; border: 0; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: {RADIUS_CONTROL}px;
  border: 1px solid {t['stroke_strong']}; background: {t['ctrl']}; }}
QCheckBox::indicator:hover {{ background: {t['ctrl_hover']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url("{chk}"); }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid {t['stroke_strong']};
  background: {t['ctrl']}; }}
QRadioButton::indicator:checked {{ width: 8px; height: 8px; border: 5px solid {t['accent']};
  background: {t['on_accent']}; }}

QListWidget, QTreeWidget, QTableWidget, QTableView {{ background: {t['card']}; border: 1px solid {t['stroke_card']};
  border-radius: {RADIUS_CONTROL}px; padding: 2px; gridline-color: {t['stroke_divider']};
  alternate-background-color: {t['subtle_pressed']}; }}
QListWidget::item {{ border-radius: {RADIUS_CONTROL}px; padding: 7px 10px; margin: 1px 2px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t['subtle_hover']}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableView::item:selected {{
  background: {t['selection']}; color: {t['text']}; }}
QTableView::item {{ padding: 2px 6px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t['text2']}; border: 0;
  border-bottom: 1px solid {t['stroke_divider']}; padding: 6px 10px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: 0; }}

QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; color: {t['text2']}; padding: 8px 14px; border: 0;
  border-bottom: 3px solid transparent; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; font-weight: 600; border-bottom: 3px solid {t['accent']}; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle {{ background: {t['scroll']}; border-radius: 3px; min-height: 24px; min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ margin: 1px; border-radius: 4px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; width: 0; height: 0; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QProgressBar {{ background: {t['stroke_divider']}; border: 0; border-radius: 1px; max-height: 3px; min-height: 3px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 1px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['stroke_strong']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
  background: {t['flyout']}; border: 5px solid {t['accent']}; }}
QToolTip {{ background: {t['flyout']}; color: {t['text']}; border: 1px solid {t['stroke_flyout']};
  border-radius: {RADIUS_CONTROL}px; padding: 6px 8px; }}
QMenu {{ background: {t['flyout']}; border: 1px solid {t['stroke_flyout']}; border-radius: {RADIUS_WINDOW}px; padding: 4px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: {RADIUS_CONTROL}px; background: transparent; }}
QMenu::item:selected {{ background: {t['subtle_hover']}; }}
QMenu::separator {{ height: 1px; background: {t['stroke_divider']}; margin: 4px 8px; }}
QMessageBox, QDialog, QFileDialog {{ background: {t['layer_solid']}; }}
"""


def palette() -> QPalette:
    t = Theme.t
    pal = QPalette()
    solid_text = qcolor(t["text"])
    base = qcolor(t["base"])
    flyout = qcolor(t["flyout"])
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        pal.setColor(group, QPalette.ColorRole.Window, base)
        pal.setColor(group, QPalette.ColorRole.WindowText, solid_text)
        pal.setColor(group, QPalette.ColorRole.Base, flyout)
        pal.setColor(group, QPalette.ColorRole.AlternateBase, base)
        pal.setColor(group, QPalette.ColorRole.Text, solid_text)
        pal.setColor(group, QPalette.ColorRole.Button, flyout)
        pal.setColor(group, QPalette.ColorRole.ButtonText, solid_text)
        pal.setColor(group, QPalette.ColorRole.ToolTipBase, flyout)
        pal.setColor(group, QPalette.ColorRole.ToolTipText, solid_text)
        pal.setColor(group, QPalette.ColorRole.Highlight, qcolor(t["accent"]))
        pal.setColor(group, QPalette.ColorRole.HighlightedText, qcolor(t["on_accent"]))
        pal.setColor(group, QPalette.ColorRole.Link, qcolor(t["accent_text"] if Theme.mode == "light" else t["accent"]))
        pal.setColor(group, QPalette.ColorRole.PlaceholderText, qcolor(t["text3"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, qcolor(t["text_disabled"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, qcolor(t["text_disabled"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, qcolor(t["text_disabled"]))
    return pal


# ---------------------------------------------------------------------------
# Windows 11 window backdrop (Mica), dark title bar, rounded corners
# ---------------------------------------------------------------------------

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_MAINWINDOW = 2   # Mica


def mica_supported() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22621
    except AttributeError:
        return False


def _dwm_set(hwnd: int, attr: int, value: int) -> int:
    val = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                                      ctypes.byref(val), ctypes.sizeof(val))


def apply_window_effects(widget, dark: bool, mica: bool) -> bool:
    """Dark title bar, 8 px rounded corners and Mica. Return True if Mica is on."""
    if sys.platform != "win32":
        return False
    hwnd = int(widget.winId())
    try:
        _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        _dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    except (OSError, AttributeError):
        return False
    if not (mica and mica_supported()):
        return False

    class MARGINS(ctypes.Structure):
        _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                    ("top", ctypes.c_int), ("bottom", ctypes.c_int)]
    try:
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd),
                                                          ctypes.byref(MARGINS(-1, -1, -1, -1)))
        return _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW) == 0
    except (OSError, AttributeError):
        return False


ICON_SIZE = QSize(16, 16)
