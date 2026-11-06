"""One trusted, sequential timer per runtime; durable domain work remains module-owned."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from .errors import CoreError

if TYPE_CHECKING:
    from .runtime import Runtime

MAX_INTERVAL_SECONDS = 24 * 60 * 60
MAX_MODULE_TASKS = 16
MAX_RUNTIME_TASKS = 64
SHUTDOWN_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class PeriodicTask:
    run: Callable[[Runtime], None]
    interval_seconds: int

    def __post_init__(self):
        if (
            not callable(self.run)
            or type(self.interval_seconds) is not int
            or not 1 <= self.interval_seconds <= MAX_INTERVAL_SECONDS
        ):
            raise CoreError(
                "INVALID_PERIODIC_TASK", "Timer cần callable và chu kỳ nguyên từ 1 đến 86400 giây."
            )


class PeriodicRunner:
    def __init__(self, runtime: Runtime, tasks: Mapping[str, PeriodicTask]):
        if len(tasks) > MAX_RUNTIME_TASKS:
            raise CoreError("PERIODIC_TASK_LIMIT", "Vượt giới hạn timer của ứng dụng.")
        self.runtime = runtime
        self.tasks = MappingProxyType(dict(tasks))
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="cafe-fin-periodic", daemon=True)
        self._lock = threading.Lock()
        self._started = False
        self._state = "NEW"
        self._active_task: str | None = None
        self._task_errors: dict[str, str] = {}
        self._fatal_error: str | None = None
        self._shutdown_error: str | None = None
        self._last_error: str | None = None
        self._runs = dict.fromkeys(self.tasks, 0)
        self._failures = dict.fromkeys(self.tasks, 0)

    def _current_error(self) -> str | None:
        return (
            self._shutdown_error
            or self._fatal_error
            or ("PERIODIC_TASK_FAILED" if self._task_errors else None)
        )

    @property
    def error_code(self) -> str | None:
        with self._lock:
            return self._current_error()

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "running": self.thread.is_alive(),
                "active_task": self._active_task,
                "error_code": self._current_error(),
                "last_error_code": self._last_error,
                "task_errors": dict(self._task_errors),
                "runs": dict(self._runs),
                "failures": dict(self._failures),
            }

    def start(self) -> None:
        with self._lock:
            if self.stop_event.is_set():
                raise CoreError("PERIODIC_CLOSED", "Timer đã dừng.", 503)
            if self._started:
                return
            self._started = True
            self._state = "RUNNING" if self.tasks else "IDLE"
            if not self.tasks:
                return
            try:
                self.thread.start()
            except BaseException:
                self._state = "FAILED"
                self._fatal_error = self._last_error = "PERIODIC_START_FAILED"
                self.stop_event.set()
                raise CoreError(
                    "PERIODIC_START_FAILED", "Không khởi động được timer local.", 503
                ) from None

    def _loop(self) -> None:
        try:
            self._run_loop()
        except BaseException:
            # No callback exception text, paths, payloads or tracebacks escape the timer.
            with self._lock:
                self._state = "FAILED"
                self._fatal_error = self._last_error = "PERIODIC_RUNNER_FAILED"
            self.stop_event.set()
        finally:
            with self._lock:
                self._active_task = None
                if self._state != "FAILED":
                    self._state = "STOPPED"

    def _run_loop(self) -> None:
        started = time.monotonic()
        due = {name: started + task.interval_seconds for name, task in self.tasks.items()}
        while not self.stop_event.is_set():
            if self.stop_event.wait(max(0.0, min(due.values()) - time.monotonic())):
                break
            for name, task in self.tasks.items():
                if self.stop_event.is_set():
                    return
                if due[name] > time.monotonic():
                    continue
                with self._lock:
                    self._active_task = name
                failed = False
                try:
                    task.run(self.runtime)
                except BaseException:
                    failed = True
                finally:
                    with self._lock:
                        self._active_task = None
                        self._runs[name] += 1
                        if failed:
                            self._failures[name] += 1
                            self._task_errors[name] = "PERIODIC_TASK_FAILED"
                            self._last_error = "PERIODIC_TASK_FAILED"
                        else:
                            self._task_errors.pop(name, None)
                # Keep monotonic phase, skip missed intervals, never replay a burst.
                finished = time.monotonic()
                steps = max(1, int((finished - due[name]) // task.interval_seconds) + 1)
                due[name] += steps * task.interval_seconds

    def request_stop(self) -> None:
        """Wake the timer without joining; an active callback may still use the writer."""
        self.stop_event.set()

    def close(self) -> None:
        self.request_stop()
        with self._lock:
            self._state = "STOPPING" if self.thread.is_alive() else "STOPPED"
        if self.thread.ident is not None:
            self.thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        if self.thread.is_alive():
            with self._lock:
                self._shutdown_error = self._last_error = "PERIODIC_SHUTDOWN_TIMEOUT"
            raise CoreError(
                "PERIODIC_SHUTDOWN_TIMEOUT", "Timer chưa dừng tại ranh giới an toàn.", 503
            )
        with self._lock:
            self._state = "STOPPED"
            self._shutdown_error = None
