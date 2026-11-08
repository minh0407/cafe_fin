"""Sample owned Windows process trees and synthetic app-data, never credentials."""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import threading
import time
from ctypes import wintypes
from pathlib import Path


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def latency_summary(samples):
    grouped = {}
    for sample in samples:
        grouped.setdefault(sample["label"], []).append(sample["seconds"])
    return {
        label: {
            "count": len(values),
            "p50_seconds": percentile(values, 0.5),
            "p95_seconds": percentile(values, 0.95),
            "max_seconds": max(values),
        }
        for label, values in grouped.items()
    }


def windows_process_tree(root_pid):
    if os.name != "nt":
        return []

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_rss",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    all_processes = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            all_processes.append((entry.pid, entry.parent, entry.exe))
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    owned = {root_pid}
    while True:
        children = {pid for pid, parent, _ in all_processes if parent in owned}
        if children.issubset(owned):
            break
        owned.update(children)
    result = []
    for pid, parent, executable in all_processes:
        if pid not in owned:
            continue
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            continue
        try:
            memory = Memory()
            memory.cb = ctypes.sizeof(memory)
            created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                continue
            cpu = None
            creation = None
            if kernel.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(system),
                ctypes.byref(user),
            ):
                cpu = (
                    (system.dwHighDateTime << 32)
                    + system.dwLowDateTime
                    + (user.dwHighDateTime << 32)
                    + user.dwLowDateTime
                ) / 10_000_000
                creation = (created.dwHighDateTime << 32) + created.dwLowDateTime
            image_buffer, image_size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            image = (
                image_buffer.value
                if kernel.QueryFullProcessImageNameW(
                    handle, 0, image_buffer, ctypes.byref(image_size)
                )
                else None
            )
            result.append(
                {
                    "pid": pid,
                    "parent_pid": parent,
                    "executable": executable,
                    "image_path": image,
                    "creation_filetime_100ns": creation,
                    "architecture": "NOT_MEASURED",
                    "role_scope": "owned backend tree; API/parser/worker may share this PID",
                    "rss_bytes": memory.rss,
                    "os_peak_rss_bytes": memory.peak_rss,
                    "private_bytes": memory.private,
                    "cpu_seconds_since_process_start": cpu,
                }
            )
        finally:
            kernel.CloseHandle(handle)
    return result


def disk_sizes(root: Path):
    values = {
        "database_bytes": 0,
        "wal_bytes": 0,
        "shm_bytes": 0,
        "app_data_bytes": 0,
        "app_import_temp_bytes": 0,
    }
    if not root.exists():
        return values
    for folder, _, files in os.walk(root):
        for name in files:
            path = Path(folder) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            values["app_data_bytes"] += size
            if name == "cafe_fin.db":
                values["database_bytes"] += size
            if name.endswith("-wal"):
                values["wal_bytes"] += size
            if name.endswith("-shm"):
                values["shm_bytes"] += size
            if "imports" in path.relative_to(root).parts:
                values["app_import_temp_bytes"] += size
    return values


def resource_summary(samples):
    """Per-process peaks and observed CPU deltas; never sum shared RSS by role."""
    processes, disk_peaks = {}, {}
    for sample in samples:
        for name, value in sample["disk"].items():
            disk_peaks[name] = max(disk_peaks.get(name, 0), value)
        for process in sample["processes"]:
            identity = (process["pid"], process.get("creation_filetime_100ns"))
            item = processes.setdefault(
                identity,
                {
                    "pid": process["pid"],
                    "creation_filetime_100ns": identity[1],
                    "executable": process["executable"],
                    "image_path": process.get("image_path"),
                    "rss_peak_sampled_bytes": 0,
                    "private_peak_sampled_bytes": 0,
                    "os_peak_rss_bytes": 0,
                    "cpu_first_seconds": None,
                    "cpu_last_seconds": None,
                },
            )
            for source, target in (
                ("rss_bytes", "rss_peak_sampled_bytes"),
                ("private_bytes", "private_peak_sampled_bytes"),
                ("os_peak_rss_bytes", "os_peak_rss_bytes"),
            ):
                item[target] = max(item[target], process[source])
            cpu = process["cpu_seconds_since_process_start"]
            if cpu is not None:
                if item["cpu_first_seconds"] is None:
                    item["cpu_first_seconds"] = cpu
                item["cpu_last_seconds"] = cpu
    for item in processes.values():
        item["cpu_observed_delta_seconds"] = (
            None
            if item["cpu_first_seconds"] is None
            else item["cpu_last_seconds"] - item["cpu_first_seconds"]
        )
    return {"processes": list(processes.values()), "disk_sampled_peaks": disk_peaks}


class Sampler:
    def __init__(self, root_pid, data_root, interval=0.5):
        self.root_pid, self.data_root, self.interval = root_pid, data_root, interval
        self.samples = []
        self.stage = "startup"
        self.free_volume_before_bytes = shutil.disk_usage(data_root.parent).free
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.is_set():
            self.samples.append(
                {
                    "monotonic_seconds": time.perf_counter(),
                    "stage": self.stage,
                    "processes": windows_process_tree(self.root_pid),
                    "disk": disk_sizes(self.data_root),
                }
            )
            self.stop.wait(self.interval)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=5)
        return {
            "platform": platform.platform(),
            "cpu_logical": os.cpu_count(),
            "interval_seconds": self.interval,
            "samples": self.samples,
            "summary": resource_summary(self.samples),
            "volume_free_before_bytes": self.free_volume_before_bytes,
            "volume_free_after_bytes": shutil.disk_usage(self.data_root.parent).free,
            "clock": {
                "implementation": time.get_clock_info("perf_counter").implementation,
                "resolution_seconds": time.get_clock_info("perf_counter").resolution,
            },
            "limits": [
                "Owned PID tree only; RSS shared pages must not be summed as unique RAM.",
                "API/parser/worker share the backend tree; roles are not separate allocations.",
                "Snapshots may miss short peaks; OS peak counters are per process to sample time.",
                "GUI native/JS heap NOT_MEASURED unless separately observed with the actual app.",
                "OS/SQLite temp outside app-data NOT_MEASURED.",
                "Host is shared; CPU/I/O and OS cache are not pinned.",
            ],
        }
