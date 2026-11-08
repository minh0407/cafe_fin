"""Windows-only private job for the synthetic sidecar harness.

Create suspended, attach to a non-inheritable kill-on-close job, then resume.
This prevents a one-file bootloader from spawning outside the job before attach.
Failure to obtain that containment aborts launch; no breakaway/policy fallback.
"""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _kernel():
    if os.name != "nt":
        raise RuntimeError("private_job_requires_windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "QueryInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
            wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


def _checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def _resume_primary_thread(kernel, pid):
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        threads = []
        result = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while result:
            if entry.th32OwnerProcessID == pid:
                threads.append(entry.th32ThreadID)
            entry.dwSize = ctypes.sizeof(entry)
            result = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        if len(threads) != 1:
            raise RuntimeError("suspended_primary_thread_count")
        thread = _checked(kernel.OpenThread(0x0002, False, threads[0]))
        try:
            result = kernel.ResumeThread(thread)
            if result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            if result != 1:
                raise RuntimeError("suspended_primary_thread_state")
        finally:
            kernel.CloseHandle(thread)
    finally:
        kernel.CloseHandle(snapshot)


class PrivateProcess:
    def __init__(self, process, kernel, job):
        self._process, self._kernel, self._job = process, kernel, job
        self.stdin, self.stdout, self.stderr = process.stdin, process.stdout, process.stderr
        self.pid = process.pid

    @property
    def returncode(self):
        return self._process.returncode

    def poll(self):
        return self._process.poll()

    def wait(self, timeout=None):
        return self._process.wait(timeout=timeout)

    def kill(self):
        if self._job is not None:
            _checked(self._kernel.TerminateJobObject(self._job, 1))

    def _process_handles(self):
        # Capture waitable handles before termination. ActiveProcesses can become
        # zero slightly before the terminated process objects signal completion.
        capacity = 16
        while capacity <= 4096:

            class ProcessIds(ctypes.Structure):
                _fields_ = [
                    ("assigned", wintypes.DWORD),
                    ("listed", wintypes.DWORD),
                    ("ids", ctypes.c_size_t * capacity),
                ]

            ids = ProcessIds()
            result = self._kernel.QueryInformationJobObject(
                self._job,
                3,
                ctypes.byref(ids),
                ctypes.sizeof(ids),
                None,
            )
            if result:
                handles = []
                try:
                    for pid in ids.ids[: ids.listed]:
                        handle = self._kernel.OpenProcess(0x00100000, False, pid)
                        if handle:
                            handles.append(handle)
                        elif ctypes.get_last_error() != 87:  # exited before OpenProcess
                            raise ctypes.WinError(ctypes.get_last_error())
                    return handles
                except BaseException:
                    for handle in handles:
                        self._kernel.CloseHandle(handle)
                    raise
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        raise RuntimeError("private_job_process_limit")

    def close_tree(self, timeout=10):
        """Terminate remaining descendants, including after the root has exited.

        On success all writers in this private tree have exited, so pipe readers
        can reach EOF. Call before joining readers and closing their streams.
        """
        if self._job is None:
            return
        handles = []
        try:
            handles = self._process_handles()
            self.kill()
            deadline = time.monotonic() + timeout
            accounting = _Accounting()
            while True:
                _checked(
                    self._kernel.QueryInformationJobObject(
                        self._job,
                        1,
                        ctypes.byref(accounting),
                        ctypes.sizeof(accounting),
                        None,
                    )
                )
                if accounting.ActiveProcesses == 0:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("private_job_cleanup_timeout")
                time.sleep(0.02)
            for handle in handles:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                result = self._kernel.WaitForSingleObject(handle, remaining_ms)
                if result == 258:
                    raise TimeoutError("private_job_cleanup_timeout")
                if result != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
            self.wait(timeout=max(0, deadline - time.monotonic()))
        finally:
            for handle in handles:
                self._kernel.CloseHandle(handle)
            self._kernel.CloseHandle(self._job)
            self._job = None


def launch_private(command, *, cwd, env):
    kernel = _kernel()
    job = _checked(kernel.CreateJobObjectW(None, None))
    process = process_handle = None
    try:
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        _checked(
            kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004,  # CREATE_SUSPENDED
        )
        process_handle = _checked(kernel.OpenProcess(0x0100 | 0x0001, False, process.pid))
        _checked(kernel.AssignProcessToJobObject(job, process_handle))
        _resume_primary_thread(kernel, process.pid)
        return PrivateProcess(process, kernel, job)
    except BaseException:
        # Before resume there are no descendants; after assignment the job owns
        # every descendant. Closing its sole handle also enforces termination.
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        raise
    finally:
        if process_handle:
            kernel.CloseHandle(process_handle)
