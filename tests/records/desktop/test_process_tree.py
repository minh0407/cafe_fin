"""Real Windows processes: private containment and bounded inherited-pipe cleanup."""

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from . import process_tree

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows JobObject evidence only")


def line_with_timeout(stream):
    output = queue.Queue(maxsize=1)
    thread = threading.Thread(target=lambda: output.put(stream.readline()), daemon=True)
    thread.start()
    return output.get(timeout=10)


def close_streams(process):
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()


@pytest.mark.parametrize("early_exit", [True, False])
def test_descendant_and_pipe_cleanup_after_root_exit_or_timeout(tmp_path, early_exit):
    code = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr); "
        "print(child.pid,flush=True); " + ("sys.exit(0)" if early_exit else "time.sleep(60)")
    )
    process = process_tree.launch_private(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        env=dict(os.environ),
    )
    child_handle = None
    reader = None
    kernel = process_tree._kernel()
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    try:
        child_pid = int(line_with_timeout(process.stdout))
        child_handle = kernel.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
        assert child_handle
        assert kernel.WaitForSingleObject(child_handle, 0) == 258  # WAIT_TIMEOUT
        reader = threading.Thread(target=process.stderr.read, daemon=True)
        reader.start()
        if early_exit:
            assert process.wait(timeout=10) == 0
        else:
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.05)
        assert reader.is_alive(), "descendant should still hold inherited stderr"
        started = time.monotonic()
        process.close_tree(timeout=10)
        assert time.monotonic() - started < 12
        assert kernel.WaitForSingleObject(child_handle, 0) == 0  # WAIT_OBJECT_0
        reader.join(timeout=2)
        assert not reader.is_alive(), "cleanup must release the inherited pipe"
        process.close_tree(timeout=0)  # idempotent
    finally:
        process.close_tree(timeout=10)
        if child_handle:
            kernel.CloseHandle(child_handle)
        if reader:
            reader.join(timeout=2)
        close_streams(process)


def test_failure_before_resume_never_executes_child_code(tmp_path, monkeypatch):
    marker = tmp_path / "must-not-exist.txt"

    def deny_resume(kernel, pid):
        raise RuntimeError("synthetic_launch_failure")

    monkeypatch.setattr(process_tree, "_resume_primary_thread", deny_resume)
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
    with pytest.raises(RuntimeError, match="^synthetic_launch_failure$"):
        process_tree.launch_private(
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=dict(os.environ),
        )
    assert not marker.exists()
