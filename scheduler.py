"""Core scheduling and Windows process-running logic for the desktop scheduler."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class JobState(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    STOPPED = "Stopped"
    SKIPPED = "Skipped"


@dataclass
class JobDefinition:
    name: str
    script_path: str
    setup_commands: str
    start_at: datetime
    stop_at: datetime
    working_directory: str = ""
    script_arguments: str = ""
    environment: str = ""
    allow_parallel: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: JobState = JobState.QUEUED
    exit_code: Optional[int] = None
    log: str = ""
    created_at: datetime = field(default_factory=datetime.now)


def build_command(job: JobDefinition) -> str:
    """Build the cmd.exe body while keeping user-entered setup commands intact."""
    commands = []
    if job.environment:
        conda_bat = find_conda_bat()
        if conda_bat:
            commands.append(f'call "{conda_bat}" activate "{job.environment}"')
        else:
            commands.append(f'call conda activate "{job.environment}"')
    setup = job.setup_commands.rstrip()
    if setup:
        # cmd.exe can stop processing subsequent lines after CALLing a batch
        # file, so make each entered line an explicit command separator.
        setup = setup.replace("\r\n", "\n").replace("\r", "\n")
        commands.extend(line.strip() for line in setup.split("\n") if line.strip())
    launch = f'python -u "{job.script_path}"'
    if job.script_arguments.strip():
        launch += f" {job.script_arguments.strip()}"
    commands.append(launch)
    return " & ".join(commands)


def find_conda_bat() -> str:
    """Find the activation script used by cmd.exe on this Windows installation."""
    candidates = []
    conda_exe = os.environ.get("CONDA_EXE", "")
    if conda_exe:
        exe_path = Path(conda_exe)
        candidates.append(exe_path.parent / "conda.bat")
        candidates.append(exe_path.parent.parent / "condabin" / "conda.bat")
    found = shutil.which("conda")
    if found:
        found_path = Path(found)
        candidates.extend([found_path, found_path.parent.parent / "condabin" / "conda.bat"])
    python_path = Path(sys.executable)
    candidates.extend([
        python_path.parent / "condabin" / "conda.bat",
        python_path.parent.parent / "condabin" / "conda.bat",
    ])
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".bat":
            return str(candidate)
    return ""


def discover_conda_environments() -> list[tuple[str, str]]:
    """Return (display name, activation target) entries, including only usable Conda envs."""
    result = [("Default Python", "")]
    conda = os.environ.get("CONDA_EXE", "") or shutil.which("conda")
    if not conda:
        return result
    try:
        completed = subprocess.run(
            [conda, "env", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        data = json.loads(completed.stdout)
        used_names = {display for display, _ in result}
        for prefix in data.get("envs", []):
            path = Path(prefix)
            name = path.name
            if name in used_names:
                name = f"{name} ({path.parent})"
            if not any(target == str(path) for _, target in result):
                result.append((name, str(path)))
                used_names.add(name)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return result


class JobRunner(QObject):
    output = pyqtSignal(str, str)
    finished = pyqtSignal(str, int, bool)

    def __init__(self, job: JobDefinition) -> None:
        super().__init__()
        self.job = job
        self.process: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._lock = threading.Lock()

    def start(self) -> None:
        command = build_command(self.job)
        cwd = self.job.working_directory or str(Path(self.job.script_path).parent)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            # Passing the complete cmd.exe command line as a string preserves
            # the quotes around paths. Passing it as a list makes Windows
            # escape those quotes before cmd.exe sees them.
            command_line = "cmd.exe /d /s /c " + command
            self.process = subprocess.Popen(
                command_line,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except Exception as exc:
            self.output.emit(self.job.id, f"[launcher error] {exc}\n")
            self.finished.emit(self.job.id, -1, False)
            return

        threading.Thread(target=self._read_stream, args=(self.process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(self.process.stderr, "stderr"), daemon=True).start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _read_stream(self, stream, channel: str) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            if line:
                self.output.emit(self.job.id, line)
        stream.close()

    def _wait(self) -> None:
        assert self.process is not None
        code = self.process.wait()
        with self._lock:
            stopped = self._stop_requested
        self.finished.emit(self.job.id, code, stopped)

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
        process = self.process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.kill()


class SchedulerController(QObject):
    job_changed = pyqtSignal(str)
    log_received = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.jobs: Dict[str, JobDefinition] = {}
        self.runners: Dict[str, JobRunner] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def add_job(self, job: JobDefinition) -> None:
        if datetime.now() >= job.start_at:
            job.state = JobState.SKIPPED
        self.jobs[job.id] = job
        self.job_changed.emit(job.id)

    def update_job(self, job: JobDefinition) -> None:
        if job.id in self.jobs and job.id not in self.runners:
            self.jobs[job.id] = job
            self.job_changed.emit(job.id)

    def remove_job(self, job_id: str) -> None:
        if job_id in self.runners:
            self.stop_job(job_id)
        self.jobs.pop(job_id, None)
        self.job_changed.emit(job_id)

    def run_now(self, job_id: str) -> None:
        if job_id in self.runners:
            return
        job = self.jobs.get(job_id)
        if job and job.state in (JobState.QUEUED, JobState.SKIPPED, JobState.COMPLETED, JobState.FAILED, JobState.STOPPED):
            self._launch(job)

    def stop_job(self, job_id: str) -> None:
        runner = self.runners.get(job_id)
        if runner:
            runner.stop()

    def stop_all(self) -> None:
        for runner in list(self.runners.values()):
            runner.stop()

    def clear_jobs(self) -> None:
        """Stop active jobs and remove every scheduled job from this session."""
        self.stop_all()
        self.jobs.clear()
        self.job_changed.emit("")

    def _tick(self) -> None:
        now = datetime.now()
        for job in list(self.jobs.values()):
            if job.id in self.runners:
                if now >= job.stop_at:
                    self.stop_job(job.id)
                continue
            if job.state != JobState.QUEUED:
                continue
            if now >= job.stop_at:
                job.state = JobState.SKIPPED
                self.job_changed.emit(job.id)
            elif now >= job.start_at:
                if job.allow_parallel or not self.runners:
                    self._launch(job)

    def _launch(self, job: JobDefinition) -> None:
        job.state = JobState.RUNNING
        job.exit_code = None
        job.log = ""
        runner = JobRunner(job)
        runner.output.connect(self._on_output)
        runner.finished.connect(self._on_finished)
        self.runners[job.id] = runner
        self.job_changed.emit(job.id)
        threading.Thread(target=runner.start, daemon=True).start()

    def _on_output(self, job_id: str, text: str) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.log += text
            self.log_received.emit(job_id, text)

    def _on_finished(self, job_id: str, exit_code: int, stopped: bool) -> None:
        job = self.jobs.get(job_id)
        self.runners.pop(job_id, None)
        if not job:
            return
        job.exit_code = exit_code
        if stopped:
            job.state = JobState.STOPPED
        elif exit_code == 0:
            job.state = JobState.COMPLETED
        else:
            job.state = JobState.FAILED
        self.job_changed.emit(job_id)
