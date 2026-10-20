"""Small session task and memory panels shared by the desktop UI modes."""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)


class TaskActivityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Task Activity · This Session")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Background tasks started during this session"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Task", "Status", "Progress"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.table)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        self.details.setPlaceholderText("Select a task to view its result or error.")
        layout.addWidget(self.details)
        self._tasks = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def refresh(self):
        from core.autonomous_worker import get_worker
        selected_id = None
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows and selected_rows[0].row() < len(self._tasks):
            selected_id = self._tasks[selected_rows[0].row()].task_id
        self._tasks = get_worker().get_tasks()[:100]
        self.table.setRowCount(len(self._tasks))
        for row, task in enumerate(self._tasks):
            for col, value in enumerate((task.description, task.status.title(), task.progress)):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        if self._tasks:
            row = next((i for i, task in enumerate(self._tasks) if task.task_id == selected_id), 0)
            self.table.selectRow(row)
        else:
            self.details.setPlainText("No background tasks yet.")

    def _show_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        task = self._tasks[rows[0].row()]
        body = f"{task.description}\n\nStatus: {task.status}\nProgress: {task.progress}"
        if task.result:
            body += f"\n\nResult:\n{task.result}"
        if task.error:
            body += f"\n\nError:\n{task.error}"
        self.details.setPlainText(body)


class MemoryReviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Memory Review")
        self.resize(720, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saved memory · select an entry to review or forget it"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Category", "Key", "Value", "Updated"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addStretch(1)
        forget = QPushButton("Forget Selected")
        forget.clicked.connect(self._forget_selected)
        row.addWidget(forget)
        layout.addLayout(row)
        self._entries = []
        self.refresh()

    def refresh(self):
        from memory.memory_manager import all_entries_for_ui
        self._entries = all_entries_for_ui()
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            for col, field in enumerate(("category", "key", "value", "updated")):
                item = QTableWidgetItem(str(entry.get(field, "")))
                item.setToolTip(str(entry.get(field, "")))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    def _forget_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        entry = self._entries[rows[0].row()]
        answer = QMessageBox.question(
            self, "Forget this memory?",
            f"Remove '{entry['key']}' from {entry['category']} memory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from memory.memory_manager import forget
        forget(entry["key"], entry["category"])
        self.refresh()
