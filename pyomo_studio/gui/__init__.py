"""Desktop interface.

Pyomo must be imported before PySide6. Shiboken (PySide6) installs an import
hook that calls ``inspect.getsource`` on modules imported after it; on Pyomo's
deferred-import placeholders for missing optional packages (matplotlib,
networkx, ...) that raises ``DeferredImportError`` and ``import pyomo.environ``
fails, so every build and solve in the interface would report that Pyomo is
not installed. Loading the engine here, before ``gui.app`` imports Qt, avoids it.
"""
from .. import engine as _engine  # noqa: F401  (import order matters, see above)
