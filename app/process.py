from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class ProcessTree:
    """Windows job object: all descendants die with the worker or its owner."""
    def __init__(self, pid: int):
        self.handle = None
        if os.name != "nt":
            return

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if handle and process and kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) and kernel.AssignProcessToJobObject(handle, process):
            self.handle = handle
            self.kernel = kernel
        elif handle:
            kernel.CloseHandle(handle)
            logging.warning("Job assignment failed: %s", ctypes.get_last_error())
        if process:
            kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class ManagedProcess(QObject):
    event = Signal(dict)
    done = Signal(int)

    def __init__(self, root: Path, job: dict, parent=None):
        super().__init__(parent)
        self.root = root
        self.job_file = root / "data" / "jobs" / (uuid4().hex + ".json")
        self.job_file.write_text(json.dumps({**job, "root": str(root), "guarded": True}, ensure_ascii=False), encoding="utf-8")
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(root))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("DENO_DIR", str(root / "data" / "cache" / "deno"))
        self.process.setProcessEnvironment(env)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["--worker", str(self.job_file)] if getattr(sys, "frozen", False) else [str(root / "main.py"), "--worker", str(self.job_file)])
        self.buffer = b""
        self.tree = None
        self._done = False
        self._cancel_requested = False
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)

    def start(self):
        self.process.start()

    def _started(self):
        self.tree = ProcessTree(self.process.processId())
        if self._cancel_requested:
            if self.tree.handle:
                self.tree.close()
            else:
                self.process.kill()
            return
        self.process.write(b"go\n")

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line.decode("utf-8"))
                if isinstance(event, dict) and "event" in event:
                    self.event.emit(event)
            except (ValueError, UnicodeError):
                logging.warning("Unexpected worker output: %r", line[:300])

    def _stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data.strip():
            logging.warning("Worker stderr: %s", data[-3000:])

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.event.emit({"event": "error", "message": "Не удалось запустить рабочий процесс."})
            self._finished(1)

    def _finished(self, code, *_):
        if self._done:
            return
        self._done = True
        self._read()
        self._stderr()
        if self.tree:
            self.tree.close()
        self.job_file.unlink(missing_ok=True)
        self.done.emit(code)

    def cancel(self):
        self._cancel_requested = True
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        if not self.process.processId():
            # The started handler will stop it before releasing the worker gate.
            return
        if self.tree and self.tree.handle:
            self.tree.close()
        elif os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.process.processId()), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        else:
            self.process.kill()

    def shutdown(self):
        self.cancel()
        self.process.waitForFinished(4000)
