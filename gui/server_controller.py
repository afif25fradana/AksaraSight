"""Server UI and supervision controller for AksaraSight Desktop Studio.

Manages backend server health polling, status pill styling, start/stop worker
threads, auto-start on launch, and graceful poller termination.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, Tuple

from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo
from gui.theme import (
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
)

logger = logging.getLogger(__name__)


class ServerUIController:
    """Manages server health polling cadence, status pill visuals, and lifecycle actions."""

    def __init__(
        self,
        server_manager: Any,
        settings: Any,
        engine: Optional[Any] = None,
        safe_after: Optional[Callable[[int, Any], None]] = None,
        is_shutting_down: Optional[Callable[[], bool]] = None,
        shutdown_event: Optional[threading.Event] = None,
        update_footer: Optional[Callable[[Optional[str]], None]] = None,
        server_status_pill: Optional[Any] = None,
        btn_server_action: Optional[Any] = None,
        format_error: Callable[[Any], str] = str,
    ) -> None:
        self._server_manager = server_manager
        self._settings = settings
        self.engine = engine
        self.safe_after = safe_after
        self.is_shutting_down = is_shutting_down
        self.shutdown_event = shutdown_event
        self.update_footer = update_footer
        self.server_status_pill = server_status_pill
        self.btn_server_action = btn_server_action
        self.format_error = format_error

        self._last_applied_server_status: Optional[Tuple[ServerStatus, ServerOwnership]] = None
        self._server_poller_thread: Optional[threading.Thread] = None
        self._server_start_thread: Optional[threading.Thread] = None
        self._server_stop_thread: Optional[threading.Thread] = None

    @property
    def server_manager(self) -> Any:
        """Return the server manager instance."""
        return self._server_manager

    @server_manager.setter
    def server_manager(self, value: Any) -> None:
        self._server_manager = value

    @property
    def settings(self) -> Any:
        """Return the application settings."""
        return self._settings

    @settings.setter
    def settings(self, value: Any) -> None:
        self._settings = value

    @property
    def last_applied_server_status(self) -> Optional[Tuple[ServerStatus, ServerOwnership]]:
        """Return cached (status, ownership) tuple to prevent duplicate widget reconfiguration."""
        return self._last_applied_server_status

    @last_applied_server_status.setter
    def last_applied_server_status(self, value: Optional[Tuple[ServerStatus, ServerOwnership]]) -> None:
        self._last_applied_server_status = value

    @property
    def server_poller_thread(self) -> Optional[threading.Thread]:
        """Return the background server health poller thread."""
        return self._server_poller_thread

    @server_poller_thread.setter
    def server_poller_thread(self, value: Optional[threading.Thread]) -> None:
        self._server_poller_thread = value

    @property
    def server_start_thread(self) -> Optional[threading.Thread]:
        """Return the background server start worker thread."""
        return self._server_start_thread

    @server_start_thread.setter
    def server_start_thread(self, value: Optional[threading.Thread]) -> None:
        self._server_start_thread = value

    @property
    def server_stop_thread(self) -> Optional[threading.Thread]:
        """Return the background server stop worker thread."""
        return self._server_stop_thread

    @server_stop_thread.setter
    def server_stop_thread(self, value: Optional[threading.Thread]) -> None:
        self._server_stop_thread = value

    def auto_start_if_needed(self) -> None:
        """Auto-start managed server on launch if enabled in settings and currently offline."""
        settings = self.settings
        if settings is not None and getattr(settings, "auto_start_server", False):
            try:
                init_info = self.server_manager.poll_status()
                if init_info.status == ServerStatus.OFFLINE:
                    logger.info("auto_start_server enabled; starting backend server process...")
                    self.server_manager.start()
            except Exception as auto_start_err:
                logger.warning("Failed to auto-start backend server on launch: %s", auto_start_err)

    def start_poller(self) -> None:
        """Start background daemon thread periodically querying server health."""
        try:
            self.apply_server_status_update(self.server_manager.get_status_info())
        except Exception:
            pass

        def _poller_worker() -> None:
            while self.shutdown_event is not None and not self.shutdown_event.is_set():
                poll_interval = 10.0
                try:
                    info = self.server_manager.poll_status()
                    if self.safe_after is not None:
                        self.safe_after(0, self.apply_server_status_update, info)
                    else:
                        self.apply_server_status_update(info)

                    if info.status == ServerStatus.STARTING:
                        poll_interval = 2.0
                    else:
                        poll_interval = 10.0
                except Exception as exc:
                    logger.debug("Server status poll error: %s", exc)
                    poll_interval = 10.0

                if self.shutdown_event is not None and self.shutdown_event.wait(timeout=poll_interval):
                    break

        thread = threading.Thread(target=_poller_worker, name="ServerPollerThread", daemon=True)
        thread.start()
        self._server_poller_thread = thread

    def apply_server_status_update(self, info: ServerStatusInfo) -> None:
        """Update header status pill and action button from ServerStatusInfo."""
        if self.is_shutting_down is not None and self.is_shutting_down():
            return

        status = info.status
        ownership = info.ownership

        if self._last_applied_server_status == (status, ownership):
            return
        self._last_applied_server_status = (status, ownership)

        if status != ServerStatus.READY and self.engine is not None and hasattr(self.engine, "invalidate_backend_verification"):
            self.engine.invalidate_backend_verification()

        if self.server_status_pill is None:
            return

        if status == ServerStatus.READY:
            ownership_lbl = " (Managed)" if ownership == ServerOwnership.MANAGED else " (Ext)"
            self.server_status_pill.configure(
                text=f"● READY{ownership_lbl}",
                fg_color="#0f3322",
                text_color="#34d399",
            )
            if self.btn_server_action is not None:
                if ownership == ServerOwnership.MANAGED:
                    self.btn_server_action.configure(
                        text="Stop Server",
                        state="normal",
                        fg_color="#3d1419",
                        hover_color="#541b22",
                        text_color="#fb7185",
                        border_color="#732531",
                    )
                else:
                    self.btn_server_action.configure(
                        text="External",
                        state="disabled",
                        fg_color=COLOR_INTERACTIVE_NEUTRAL,
                        text_color=COLOR_TEXT_MUTED,
                        border_color=COLOR_SURFACE_BORDER,
                    )

        elif status == ServerStatus.STARTING:
            self.server_status_pill.configure(
                text="● STARTING",
                fg_color="#3d2a00",
                text_color="#fbbf24",
            )
            if self.btn_server_action is not None:
                if ownership == ServerOwnership.MANAGED:
                    self.btn_server_action.configure(
                        text="Cancel Launch",
                        state="normal",
                        fg_color="#3d1419",
                        hover_color="#541b22",
                        text_color="#fb7185",
                        border_color="#732531",
                    )
                else:
                    self.btn_server_action.configure(
                        text="Starting...",
                        state="disabled",
                        fg_color=COLOR_INTERACTIVE_NEUTRAL,
                        text_color=COLOR_TEXT_MUTED,
                        border_color=COLOR_SURFACE_BORDER,
                    )

        elif status == ServerStatus.ERROR:
            self.server_status_pill.configure(
                text="● ERROR",
                fg_color="#3d1419",
                text_color="#fb7185",
            )
            if self.btn_server_action is not None:
                self.btn_server_action.configure(
                    text="Start Server",
                    state="normal",
                    fg_color=COLOR_INTERACTIVE_NEUTRAL,
                    hover_color=COLOR_INTERACTIVE_HOVER,
                    text_color=COLOR_TEXT_PRIMARY,
                    border_color=COLOR_SURFACE_BORDER,
                )

        else:  # OFFLINE
            self.server_status_pill.configure(
                text="● OFFLINE",
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                text_color=COLOR_TEXT_MUTED,
            )
            if self.btn_server_action is not None:
                self.btn_server_action.configure(
                    text="Start Server",
                    state="normal",
                    fg_color=COLOR_INTERACTIVE_NEUTRAL,
                    hover_color=COLOR_INTERACTIVE_HOVER,
                    text_color=COLOR_TEXT_PRIMARY,
                    border_color=COLOR_SURFACE_BORDER,
                )

    def on_server_action_clicked(self) -> None:
        """Handle user clicks on the server Start/Stop action button."""
        status = self.server_manager.status
        ownership = self.server_manager.ownership

        if (status in (ServerStatus.READY, ServerStatus.STARTING)) and ownership == ServerOwnership.MANAGED:
            if self.btn_server_action is not None:
                self.btn_server_action.configure(text="Stopping...", state="disabled")

            def _stop_worker() -> None:
                try:
                    self.server_manager.stop()
                except Exception as stop_err:
                    logger.warning("Error stopping server: %s", stop_err)
                    if self.safe_after is not None and self.update_footer is not None:
                        self.safe_after(0, lambda e=stop_err: self.update_footer(f"Server stop failed: {self.format_error(e)}"))
                    elif self.update_footer is not None:
                        self.update_footer(f"Server stop failed: {self.format_error(stop_err)}")
                finally:
                    info = self.server_manager.poll_status()
                    if self.safe_after is not None:
                        self.safe_after(0, self.apply_server_status_update, info)
                    else:
                        self.apply_server_status_update(info)

            stop_thread = threading.Thread(target=_stop_worker, name="ServerStopWorker", daemon=True)
            self._server_stop_thread = stop_thread
            stop_thread.start()

        elif status in (ServerStatus.OFFLINE, ServerStatus.ERROR):
            if self.btn_server_action is not None:
                self.btn_server_action.configure(text="Starting...", state="disabled")
            if self.server_status_pill is not None:
                self.server_status_pill.configure(
                    text="● STARTING",
                    fg_color="#3d2a00",
                    text_color="#fbbf24",
                )

            def _start_worker() -> None:
                try:
                    self.server_manager.start()
                except Exception as start_err:
                    logger.warning("Error starting server: %s", start_err)
                    if self.safe_after is not None and self.update_footer is not None:
                        self.safe_after(0, lambda e=start_err: self.update_footer(f"Server start failed: {self.format_error(e)}"))
                    elif self.update_footer is not None:
                        self.update_footer(f"Server start failed: {self.format_error(start_err)}")
                finally:
                    info = self.server_manager.poll_status()
                    if self.safe_after is not None:
                        self.safe_after(0, self.apply_server_status_update, info)
                    else:
                        self.apply_server_status_update(info)

            start_thread = threading.Thread(target=_start_worker, name="ServerStartWorker", daemon=True)
            self._server_start_thread = start_thread
            start_thread.start()

    def shutdown(self, timeout: float = 1.0) -> None:
        """Join any active poller, start, or stop worker threads."""
        if self._server_poller_thread is not None and self._server_poller_thread.is_alive():
            self._server_poller_thread.join(timeout=timeout)
        if self._server_stop_thread is not None and self._server_stop_thread.is_alive():
            self._server_stop_thread.join(timeout=timeout)
        if self._server_start_thread is not None and self._server_start_thread.is_alive():
            self._server_start_thread.join(timeout=timeout)
