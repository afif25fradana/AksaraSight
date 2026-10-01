"""GUI package for AksaraSight desktop application."""

import logging
import threading
import tkinter.font as _tkfont

logger = logging.getLogger(__name__)

_original_font_del = _tkfont.Font.__del__


def _thread_safe_font_del(self: _tkfont.Font) -> None:
    # Only invoke Tcl font deletion from the main thread.
    # When Python cyclic GC sweeps orphaned Font objects on background worker threads
    # (e.g. OCRWorkerThread), calling self._call("font", "delete", self.name) blocks
    # indefinitely on Windows because Tcl is single-threaded and the main thread may be
    # waiting on the worker. The trade-off: orphaned Tcl font names might linger until
    # the Tk root window is destroyed, where all Tcl resources are reclaimed in C anyway.
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        _original_font_del(self)
    except Exception as exc:
        logger.debug("Failed to delete Tk font: %s", exc)


if not getattr(_tkfont.Font.__del__, "_aksara_guarded", False):
    _thread_safe_font_del._aksara_guarded = True  # type: ignore[attr-defined]
    _tkfont.Font.__del__ = _thread_safe_font_del
