"""PyQt6 desktop UI for the one-time Python job scheduler."""

from __future__ import annotations

import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QDateTime, QTimer, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDateTimeEdit, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QInputDialog, QComboBox, QStatusBar, QTableWidget, QTableWidgetItem,
    QSplitter, QVBoxLayout, QWidget,
)

from scheduler import JobDefinition, JobState, SchedulerController, discover_conda_environments


TEMPLATE_FILE = Path(__file__).with_name("templates.json")


DARK_STYLESHEET = """
QWidget {
    background-color: #202124;
    color: #e8eaed;
    font-size: 10pt;
}
QMainWindow, QDialog {
    background-color: #202124;
}
QLineEdit, QPlainTextEdit, QDateTimeEdit, QComboBox, QTableWidget {
    background-color: #292a2d;
    color: #e8eaed;
    border: 1px solid #5f6368;
    border-radius: 4px;
    selection-background-color: #3f51b5;
    selection-color: #ffffff;
}
QLineEdit, QDateTimeEdit, QComboBox {
    padding: 5px;
}
QPlainTextEdit {
    padding: 4px;
}
QPushButton {
    background-color: #3c4043;
    color: #e8eaed;
    border: 1px solid #5f6368;
    border-radius: 4px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #4a4d51;
}
QPushButton:pressed {
    background-color: #303134;
}
QHeaderView::section {
    background-color: #303134;
    color: #e8eaed;
    border: 1px solid #5f6368;
    padding: 5px;
}
QTableWidget {
    gridline-color: #3c4043;
    alternate-background-color: #242528;
}
QTableWidget::item {
    padding: 4px;
}
QStatusBar {
    background-color: #292a2d;
    color: #bdc1c6;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #202124;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #5f6368;
    border-radius: 4px;
}
"""


def load_templates() -> list[dict]:
    if not TEMPLATE_FILE.is_file():
        return []
    try:
        data = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def to_qdatetime(value: datetime) -> QDateTime:
    return QDateTime(value.year, value.month, value.day, value.hour, value.minute, value.second)


class JobDialog(QDialog):
    def __init__(self, parent=None, job: Optional[JobDefinition] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Job" if job else "New Job")
        self.resize(620, 520)
        form = QFormLayout()

        template_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.addItem("No template", "")
        for template in load_templates():
            self.template_combo.addItem(template.get("template_name", "Unnamed template"), template)
        load_button = QPushButton("Load")
        save_template_button = QPushButton("Save as template")
        load_button.clicked.connect(self._load_template)
        save_template_button.clicked.connect(self._save_template)
        template_row.addWidget(self.template_combo)
        template_row.addWidget(load_button)
        template_row.addWidget(save_template_button)
        form.addRow("Template", template_row)

        self.name = QLineEdit(job.name if job else "")
        form.addRow("Name", self.name)

        path_row = QHBoxLayout()
        self.script = QLineEdit(job.script_path if job else "")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_script)
        path_row.addWidget(self.script)
        path_row.addWidget(browse)
        form.addRow("Python file", path_row)

        self.working_dir = QLineEdit(job.working_directory if job else "")
        form.addRow("Working directory", self.working_dir)

        self.arguments = QLineEdit(job.script_arguments if job else "")
        form.addRow("Script arguments", self.arguments)

        self.environment = QComboBox()
        for display_name, activation_target in discover_conda_environments():
            self.environment.addItem(display_name, activation_target)
        if job and job.environment:
            index = self.environment.findData(job.environment)
            if index < 0:
                self.environment.addItem(Path(job.environment).name, job.environment)
                index = self.environment.count() - 1
            self.environment.setCurrentIndex(index)
        form.addRow("Python environment", self.environment)

        self.commands = QPlainTextEdit(job.setup_commands if job else "")
        self.commands.setPlaceholderText("Optional Command Prompt setup commands, one per line…")
        self.commands.setMinimumHeight(130)
        form.addRow("Setup commands", self.commands)

        now = QDateTime.currentDateTime()
        self.start = QDateTimeEdit(to_qdatetime(job.start_at) if job else now.addSecs(60))
        self.stop = QDateTimeEdit(to_qdatetime(job.stop_at) if job else now.addSecs(3600))
        for control in (self.start, self.stop):
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        form.addRow("Start time", self.start)
        form.addRow("Stop time", self.stop)

        self.parallel = QCheckBox("Allow this job to run while another job is active")
        self.parallel.setChecked(job.allow_parallel if job else False)
        form.addRow("Concurrency", self.parallel)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._validate_and_accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _load_template(self) -> None:
        template = self.template_combo.currentData()
        if not isinstance(template, dict):
            return
        self.name.setText(template.get("name", ""))
        self.script.setText(template.get("script_path", ""))
        self.working_dir.setText(template.get("working_directory", ""))
        self.arguments.setText(template.get("script_arguments", ""))
        self.commands.setPlainText(template.get("setup_commands", ""))
        self.parallel.setChecked(bool(template.get("allow_parallel", False)))
        index = self.environment.findData(template.get("environment", ""))
        if index >= 0:
            self.environment.setCurrentIndex(index)

    def _save_template(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save template", "Template name", text=self.name.text().strip())
        if not accepted or not name.strip():
            return
        templates = load_templates()
        payload = self.template_payload()
        payload["template_name"] = name.strip()
        templates = [item for item in templates if item.get("template_name") != name.strip()]
        templates.append(payload)
        try:
            TEMPLATE_FILE.write_text(json.dumps(templates, indent=2), encoding="utf-8")
            index = self.template_combo.findText(name.strip())
            if index >= 0:
                self.template_combo.setItemData(index, payload)
            else:
                self.template_combo.addItem(name.strip(), payload)
                index = self.template_combo.count() - 1
            self.template_combo.setCurrentIndex(index)
            QMessageBox.information(self, "Template saved", f"Saved template: {name.strip()}")
        except OSError as exc:
            QMessageBox.critical(self, "Template error", f"Could not save the template:\n{exc}")

    def template_payload(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "script_path": self.script.text().strip(),
            "working_directory": self.working_dir.text().strip(),
            "script_arguments": self.arguments.text().strip(),
            "setup_commands": self.commands.toPlainText(),
            "environment": self.environment.currentData() or "",
            "allow_parallel": self.parallel.isChecked(),
        }

    def _browse_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Python file", "", "Python files (*.py);;All files (*.*)")
        if path:
            self.script.setText(path)
            if not self.working_dir.text().strip():
                self.working_dir.setText(str(Path(path).parent))

    def _validate_and_accept(self) -> None:
        if not self.name.text().strip() or not self.script.text().strip():
            QMessageBox.warning(self, "Incomplete job", "A name and Python file are required.")
            return
        if not Path(self.script.text().strip()).is_file():
            QMessageBox.warning(self, "Invalid Python file", "Select an existing Python file.")
            return
        if self.start.dateTime() >= self.stop.dateTime():
            QMessageBox.warning(self, "Invalid schedule", "The stop time must be after the start time.")
            return
        self.accept()

    def job(self, existing_id: Optional[str] = None) -> JobDefinition:
        return JobDefinition(
            id=existing_id or "",
            name=self.name.text().strip(),
            script_path=self.script.text().strip(),
            setup_commands=self.commands.toPlainText(),
            start_at=self.start.dateTime().toPyDateTime(),
            stop_at=self.stop.dateTime().toPyDateTime(),
            working_directory=self.working_dir.text().strip(),
            script_arguments=self.arguments.text().strip(),
            environment=self.environment.currentData() or "",
            allow_parallel=self.parallel.isChecked(),
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Python Job Scheduler")
        self.resize(1000, 560)
        self.controller = SchedulerController()
        self.controller.job_changed.connect(self.refresh)
        self.logs: dict[str, QPlainTextEdit] = {}
        self.log_dialogs: dict[str, QDialog] = {}
        self.output_job_id: Optional[str] = None
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Start", "Stop", "Status", "PID", "Exit", "Mode"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_job())
        self.output_log = QPlainTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setPlaceholderText("Select a job to view its program output.")
        self.output_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output_log.setMinimumHeight(160)

        toolbar = QHBoxLayout()
        for label, callback in (("New", self.new_job), ("Edit", self.edit_job), ("Delete", self.delete_job), ("Run now", self.run_now), ("Stop", self.stop_job), ("View logs", self.view_logs)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        output_panel = QWidget()
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(0, 4, 0, 0)
        output_layout.addWidget(QLabel("Program output"))
        output_layout.addWidget(self.output_log)
        splitter.addWidget(output_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 260])
        layout.addWidget(splitter)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1000)
        self.log_timer.timeout.connect(self.update_log_view)
        self.log_timer.start()

    def selected_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def new_job(self) -> None:
        dialog = JobDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            job = dialog.job()
            job.id = __import__("uuid").uuid4().hex
            self.controller.add_job(job)

    def edit_job(self) -> None:
        job_id = self.selected_id()
        job = self.controller.jobs.get(job_id or "")
        if not job or job_id in self.controller.runners:
            return
        dialog = JobDialog(self, job)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.update_job(dialog.job(job.id))

    def delete_job(self) -> None:
        job_id = self.selected_id()
        if job_id:
            self.controller.remove_job(job_id)

    def run_now(self) -> None:
        job_id = self.selected_id()
        if job_id:
            self.controller.run_now(job_id)

    def stop_job(self) -> None:
        job_id = self.selected_id()
        if job_id:
            self.controller.stop_job(job_id)

    def view_logs(self) -> None:
        job_id = self.selected_id()
        job = self.controller.jobs.get(job_id or "")
        if not job:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Logs — {job.name}")
        dialog.resize(800, 500)
        text = QPlainTextEdit(job.log)
        text.setReadOnly(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text)
        self.logs[job.id] = text
        self.log_dialogs[job.id] = dialog
        dialog.finished.connect(lambda: self.logs.pop(job.id, None))
        dialog.finished.connect(lambda: self.log_dialogs.pop(job.id, None))
        dialog.show()

    def update_log_view(self) -> None:
        # Follow the first running job in table/insertion order, independently
        # of which row the user has selected for editing or control actions.
        job = next((item for item in self.controller.jobs.values() if item.state is JobState.RUNNING), None)
        job_id = job.id if job else None
        if job_id != self.output_job_id:
            self.output_job_id = job_id
            self.output_log.clear()
            if job:
                self.output_log.setPlaceholderText(f"Waiting for output from {job.name}…")
            else:
                self.output_log.setPlaceholderText("No job is currently running.")
        text = job.log if job else ""
        if self.output_log.toPlainText() != text:
            self.output_log.setPlainText(text)
            cursor = self.output_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.output_log.setTextCursor(cursor)

    def refresh(self, job_id: str = "") -> None:
        self.table.setRowCount(0)
        for row, job in enumerate(self.controller.jobs.values()):
            self.table.insertRow(row)
            values = [job.name, job.start_at.strftime("%Y-%m-%d %H:%M:%S"), job.stop_at.strftime("%Y-%m-%d %H:%M:%S"), job.state.value, str(self.controller.runners[job.id].process.pid) if job.id in self.controller.runners and self.controller.runners[job.id].process else "", "" if job.exit_code is None else str(job.exit_code), "Parallel" if job.allow_parallel else "Queued"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, job.id)
                self.table.setItem(row, column, item)
        self.statusBar().showMessage(f"{len(self.controller.jobs)} job(s)")
        self.update_log_view()

    def closeEvent(self, event: QCloseEvent) -> None:
        answer = QMessageBox.question(
            self,
            "Exit Python Job Scheduler",
            "Are you sure you want to exit? All scheduled tasks will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.clear_jobs()
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainWindow()
    window.show()
    window.refresh()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
