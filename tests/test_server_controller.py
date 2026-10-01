"""Isolated unit tests for gui/server_controller.py.

Tests ServerUIController health polling cadence, status pill visuals,
start/stop worker threads, auto-start on launch, and graceful shutdown
using lightweight duck-typed fake controls.
Runs 100% headless without requiring ctk.CTk or a display server.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo
from gui.server_controller import ServerUIController
from gui.theme import (
    COLOR_TEXT_MUTED,
)


class FakeWidget:
    """Duck-typed widget fake tracking configure calls and attributes."""

    def __init__(self, **kwargs: Any) -> None:
        self.attrs: Dict[str, Any] = dict(kwargs)
        self.configure_calls: List[Dict[str, Any]] = []

    def cget(self, key: str) -> Any:
        return self.attrs.get(key)

    def configure(self, **kwargs: Any) -> None:
        self.attrs.update(kwargs)
        self.configure_calls.append(kwargs)


class FakeLabel(FakeWidget):
    """Duck-typed label widget fake."""

    def __init__(self, text: str = "● OFFLINE", fg_color: str = "", text_color: str = "", **kwargs: Any) -> None:
        super().__init__(text=text, fg_color=fg_color, text_color=text_color, **kwargs)


class FakeButton(FakeWidget):
    """Duck-typed button widget fake."""

    def __init__(self, text: str = "Start Server", state: str = "normal", **kwargs: Any) -> None:
        super().__init__(text=text, state=state, **kwargs)


class StubSettings:
    """Lightweight settings stub for server controller testing."""

    def __init__(self, auto_start_server: bool = False) -> None:
        self.auto_start_server = auto_start_server


@pytest.fixture
def controller_harness():
    """Build a ServerUIController instance wired with test doubles."""
    mock_sm = MagicMock()
    mock_sm.status = ServerStatus.OFFLINE
    mock_sm.ownership = ServerOwnership.NONE
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    mock_sm.get_status_info.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )

    settings = StubSettings(auto_start_server=False)
    mock_engine = MagicMock()
    pill = FakeLabel()
    btn = FakeButton()
    shutdown_ev = threading.Event()
    footer_messages: List[str] = []
    safe_after_callbacks: List[Tuple[Callable, tuple]] = []

    def fake_update_footer(msg: Optional[str]) -> None:
        if msg is not None:
            footer_messages.append(msg)

    def fake_safe_after(ms: int, func: Callable, *args: Any) -> None:
        safe_after_callbacks.append((func, args))

    def drain() -> None:
        while safe_after_callbacks:
            fn, args = safe_after_callbacks.pop(0)
            fn(*args)

    controller = ServerUIController(
        server_manager=mock_sm,
        settings=settings,
        engine=mock_engine,
        safe_after=fake_safe_after,
        is_shutting_down=lambda: False,
        shutdown_event=shutdown_ev,
        update_footer=fake_update_footer,
        server_status_pill=pill,
        btn_server_action=btn,
        format_error=lambda err: f"formatted: {err}",
    )

    return {
        "controller": controller,
        "server_manager": mock_sm,
        "settings": settings,
        "engine": mock_engine,
        "pill": pill,
        "btn": btn,
        "shutdown_ev": shutdown_ev,
        "footer_messages": footer_messages,
        "safe_after_callbacks": safe_after_callbacks,
        "drain": drain,
    }


def test_controller_initialization_and_properties():
    """Verify property getters and setters on ServerUIController."""
    mock_sm1 = MagicMock()
    mock_sm2 = MagicMock()
    settings1 = StubSettings(auto_start_server=False)
    settings2 = StubSettings(auto_start_server=True)

    # Direct server_manager and settings
    ctrl = ServerUIController(
        server_manager=mock_sm1,
        settings=settings1,
    )
    assert ctrl.server_manager is mock_sm1
    assert ctrl.settings is settings1
    assert ctrl.last_applied_server_status is None
    assert ctrl.server_poller_thread is None
    assert ctrl.server_start_thread is None
    assert ctrl.server_stop_thread is None

    # Direct setters
    ctrl.server_manager = mock_sm2
    assert ctrl.server_manager is mock_sm2
    ctrl.settings = settings2
    assert ctrl.settings is settings2

    ctrl.last_applied_server_status = (ServerStatus.READY, ServerOwnership.MANAGED)
    assert ctrl.last_applied_server_status == (ServerStatus.READY, ServerOwnership.MANAGED)

    dummy_t1 = threading.Thread(target=lambda: None)
    dummy_t2 = threading.Thread(target=lambda: None)
    dummy_t3 = threading.Thread(target=lambda: None)

    ctrl.server_poller_thread = dummy_t1
    assert ctrl.server_poller_thread is dummy_t1
    ctrl.server_start_thread = dummy_t2
    assert ctrl.server_start_thread is dummy_t2
    ctrl.server_stop_thread = dummy_t3
    assert ctrl.server_stop_thread is dummy_t3


def test_status_rendering_all_states(controller_harness):
    """Verify header status pill and action button update across all status states."""
    ctrl = controller_harness["controller"]
    pill = controller_harness["pill"]
    btn = controller_harness["btn"]

    # 1. OFFLINE
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")
    )
    assert pill.cget("text") == "● OFFLINE"
    assert pill.cget("text_color") == COLOR_TEXT_MUTED
    assert btn.cget("text") == "Start Server"
    assert btn.cget("state") == "normal"

    # 2a. STARTING (External / None)
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.STARTING, ownership=ServerOwnership.NONE, message="Starting")
    )
    assert pill.cget("text") == "● STARTING"
    assert pill.cget("text_color") == "#fbbf24"
    assert btn.cget("text") == "Starting..."
    assert btn.cget("state") == "disabled"

    # 2b. STARTING (Managed) -> Cancel Launch
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.STARTING, ownership=ServerOwnership.MANAGED, message="Starting")
    )
    assert pill.cget("text") == "● STARTING"
    assert btn.cget("text") == "Cancel Launch"
    assert btn.cget("state") == "normal"
    assert btn.cget("text_color") == "#fb7185"

    # 3. READY (Managed) -> Stop Server
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED, message="Ready")
    )
    assert pill.cget("text") == "● READY (Managed)"
    assert pill.cget("text_color") == "#34d399"
    assert btn.cget("text") == "Stop Server"
    assert btn.cget("state") == "normal"
    assert btn.cget("text_color") == "#fb7185"

    # 4. READY (External) -> External (disabled)
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.EXTERNAL, message="Ready")
    )
    assert pill.cget("text") == "● READY (Ext)"
    assert pill.cget("text_color") == "#34d399"
    assert btn.cget("text") == "External"
    assert btn.cget("state") == "disabled"

    # 5. ERROR -> Start Server
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.ERROR, ownership=ServerOwnership.NONE, message="Failed")
    )
    assert pill.cget("text") == "● ERROR"
    assert pill.cget("text_color") == "#fb7185"
    assert btn.cget("text") == "Start Server"
    assert btn.cget("state") == "normal"


def test_status_deduplication(controller_harness):
    """Verify consecutive duplicate status updates do not trigger unnecessary widget reconfiguration."""
    ctrl = controller_harness["controller"]
    pill = controller_harness["pill"]

    info = ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")
    ctrl.apply_server_status_update(info)
    first_call_count = len(pill.configure_calls)
    assert first_call_count > 0

    # Second call with identical status & ownership
    ctrl.apply_server_status_update(info)
    assert len(pill.configure_calls) == first_call_count

    # Different status triggers reconfiguration
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.STARTING, ownership=ServerOwnership.NONE, message="Booting")
    )
    assert len(pill.configure_calls) > first_call_count


def test_backend_cache_invalidation_seam(controller_harness):
    """Verify engine backend verification cache is invalidated whenever status != READY."""
    ctrl = controller_harness["controller"]
    mock_engine = controller_harness["engine"]

    # When NOT READY (OFFLINE)
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")
    )
    assert mock_engine.invalidate_backend_verification.call_count == 1

    # When READY -> cache invalidation is NOT called
    mock_engine.invalidate_backend_verification.reset_mock()
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED, message="Ready")
    )
    mock_engine.invalidate_backend_verification.assert_not_called()

    # When transitioning from READY to ERROR -> cache invalidation IS called
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.ERROR, ownership=ServerOwnership.NONE, message="Crash")
    )
    assert mock_engine.invalidate_backend_verification.call_count == 1


def test_shutting_down_guard(controller_harness):
    """Verify apply_server_status_update is a no-op when is_shutting_down returns True."""
    ctrl = controller_harness["controller"]
    pill = controller_harness["pill"]
    mock_engine = controller_harness["engine"]

    ctrl.is_shutting_down = lambda: True

    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED, message="Ready")
    )

    assert len(pill.configure_calls) == 0
    assert ctrl.last_applied_server_status is None
    mock_engine.invalidate_backend_verification.assert_not_called()


def test_auto_start_if_needed(controller_harness):
    """Verify auto_start_if_needed starts server only when auto_start_server=True and offline."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    settings = controller_harness["settings"]

    # 1. auto_start_server=False -> no start
    settings.auto_start_server = False
    ctrl.auto_start_if_needed()
    mock_sm.start.assert_not_called()

    # 2. auto_start_server=True and OFFLINE -> start called
    settings.auto_start_server = True
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    ctrl.auto_start_if_needed()
    mock_sm.start.assert_called_once()

    # 3. auto_start_server=True but READY -> start not called again
    mock_sm.start.reset_mock()
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Ready",
    )
    ctrl.auto_start_if_needed()
    mock_sm.start.assert_not_called()

    # 4. Exception in start() handled cleanly without crash
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    mock_sm.start.side_effect = RuntimeError("Failed to bind port")
    ctrl.auto_start_if_needed()  # should not raise
    mock_sm.start.side_effect = None


def test_action_click_dispatch_start(controller_harness):
    """Verify clicking action button when offline dispatches start() worker thread."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    btn = controller_harness["btn"]
    pill = controller_harness["pill"]
    drain = controller_harness["drain"]

    mock_sm.status = ServerStatus.OFFLINE
    mock_sm.ownership = ServerOwnership.NONE

    start_called = threading.Event()

    def fake_start():
        start_called.set()

    mock_sm.start.side_effect = fake_start

    ctrl.on_server_action_clicked()

    # Immediate feedback before worker thread completion
    assert btn.cget("text") == "Starting..."
    assert btn.cget("state") == "disabled"
    assert pill.cget("text") == "● STARTING"

    # Wait for worker thread
    assert start_called.wait(timeout=2.0)
    assert ctrl.server_start_thread is not None
    ctrl.server_start_thread.join(timeout=1.0)
    assert not ctrl.server_start_thread.is_alive()

    # Drain safe_after callbacks
    drain()


def test_action_click_dispatch_start_failure(controller_harness):
    """Verify start failure formats error message and posts to footer."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    footer_messages = controller_harness["footer_messages"]
    drain = controller_harness["drain"]

    mock_sm.status = ServerStatus.OFFLINE
    mock_sm.ownership = ServerOwnership.NONE
    mock_sm.start.side_effect = ConnectionRefusedError("Backend process crashed")

    ctrl.on_server_action_clicked()

    assert ctrl.server_start_thread is not None
    ctrl.server_start_thread.join(timeout=1.0)

    drain()
    assert any("Server start failed: formatted: Backend process crashed" in msg for msg in footer_messages)


def test_action_click_dispatch_stop(controller_harness):
    """Verify clicking action button when READY and MANAGED dispatches stop() worker thread."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    btn = controller_harness["btn"]
    drain = controller_harness["drain"]

    mock_sm.status = ServerStatus.READY
    mock_sm.ownership = ServerOwnership.MANAGED

    stop_called = threading.Event()

    def fake_stop():
        stop_called.set()

    mock_sm.stop.side_effect = fake_stop

    ctrl.on_server_action_clicked()

    # Immediate feedback
    assert btn.cget("text") == "Stopping..."
    assert btn.cget("state") == "disabled"

    # Wait for worker thread
    assert stop_called.wait(timeout=2.0)
    assert ctrl.server_stop_thread is not None
    ctrl.server_stop_thread.join(timeout=1.0)
    assert not ctrl.server_stop_thread.is_alive()

    drain()


def test_action_click_dispatch_cancel_launch(controller_harness):
    """Verify clicking action button when STARTING and MANAGED dispatches stop() to cancel launch."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    btn = controller_harness["btn"]
    drain = controller_harness["drain"]

    mock_sm.status = ServerStatus.STARTING
    mock_sm.ownership = ServerOwnership.MANAGED

    stop_called = threading.Event()
    mock_sm.stop.side_effect = lambda: stop_called.set()

    ctrl.on_server_action_clicked()

    assert btn.cget("text") == "Stopping..."
    assert stop_called.wait(timeout=2.0)
    assert ctrl.server_stop_thread is not None
    ctrl.server_stop_thread.join(timeout=1.0)

    drain()


def test_action_click_dispatch_stop_failure(controller_harness):
    """Verify stop failure formats error message and posts to footer."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    footer_messages = controller_harness["footer_messages"]
    drain = controller_harness["drain"]

    mock_sm.status = ServerStatus.READY
    mock_sm.ownership = ServerOwnership.MANAGED
    mock_sm.stop.side_effect = RuntimeError("Process hung")

    ctrl.on_server_action_clicked()

    assert ctrl.server_stop_thread is not None
    ctrl.server_stop_thread.join(timeout=1.0)

    drain()
    assert any("Server stop failed: formatted: Process hung" in msg for msg in footer_messages)


def test_poller_thread_and_graceful_shutdown(controller_harness):
    """Verify start_poller starts background daemon and shutdown terminates worker threads."""
    ctrl = controller_harness["controller"]
    mock_sm = controller_harness["server_manager"]
    shutdown_ev = controller_harness["shutdown_ev"]

    polled = threading.Event()

    def fake_poll():
        polled.set()
        return ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")

    mock_sm.poll_status.side_effect = fake_poll

    ctrl.start_poller()
    assert ctrl.server_poller_thread is not None
    assert ctrl.server_poller_thread.is_alive()

    # Poller runs and queries server status
    assert polled.wait(timeout=2.0)

    # Set shutdown event and trigger controller shutdown
    shutdown_ev.set()
    ctrl.shutdown(timeout=1.0)
    assert not ctrl.server_poller_thread.is_alive()


def test_poller_cadence_starting_vs_steady():
    """Verify poller loop uses 2.0s interval when STARTING, and 10.0s when other."""
    shutdown_ev = threading.Event()
    wait_times: List[float] = []

    def spy_wait(timeout=None):
        if timeout is not None:
            wait_times.append(timeout)
        shutdown_ev.set()  # Stop after first iteration
        return True

    shutdown_ev.wait = spy_wait  # type: ignore

    mock_sm = MagicMock()
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.STARTING,
        ownership=ServerOwnership.MANAGED,
        message="Starting",
    )

    ctrl = ServerUIController(
        server_manager=mock_sm,
        settings=StubSettings(),
        shutdown_event=shutdown_ev,
    )

    ctrl.start_poller()
    if ctrl.server_poller_thread is not None:
        ctrl.server_poller_thread.join(timeout=1.0)

    assert wait_times == [2.0]


def test_none_widgets_and_callbacks_resilience():
    """Verify ServerUIController gracefully operates when widgets or callbacks are None."""
    mock_sm = MagicMock()
    mock_sm.status = ServerStatus.OFFLINE
    mock_sm.ownership = ServerOwnership.NONE
    mock_sm.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )

    ctrl = ServerUIController(
        server_manager=mock_sm,
        settings=StubSettings(),
        engine=None,
        safe_after=None,
        is_shutting_down=None,
        shutdown_event=None,
        update_footer=None,
        server_status_pill=None,
        btn_server_action=None,
    )

    # Calling apply_server_status_update with None widgets shouldn't crash
    ctrl.apply_server_status_update(
        ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")
    )
    assert ctrl.last_applied_server_status == (ServerStatus.OFFLINE, ServerOwnership.NONE)

    # Calling action click with None widgets shouldn't crash
    ctrl.on_server_action_clicked()
    if ctrl.server_start_thread is not None:
        ctrl.server_start_thread.join(timeout=1.0)

    # Calling shutdown shouldn't crash
    ctrl.shutdown(timeout=0.1)
