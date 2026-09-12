"""GUI Application shell and background worker thread for OCR-LLM-Local."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import queue
import sys
import threading
import traceback
from typing import Any, Optional, Union

import customtkinter as ctk
import tkinterdnd2 as tkdnd
import tkinterdnd2.TkinterDnD as tdnd

from config.settings import Settings
from core.engine import OCREngine
from core.formatter import format_output, save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat


class WorkerEventType(str, Enum):
    """Event types posted from the background worker thread to the main UI thread."""
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WORKER_CRASHED = "WORKER_CRASHED"


@dataclass
class WorkerEvent:
    """Structured event emitted by the worker thread across the result queue."""
    event_type: WorkerEventType
    file_path: str
    result: Optional[OCRResult] = None
    error: Optional[str] = None


def _init_tkinterdnd(tkroot: Any) -> str:
    """Initialize TkinterDnD with forward-slash normalized auto_path for Windows/Tcl 9 compatibility.

    WHY THIS NORMALIZATION IS REQUIRED:
    On Windows (specifically Python 3.14 with Tcl 9), standard Windows backslash paths
    (e.g. 'C:\\Users\\...') contain backslash escape sequences like '\\U'. In Tcl 9, '\\U'
    is parsed as a Unicode escape sequence ('\\UXXXXXXXX'). When TkinterDnD's internal
    pkgIndex.tcl evaluates "tkdnd::source {$dir/tkdnd.tcl}", unescaped backslashes in $dir
    corrupt the interpolated path string, causing Tcl package loading to fail intermittently
    with 'couldn't read file ".../tkdnd.tcl": no such file or directory'.
    Normalizing the directory path with forward slashes (str(target_dir).replace('\\', '/'))
    before appending to Tcl's 'auto_path' ensures Tcl interprets the path cleanly without
    escape sequence corruption.
    """
    try:
        import os
        import platform
        machine = os.environ.get("PROCESSOR_ARCHITECTURE", platform.machine())
        platform_rep = "win-arm64" if machine == "ARM64" else ("win-x64" if "64" in machine else "win-x86")
        tcl_major = int(tkroot.tk.call("info", "tclversion").split(".")[0])
        subfolder = f"{platform_rep}-tcl9" if tcl_major >= 9 else platform_rep
        target_dir = (Path(tkdnd.__file__).parent / "tkdnd" / subfolder).resolve()
        if target_dir.is_dir():
            tkroot.tk.call("lappend", "auto_path", str(target_dir).replace("\\", "/"))
    except Exception:
        pass
    return tdnd._require(tkroot)


class OCRApp(ctk.CTk, tdnd.DnDWrapper):
    """GLM-OCR Local desktop studio application window.

    Coordinates presentation widgets with a dedicated background worker thread
    via thread-safe queue hand-offs. Widgets are exclusively mutated on the
    main thread during periodic queue polling.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine: Optional[OCREngine] = None,
    ) -> None:
        """Initialize the GUI application window and worker thread.

        Args:
            settings: Application runtime configuration. Defaults to Settings.from_env().
            engine: Pre-configured OCREngine instance. Created automatically if omitted.
        """
        super().__init__()
        self.TkdndVersion = _init_tkinterdnd(self)

        self.settings = settings or Settings.from_env()
        self.engine = engine or OCREngine(self.settings)

        # Configure appearance and geometry (Windows 11 dark mode aesthetic)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("GLM-OCR Local Studio")
        self.geometry("900x600")
        self.minsize(600, 400)

        # Thread synchronization queues and state
        self._task_queue: queue.Queue[Optional[Path]] = queue.Queue()
        self._result_queue: queue.Queue[WorkerEvent] = queue.Queue()
        self._shutdown_event = threading.Event()
        self._is_shutting_down = False
        self._poll_id: Optional[str] = None

        # Minimal initial UI placeholder
        self._status_label = ctk.CTkLabel(
            self,
            text="GLM-OCR Local Studio - Ready\nDrop files here or click to browse",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self._status_label.pack(expand=True, fill="both", padx=20, pady=20)

        # Protocol handlers
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Native drag-and-drop registration
        self.drop_target_register(tkdnd.DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop_files)

        # Background worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="OCRWorkerThread",
            daemon=True,
        )
        self._worker_thread.start()

        # Start periodic result queue polling
        self._poll_result_queue()

    def enqueue_file(self, file_path: Union[str, Path]) -> None:
        """Submit a document file to the worker task queue for processing.

        Args:
            file_path: Absolute or relative path to an image or PDF document.
        """
        if self._is_shutting_down:
            return
        self._task_queue.put(Path(file_path))

    def _on_drop_files(self, event: Any) -> None:
        """Handle native drop events received from TkinterDnD."""
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return

        try:
            file_paths = self.tk.splitlist(raw_data)
        except Exception as exc:
            sys.stderr.write(f"Failed to parse dropped files data: {exc}\n")
            return

        for path_str in file_paths:
            path = Path(path_str)
            print(f"[GUI DnD] Dropped file received: {path}")
            self.enqueue_file(path)

    def _worker_loop(self) -> None:
        """Dedicated background worker loop processing OCR jobs from the task queue."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    # Timeout allows periodically checking shutdown event
                    item = self._task_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if item is None or self._shutdown_event.is_set():
                    self._task_queue.task_done()
                    break

                file_path_str = str(item)

                # Post STARTED event
                self._result_queue.put(
                    WorkerEvent(
                        event_type=WorkerEventType.STARTED,
                        file_path=file_path_str,
                    )
                )

                try:
                    # Execute OCR via Core Engine
                    result = self.engine.process_document(file_path_str)
                    if result.status == JobStatus.SUCCESS:
                        event_type = WorkerEventType.COMPLETED
                    else:
                        event_type = WorkerEventType.FAILED

                    self._result_queue.put(
                        WorkerEvent(
                            event_type=event_type,
                            file_path=file_path_str,
                            result=result,
                            error=result.error,
                        )
                    )
                except Exception as exc:
                    sys.stderr.write(f"Unexpected error processing {file_path_str}: {exc}\n")
                    traceback.print_exc(file=sys.stderr)
                    self._result_queue.put(
                        WorkerEvent(
                            event_type=WorkerEventType.FAILED,
                            file_path=file_path_str,
                            error=str(exc),
                        )
                    )
                finally:
                    self._task_queue.task_done()

        except Exception as crash_exc:
            # Fatal crash of the worker loop itself
            sys.stderr.write(f"FATAL: OCRWorkerThread crashed: {crash_exc}\n")
            traceback.print_exc(file=sys.stderr)
            try:
                self._result_queue.put(
                    WorkerEvent(
                        event_type=WorkerEventType.WORKER_CRASHED,
                        file_path="",
                        error=f"Worker loop crashed: {crash_exc}",
                    )
                )
            except Exception:
                pass

    def _process_result_queue(self) -> None:
        """Periodic timer callback running on the main thread to process worker events."""
        while True:
            try:
                event = self._result_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_worker_event(event)

        if not self._is_shutting_down:
            self._poll_id = self.after(50, self._process_result_queue)

    _poll_result_queue = _process_result_queue

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        """Process a worker event on the main thread (placeholder for UI table updates)."""
        if event.event_type == WorkerEventType.STARTED:
            print(f"[GUI Worker] Started processing: {event.file_path}")
            self._status_label.configure(text=f"Processing: {Path(event.file_path).name}")
        elif event.event_type == WorkerEventType.COMPLETED:
            status = event.result.status.value if event.result else "SUCCESS"
            print(f"[GUI Worker] Completed processing: {event.file_path} (Status: {status})")
            self._status_label.configure(text=f"Done: {Path(event.file_path).name} ({status})")
        elif event.event_type == WorkerEventType.FAILED:
            print(f"[GUI Worker] Failed processing: {event.file_path} (Error: {event.error})")
            self._status_label.configure(text=f"Failed: {Path(event.file_path).name} - {event.error}")
        elif event.event_type == WorkerEventType.WORKER_CRASHED:
            # Output diagnostic clearly to stderr and flush so it is never silently swallowed
            print(f"[GUI Worker] FATAL: Worker thread crashed: {event.error}", file=sys.stderr)
            sys.stderr.flush()
            # TODO (Phase 3 Layout): Surface this to the user visually in the UI / dialog once the queue table exists
            self._status_label.configure(text=f"Fatal Worker Error: {event.error}")

    def _on_closing(self) -> None:
        """Cleanly terminate background worker, network sessions, and destroy window."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        # 1. Cancel active after() polling timer
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

        # 2. Signal worker thread to stop
        self._shutdown_event.set()

        # 3. Drain unstarted tasks from queue and enqueue termination sentinel
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
                self._task_queue.task_done()
            except (queue.Empty, ValueError):
                break

        try:
            self._task_queue.put_nowait(None)
        except (queue.Full, ValueError):
            pass

        # 4. Short join to allow worker to finish if idle
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.1)

        # 5. Explicitly close VisionClient / network sessions
        try:
            if hasattr(self.engine, "close"):
                self.engine.close()
            elif hasattr(self.engine, "client") and hasattr(self.engine.client, "close"):
                self.engine.client.close()
        except Exception as close_exc:
            sys.stderr.write(f"Warning: error closing engine client: {close_exc}\n")

        # 6. Destroy window
        self.destroy()


def main() -> None:
    """Run the GLM-OCR Local GUI application."""
    app = OCRApp()
    app.mainloop()


if __name__ == "__main__":
    main()
