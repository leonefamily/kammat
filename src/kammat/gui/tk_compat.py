"""Runtime compatibility for the declared PySimpleGUI 4/Tcl 9 combination."""

from queue import Queue
from threading import Lock
from typing import Any


def _toolkit_major(toolkit: Any) -> int:
    raw = str(getattr(toolkit, "__version__", ""))
    try:
        return int(raw.split(".", 1)[0])
    except (TypeError, ValueError):
        return 0


def ensure_pysimplegui_tcl_compat(toolkit: Any) -> bool:
    """Install the narrow PySimpleGUI 4 thread-queue fix required by Tcl 9.

    PySimpleGUI 4 creates its thread-event ``StringVar`` with the legacy
    ``trace('w', ...)`` API removed by Tcl 9.  Replace only that toolkit
    method, in memory, with the equivalent supported ``trace_add`` call.
    Tcl 8 and newer PySimpleGUI releases are left untouched.
    """

    if getattr(toolkit, "__name__", None) != "PySimpleGUI":
        return False
    tk_module = getattr(toolkit, "tk", None)
    window_type = getattr(toolkit, "Window", None)
    if (
        tk_module is None
        or window_type is None
        or float(getattr(tk_module, "TclVersion", 0)) < 9.0
        or _toolkit_major(toolkit) >= 5
    ):
        return False
    current = getattr(window_type, "_create_thread_queue", None)
    if current is None:
        raise RuntimeError("PySimpleGUI thread queue hook is unavailable")
    if getattr(current, "_kammat_tcl9_compat", False):
        return False

    def create_thread_queue_tcl9(self: Any) -> None:
        if self.thread_queue is None:
            self.thread_queue = Queue()
        if self.thread_lock is None:
            self.thread_lock = Lock()
        if self.thread_strvar is None:
            self.thread_strvar = tk_module.StringVar()
            self.thread_strvar.trace_add(
                "write", self._window_tkvar_changed_callback
            )

    create_thread_queue_tcl9._kammat_tcl9_compat = True
    window_type._create_thread_queue = create_thread_queue_tcl9
    return True


__all__ = ["ensure_pysimplegui_tcl_compat"]
