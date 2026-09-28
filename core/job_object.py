"""Windows Job Object management for child process lifecycle containment.

Assigns spawned inference backend processes to a Win32 Job Object configured
with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so that child processes terminate
reliably if the parent process exits or terminates unexpectedly.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JobObjectExtendedLimitInformation = 9

    def _create_kill_on_close_job() -> Optional[int]:
        """Create a Win32 Job Object configured to terminate member processes on handle close."""
        try:
            k32 = ctypes.windll.kernel32
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.SetInformationJobObject.restype = wintypes.BOOL
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None

            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            success = k32.SetInformationJobObject(
                job,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not success:
                k32.CloseHandle(job)
                return None
            return job
        except Exception as exc:
            logger.debug("Failed to initialize Windows Job Object: %s", exc)
            return None

    def _assign_process_to_job(job_handle: int, process_handle: int) -> bool:
        """Assign a process handle to a Win32 Job Object with non-silent warning fallback."""
        try:
            k32 = ctypes.windll.kernel32
            k32.AssignProcessToJobObject.restype = wintypes.BOOL
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            ret = k32.AssignProcessToJobObject(job_handle, process_handle)
            if not ret:
                err = k32.GetLastError()
                logger.warning(
                    "Failed to assign server process to Windows Job Object (Win32 error %d). "
                    "Falling back to standard software lifecycle hooks.",
                    err,
                )
                return False
            return True
        except Exception as exc:
            logger.warning("Error assigning process to Windows Job Object: %s", exc)
            return False

    def _close_job_handle(job_handle: int) -> None:
        """Close a Win32 Job Object handle."""
        try:
            k32 = ctypes.windll.kernel32
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle(job_handle)
        except Exception:
            pass

else:
    def _create_kill_on_close_job() -> Optional[int]:
        return None

    def _assign_process_to_job(job_handle: int, process_handle: int) -> bool:
        return False

    def _close_job_handle(job_handle: int) -> None:
        pass


_create_job_object = _create_kill_on_close_job


class Win32JobObject:
    """Encapsulates Win32 Job Object operations for subprocess containment."""

    create = staticmethod(_create_kill_on_close_job)
    assign = staticmethod(_assign_process_to_job)
    close = staticmethod(_close_job_handle)
