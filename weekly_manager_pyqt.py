# weekly_manager_pyqt.py
# Python 3.10+
# Benoetigt: PyQt6

import json
import os
import sys

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyleFactory,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


WEEKDAY_SHORT_DE = {
    1: "Mo",
    2: "Di",
    3: "Mi",
    4: "Do",
    5: "Fr",
    6: "Sa",
    7: "So",
}


def normalize_iso_date(value: str, fallback: QDate | None = None) -> str:
    fallback = fallback or QDate.currentDate()
    qd = QDate.fromString(str(value), Qt.DateFormat.ISODate)
    if not qd.isValid():
        qd = fallback
    return qd.toString(Qt.DateFormat.ISODate)


def normalize_todos(raw_todos) -> list[dict]:
    todos = []
    if not isinstance(raw_todos, list):
        return todos

    for raw in raw_todos:
        if isinstance(raw, dict):
            text = str(raw.get("text", "")).strip()
            if text:
                todos.append({"text": text, "checked": bool(raw.get("checked", False))})
        elif isinstance(raw, str):
            text = raw.strip()
            if text:
                todos.append({"text": text, "checked": False})
    return todos


def make_empty_weekly(date_str: str, planned: str = "") -> dict:
    return {
        "date": normalize_iso_date(date_str),
        "title": "",
        "planned": planned,
        "done": "",
        "next_planned": "",
    }


def make_empty_project(name: str, start_date: str, end_date: str) -> dict:
    return {
        "name": name.strip() or "Projekt",
        "start_date": normalize_iso_date(start_date),
        "end_date": normalize_iso_date(end_date),
        "project_todos": [],
        "weeklies": [],
    }


def _merge_old_todo_buckets(raw_project: dict) -> list[dict]:
    combined = []
    seen = set()

    for key in ["project_todos", "project_todos_active", "project_todos_later"]:
        for todo in normalize_todos(raw_project.get(key, [])):
            todo_key = todo["text"].strip().lower()
            if todo_key and todo_key not in seen:
                seen.add(todo_key)
                combined.append(todo)
    return combined


def _clean_weekly(raw_weekly: dict) -> dict:
    return {
        "date": normalize_iso_date(raw_weekly.get("date", QDate.currentDate().toString(Qt.DateFormat.ISODate))),
        "title": str(raw_weekly.get("title", "")),
        "planned": str(raw_weekly.get("planned", "")),
        "done": str(raw_weekly.get("done", "")),
        "next_planned": str(raw_weekly.get("next_planned", "")),
    }


def _clean_project(raw_project: dict, fallback_name: str) -> dict:
    project_name = str(raw_project.get("name", fallback_name)).strip() or fallback_name
    start_date = normalize_iso_date(raw_project.get("start_date", QDate.currentDate().toString(Qt.DateFormat.ISODate)))
    end_date = normalize_iso_date(raw_project.get("end_date", QDate.currentDate().addDays(90).toString(Qt.DateFormat.ISODate)))

    raw_weeklies = raw_project.get("weeklies", [])
    if not isinstance(raw_weeklies, list):
        raw_weeklies = []

    weeklies = []
    for raw_weekly in raw_weeklies:
        if isinstance(raw_weekly, dict):
            weeklies.append(_clean_weekly(raw_weekly))

    return {
        "name": project_name,
        "start_date": start_date,
        "end_date": end_date,
        "project_todos": _merge_old_todo_buckets(raw_project),
        "weeklies": weeklies,
    }


def validate_data(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON-Wurzel muss ein Objekt sein.")

    students_raw = data.get("students", {})
    if not isinstance(students_raw, dict):
        students_raw = {}

    cleaned = {"version": 4, "students": {}}

    for student_name, student_value in students_raw.items():
        if not isinstance(student_name, str):
            continue

        projects = []

        # Altformat: students[name] = [weeklies]
        if isinstance(student_value, list):
            projects.append(
                _clean_project(
                    {
                        "name": "Standardprojekt",
                        "start_date": QDate.currentDate().toString(Qt.DateFormat.ISODate),
                        "end_date": QDate.currentDate().addDays(90).toString(Qt.DateFormat.ISODate),
                        "weeklies": student_value,
                    },
                    "Standardprojekt",
                )
            )
        elif isinstance(student_value, dict):
            raw_projects = student_value.get("projects")
            if isinstance(raw_projects, list):
                for idx, raw_project in enumerate(raw_projects):
                    if isinstance(raw_project, dict):
                        projects.append(_clean_project(raw_project, f"Projekt {idx + 1}"))
            elif isinstance(student_value.get("weeklies"), list):
                projects.append(
                    _clean_project(
                        {
                            "name": student_value.get("name", "Standardprojekt"),
                            "start_date": student_value.get("start_date", QDate.currentDate().toString(Qt.DateFormat.ISODate)),
                            "end_date": student_value.get("end_date", QDate.currentDate().addDays(90).toString(Qt.DateFormat.ISODate)),
                            "weeklies": student_value.get("weeklies", []),
                            "project_todos": student_value.get("project_todos", []),
                            "project_todos_active": student_value.get("project_todos_active", []),
                            "project_todos_later": student_value.get("project_todos_later", []),
                        },
                        "Standardprojekt",
                    )
                )

        cleaned["students"][student_name] = {"projects": projects}

    return cleaned


class TaskListWidget(QWidget):
    tasksChanged = pyqtSignal()

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self._loading = False

        self.list_widget = QListWidget()
        self.list_widget.itemChanged.connect(self._on_item_changed)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(placeholder)
        self.btn_add = QPushButton("Hinzufuegen")
        self.btn_remove_checked = QPushButton("Erledigte entfernen")

        self.btn_add.clicked.connect(self._add_from_input)
        self.input_edit.returnPressed.connect(self._add_from_input)
        self.btn_remove_checked.clicked.connect(self._remove_checked)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.list_widget, 1)

        row = QHBoxLayout()
        row.addWidget(self.input_edit, 1)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove_checked)
        root.addLayout(row)

    def _create_item(self, text: str, checked: bool) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
        )
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def set_tasks(self, tasks: list[dict]):
        self._loading = True
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for task in tasks:
            text = str(task.get("text", "")).strip()
            if text:
                self.list_widget.addItem(self._create_item(text, bool(task.get("checked", False))))
        self.list_widget.blockSignals(False)
        self._loading = False

    def get_tasks(self) -> list[dict]:
        tasks = []
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            text = item.text().strip()
            if text:
                tasks.append({"text": text, "checked": item.checkState() == Qt.CheckState.Checked})
        return tasks

    def _add_from_input(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        self.list_widget.addItem(self._create_item(text, False))
        self.input_edit.clear()
        self.tasksChanged.emit()

    def _remove_checked(self):
        for idx in reversed(range(self.list_widget.count())):
            if self.list_widget.item(idx).checkState() == Qt.CheckState.Checked:
                self.list_widget.takeItem(idx)
        self.tasksChanged.emit()

    def _on_item_changed(self, _item: QListWidgetItem):
        if not self._loading:
            self.tasksChanged.emit()


class DeselectableListWidget(QListWidget):
    def mousePressEvent(self, event):
        clicked_item = self.itemAt(event.pos())
        if clicked_item is not None and clicked_item == self.currentItem() and clicked_item.isSelected():
            self.clearSelection()
            self.setCurrentItem(None)
            event.accept()
            return
        super().mousePressEvent(event)


class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QLabel(title)
        header.setObjectName("CardTitle")
        layout.addWidget(header)

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(10)
        layout.addLayout(self.content_layout)


class WeeklyManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Studierenden-Weeklies Manager")
        self.resize(1460, 900)

        self.data = {"version": 4, "students": {}}
        self.current_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weeklies.json")
        self.default_open_dir = os.path.dirname(os.path.abspath(__file__))

        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None

        self._loading_ui = False
        self._dirty = False
        self._autosave_enabled = True
        self._theme_mode = self._detect_system_theme()

        self._build_ui()
        self._apply_theme(self._theme_mode)
        self._connect_signals()
        self._load_or_create_default_file()
        self._set_saved_state(saved=True)
        self._update_window_title()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setStatusBar(QStatusBar(self))

        toolbar = QToolBar("Hauptleiste")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_open = QAction("Laden", self)
        toolbar.addAction(self.act_open)
        toolbar.addSeparator()

        self.theme_toggle_btn = QPushButton()
        self.theme_toggle_btn.setCheckable(True)
        self.theme_toggle_btn.setChecked(self._theme_mode == "dark")
        self._update_theme_toggle_button()
        toolbar.addWidget(self.theme_toggle_btn)
        toolbar.addSeparator()

        self.act_add_student = QAction("Studierende:n hinzufuegen", self)
        self.act_remove_student = QAction("Studierende:n entfernen", self)
        toolbar.addAction(self.act_add_student)
        toolbar.addAction(self.act_remove_student)
        toolbar.addSeparator()

        self.act_add_project = QAction("Projekt hinzufuegen", self)
        self.act_remove_project = QAction("Projekt entfernen", self)
        toolbar.addAction(self.act_add_project)
        toolbar.addAction(self.act_remove_project)
        toolbar.addSeparator()

        self.act_new_weekly = QAction("Neues Weekly", self)
        self.act_delete_weekly = QAction("Weekly loeschen", self)
        toolbar.addAction(self.act_new_weekly)
        toolbar.addAction(self.act_delete_weekly)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        left_card = Card("Studierende")
        splitter.addWidget(left_card)

        self.student_list = DeselectableListWidget()
        self.student_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        left_card.content_layout.addWidget(self.student_list, 1)

        student_btn_row = QHBoxLayout()
        self.btn_add_student = QPushButton("+ Hinzufuegen")
        self.btn_remove_student = QPushButton("- Entfernen")
        student_btn_row.addWidget(self.btn_add_student)
        student_btn_row.addWidget(self.btn_remove_student)
        left_card.content_layout.addLayout(student_btn_row)

        middle_card = Card("Projekte und Weeklies")
        splitter.addWidget(middle_card)

        self.project_summary_label = QLabel("Keine Studierenden ausgewaehlt")
        self.project_summary_label.setObjectName("SubtleLabel")
        middle_card.content_layout.addWidget(self.project_summary_label)

        self.project_list = DeselectableListWidget()
        self.project_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        middle_card.content_layout.addWidget(self.project_list, 1)

        project_btn_row = QHBoxLayout()
        self.btn_add_project = QPushButton("Neues Projekt")
        self.btn_remove_project = QPushButton("Projekt loeschen")
        project_btn_row.addWidget(self.btn_add_project)
        project_btn_row.addWidget(self.btn_remove_project)
        middle_card.content_layout.addLayout(project_btn_row)

        self.weekly_summary_label = QLabel("Kein Projekt ausgewaehlt")
        self.weekly_summary_label.setObjectName("SubtleLabel")
        middle_card.content_layout.addWidget(self.weekly_summary_label)

        self.weekly_list = DeselectableListWidget()
        self.weekly_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        middle_card.content_layout.addWidget(self.weekly_list, 1)

        weekly_btn_row = QHBoxLayout()
        self.btn_new_weekly = QPushButton("Neues Weekly")
        self.btn_delete_weekly = QPushButton("Weekly loeschen")
        self.btn_project_overview = QPushButton("Projektansicht")
        weekly_btn_row.addWidget(self.btn_new_weekly)
        weekly_btn_row.addWidget(self.btn_delete_weekly)
        weekly_btn_row.addWidget(self.btn_project_overview)
        middle_card.content_layout.addLayout(weekly_btn_row)

        right_card = Card("Projekt / Weekly")
        splitter.addWidget(right_card)

        project_meta_row = QHBoxLayout()
        project_meta_row.addWidget(QLabel("Projektname"))
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("Projektname")
        project_meta_row.addWidget(self.project_name_edit, 1)
        project_meta_row.addWidget(QLabel("Start"))
        self.project_start_edit = QDateEdit()
        self.project_start_edit.setCalendarPopup(True)
        self.project_start_edit.setDisplayFormat("dd.MM.yyyy")
        project_meta_row.addWidget(self.project_start_edit)
        project_meta_row.addWidget(QLabel("Ende"))
        self.project_end_edit = QDateEdit()
        self.project_end_edit.setCalendarPopup(True)
        self.project_end_edit.setDisplayFormat("dd.MM.yyyy")
        project_meta_row.addWidget(self.project_end_edit)
        right_card.content_layout.addLayout(project_meta_row)

        self.project_progress_label = QLabel("Projektfortschritt: -")
        self.project_progress_label.setObjectName("SubtleLabel")
        right_card.content_layout.addWidget(self.project_progress_label)

        self.project_progress = QProgressBar()
        self.project_progress.setRange(0, 100)
        self.project_progress.setTextVisible(True)
        self.project_progress.setFormat("%p%")
        self.project_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_card.content_layout.addWidget(self.project_progress)

        self.grp_project_todos = QGroupBox("Projekt TODOs")
        project_todo_layout = QVBoxLayout(self.grp_project_todos)
        self.project_todos_widget = TaskListWidget("Neue TODO ...")
        project_todo_layout.addWidget(self.project_todos_widget)
        right_card.content_layout.addWidget(self.grp_project_todos, 1)

        self.grp_todo_context = QGroupBox("Offene TODOs (Kontextansicht)")
        todo_context_layout = QVBoxLayout(self.grp_todo_context)
        self.todo_context_label = QLabel("Kontext: Gesamt")
        self.todo_context_label.setObjectName("SubtleLabel")
        self.todo_context_list = QListWidget()
        self.todo_context_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        todo_context_layout.addWidget(self.todo_context_label)
        todo_context_layout.addWidget(self.todo_context_list, 1)
        right_card.content_layout.addWidget(self.grp_todo_context, 1)

        weekly_meta_row = QHBoxLayout()
        weekly_meta_row.addWidget(QLabel("Weekly-Titel"))
        self.weekly_title_edit = QLineEdit()
        self.weekly_title_edit.setPlaceholderText("z. B. Numerik Uebungsblatt 3")
        weekly_meta_row.addWidget(self.weekly_title_edit, 1)
        weekly_meta_row.addWidget(QLabel("Datum"))
        self.weekly_date_edit = QDateEdit()
        self.weekly_date_edit.setCalendarPopup(True)
        self.weekly_date_edit.setDisplayFormat("dd.MM.yyyy")
        weekly_meta_row.addWidget(self.weekly_date_edit)
        right_card.content_layout.addLayout(weekly_meta_row)

        self.grp_planned = QGroupBox("Was war geplant?")
        planned_layout = QVBoxLayout(self.grp_planned)
        self.txt_planned = QTextEdit()
        planned_layout.addWidget(self.txt_planned)
        right_card.content_layout.addWidget(self.grp_planned, 1)

        self.grp_done = QGroupBox("Was wurde gemacht?")
        done_layout = QVBoxLayout(self.grp_done)
        self.txt_done = QTextEdit()
        done_layout.addWidget(self.txt_done)
        right_card.content_layout.addWidget(self.grp_done, 1)

        self.grp_next = QGroupBox("Was ist geplant?")
        next_layout = QVBoxLayout(self.grp_next)
        self.txt_next = QTextEdit()
        next_layout.addWidget(self.txt_next)
        right_card.content_layout.addWidget(self.grp_next, 1)

        splitter.setSizes([230, 400, 830])

        self._set_project_fields_enabled(False)
        self._set_weekly_editor_enabled(False)

    def _connect_signals(self):
        self.act_open.triggered.connect(self.load_json_dialog)
        self.theme_toggle_btn.toggled.connect(self._on_theme_toggled)
        self.act_add_student.triggered.connect(self.add_student)
        self.act_remove_student.triggered.connect(self.remove_student)
        self.act_add_project.triggered.connect(self.add_project)
        self.act_remove_project.triggered.connect(self.remove_project)
        self.act_new_weekly.triggered.connect(self.add_weekly)
        self.act_delete_weekly.triggered.connect(self.delete_weekly)

        self.btn_add_student.clicked.connect(self.add_student)
        self.btn_remove_student.clicked.connect(self.remove_student)
        self.btn_add_project.clicked.connect(self.add_project)
        self.btn_remove_project.clicked.connect(self.remove_project)
        self.btn_new_weekly.clicked.connect(self.add_weekly)
        self.btn_delete_weekly.clicked.connect(self.delete_weekly)
        self.btn_project_overview.clicked.connect(self._switch_to_project_overview)

        self.student_list.currentItemChanged.connect(self.on_student_changed)
        self.project_list.currentItemChanged.connect(self.on_project_changed)
        self.weekly_list.currentItemChanged.connect(self.on_weekly_changed)

        self.project_name_edit.textChanged.connect(self._on_project_fields_changed)
        self.project_start_edit.dateChanged.connect(self._on_project_fields_changed)
        self.project_end_edit.dateChanged.connect(self._on_project_fields_changed)
        self.project_todos_widget.tasksChanged.connect(self._on_project_todos_changed)

        self.weekly_title_edit.textChanged.connect(self._on_weekly_fields_changed)
        self.weekly_date_edit.dateChanged.connect(self._on_weekly_fields_changed)
        self.txt_planned.textChanged.connect(self._on_weekly_fields_changed)
        self.txt_done.textChanged.connect(self._on_weekly_fields_changed)
        self.txt_next.textChanged.connect(self._on_weekly_fields_changed)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _detect_system_theme(self) -> str:
        try:
            scheme = QApplication.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
        except Exception:
            pass

        window_color = QApplication.palette().color(QPalette.ColorRole.Window)
        return "dark" if window_color.lightness() < 128 else "light"

    def _on_theme_toggled(self, checked: bool):
        self._theme_mode = "dark" if checked else "light"
        self._apply_theme(self._theme_mode)
        self._update_theme_toggle_button()

    def _update_theme_toggle_button(self):
        if self.theme_toggle_btn.isChecked():
            self.theme_toggle_btn.setText("Dark aktiv")
            self.theme_toggle_btn.setToolTip("Zu Light wechseln")
        else:
            self.theme_toggle_btn.setText("Light aktiv")
            self.theme_toggle_btn.setToolTip("Zu Dark wechseln")

    def _apply_theme(self, mode: str):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        if mode == "dark":
            colors = {
                "bg": "#0f172a",
                "surface": "#111827",
                "surface_alt": "#1f2937",
                "border": "#334155",
                "text": "#e5e7eb",
                "subtle": "#94a3b8",
                "accent": "#3b82f6",
                "accent_border": "#1d4ed8",
                "hover": "#1e293b",
                "selected": "#1d4ed8",
            }
        else:
            colors = {
                "bg": "#f3f6fb",
                "surface": "#ffffff",
                "surface_alt": "#fbfcff",
                "border": "#e3e8f0",
                "text": "#1f2a37",
                "subtle": "#5b6b7a",
                "accent": "#2563eb",
                "accent_border": "#1d4ed8",
                "hover": "#eef3ff",
                "selected": "#dbeafe",
            }

        self.setStyleSheet(
            f"""
            QMainWindow {{ background: {colors['bg']}; }}
            QWidget {{ color: {colors['text']}; }}
            QToolBar {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                spacing: 6px;
                padding: 6px;
                border-radius: 10px;
            }}
            QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QToolButton:hover {{
                background: {colors['hover']};
                border: 1px solid {colors['border']};
            }}
            QLabel#SubtleLabel {{ color: {colors['subtle']}; }}
            QFrame#Card {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 14px;
            }}
            QLabel#CardTitle {{
                font-size: 15px;
                font-weight: 700;
                color: {colors['text']};
                padding-bottom: 4px;
            }}
            QListWidget {{
                background: {colors['surface_alt']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 6px;
            }}
            QListWidget::item {{ border-radius: 8px; padding: 8px; margin: 2px 0px; }}
            QListWidget::item:selected {{
                background: {colors['selected']};
                border: 1px solid {colors['accent_border']};
            }}
            QListWidget::item:hover:!selected {{ background: {colors['hover']}; }}
            QPushButton {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                background: {colors['hover']};
                border-color: {colors['accent_border']};
            }}
            QPushButton:disabled {{
                color: {colors['subtle']};
                background: {colors['surface_alt']};
                border-color: {colors['border']};
            }}
            QTextEdit, QDateEdit, QLineEdit {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 6px;
            }}
            QProgressBar {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                min-height: 24px;
                padding: 0px;
                text-align: center;
            }}
            QTextEdit:focus, QDateEdit:focus, QLineEdit:focus {{
                border: 1px solid {colors['accent']};
            }}
            QProgressBar::chunk {{
                background: {colors['accent']};
                border-radius: 8px;
            }}
            QGroupBox {{
                font-weight: 600;
                border: 1px solid {colors['border']};
                border-radius: 12px;
                margin-top: 8px;
                background: {colors['surface_alt']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }}
            QStatusBar {{
                background: {colors['surface']};
                border-top: 1px solid {colors['border']};
            }}
        """
        )

    # ------------------------------------------------------------------
    # State / helpers
    # ------------------------------------------------------------------
    def _set_saved_state(self, saved: bool):
        self._dirty = not saved
        self.statusBar().showMessage("Alle Aenderungen gespeichert" if saved else "Ungespeicherte Aenderungen")
        self._update_window_title()

    def _update_window_title(self):
        filename = os.path.basename(self.current_file) if self.current_file else "Unbenannt"
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"Studierenden-Weeklies Manager - {filename}{dirty}")

    def _mark_dirty(self):
        if not self._loading_ui:
            self._set_saved_state(saved=False)

    def _on_data_changed(self):
        if self._loading_ui:
            return
        self._mark_dirty()
        if self._autosave_enabled:
            self._save_to_current_file()

    def _set_project_fields_enabled(self, enabled: bool):
        self.project_name_edit.setEnabled(enabled)
        self.project_start_edit.setEnabled(enabled)
        self.project_end_edit.setEnabled(enabled)
        self.project_progress.setEnabled(enabled)
        self.project_todos_widget.setEnabled(enabled)
        self.btn_project_overview.setEnabled(enabled)

    def _set_weekly_editor_enabled(self, enabled: bool):
        self.weekly_title_edit.setEnabled(enabled)
        self.weekly_date_edit.setEnabled(enabled)
        self.txt_planned.setEnabled(enabled)
        self.txt_done.setEnabled(enabled)
        self.txt_next.setEnabled(enabled)

    def _current_student_entry(self):
        if self.current_student is None:
            return None
        entry = self.data["students"].get(self.current_student)
        return entry if isinstance(entry, dict) else None

    def _current_student_projects(self):
        entry = self._current_student_entry()
        if entry is None:
            return None
        projects = entry.get("projects", [])
        return projects if isinstance(projects, list) else None

    def _current_project(self):
        projects = self._current_student_projects()
        if projects is None or self.current_project_index is None:
            return None
        if not (0 <= self.current_project_index < len(projects)):
            return None
        return projects[self.current_project_index]

    def _current_weeklies(self):
        project = self._current_project()
        if project is None:
            return None
        weeklies = project.get("weeklies", [])
        return weeklies if isinstance(weeklies, list) else None

    def _sync_action_states(self):
        has_student = self.current_student is not None
        has_project = self._current_project() is not None

        weeklies = self._current_weeklies()
        has_weekly = (
            weeklies is not None
            and self.current_weekly_index is not None
            and 0 <= self.current_weekly_index < len(weeklies)
        )

        self.btn_add_project.setEnabled(has_student)
        self.act_add_project.setEnabled(has_student)

        self.btn_remove_project.setEnabled(has_project)
        self.act_remove_project.setEnabled(has_project)
        self.btn_new_weekly.setEnabled(has_project)
        self.act_new_weekly.setEnabled(has_project)
        self.btn_project_overview.setEnabled(has_project)

        self.btn_delete_weekly.setEnabled(has_weekly)
        self.act_delete_weekly.setEnabled(has_weekly)

    def _weekly_list_text(self, weekly: dict) -> str:
        qd = QDate.fromString(weekly.get("date", ""), Qt.DateFormat.ISODate)
        if not qd.isValid():
            qd = QDate.currentDate()

        date_text = qd.toString("dd.MM.yyyy")
        weekday_short = WEEKDAY_SHORT_DE.get(qd.dayOfWeek(), "Mo")
        title = str(weekly.get("title", "")).strip() or "Ohne Titel"
        return f"{date_text} - {weekday_short} - {title}"

    def _load_project_into_ui(self, project: dict):
        self._loading_ui = True
        try:
            self.project_name_edit.setText(str(project.get("name", "")).strip() or "Projekt")
            start_qd = QDate.fromString(project.get("start_date", ""), Qt.DateFormat.ISODate)
            end_qd = QDate.fromString(project.get("end_date", ""), Qt.DateFormat.ISODate)
            if not start_qd.isValid():
                start_qd = QDate.currentDate()
            if not end_qd.isValid():
                end_qd = start_qd.addDays(90)
            self.project_start_edit.setDate(start_qd)
            self.project_end_edit.setDate(end_qd)
            self.project_todos_widget.set_tasks(normalize_todos(project.get("project_todos", [])))
        finally:
            self._loading_ui = False

        self._update_project_progress_ui(project)

    def _clear_project_ui(self):
        self._loading_ui = True
        try:
            self.project_name_edit.clear()
            self.project_start_edit.setDate(QDate.currentDate())
            self.project_end_edit.setDate(QDate.currentDate().addDays(90))
            self.project_todos_widget.set_tasks([])
        finally:
            self._loading_ui = False
        self._update_project_progress_ui(None)

    def _load_weekly_into_ui(self, weekly: dict):
        self._loading_ui = True
        try:
            self.weekly_title_edit.setText(str(weekly.get("title", "")))
            qd = QDate.fromString(weekly.get("date", ""), Qt.DateFormat.ISODate)
            if not qd.isValid():
                qd = QDate.currentDate()
            self.weekly_date_edit.setDate(qd)
            self.txt_planned.setPlainText(str(weekly.get("planned", "")))
            self.txt_done.setPlainText(str(weekly.get("done", "")))
            self.txt_next.setPlainText(str(weekly.get("next_planned", "")))
        finally:
            self._loading_ui = False

    def _clear_weekly_ui(self):
        self._loading_ui = True
        try:
            self.weekly_title_edit.clear()
            self.weekly_date_edit.setDate(QDate.currentDate())
            self.txt_planned.clear()
            self.txt_done.clear()
            self.txt_next.clear()
        finally:
            self._loading_ui = False

    def _write_project_from_ui(self) -> bool:
        if self._loading_ui:
            return False
        project = self._current_project()
        if project is None:
            return False

        project["name"] = (self.project_name_edit.text() or "").strip() or "Projekt"
        project["start_date"] = self.project_start_edit.date().toString(Qt.DateFormat.ISODate)
        project["end_date"] = self.project_end_edit.date().toString(Qt.DateFormat.ISODate)
        project["project_todos"] = self.project_todos_widget.get_tasks()
        return True

    def _write_weekly_from_ui(self) -> bool:
        if self._loading_ui:
            return False
        weeklies = self._current_weeklies()
        if weeklies is None or self.current_weekly_index is None:
            return False
        if not (0 <= self.current_weekly_index < len(weeklies)):
            return False

        weekly = weeklies[self.current_weekly_index]
        weekly["title"] = self.weekly_title_edit.text().strip()
        weekly["date"] = self.weekly_date_edit.date().toString(Qt.DateFormat.ISODate)
        weekly["planned"] = self.txt_planned.toPlainText().rstrip()
        weekly["done"] = self.txt_done.toPlainText().rstrip()
        weekly["next_planned"] = self.txt_next.toPlainText().rstrip()
        return True

    def _update_current_weekly_list_item(self):
        if self.current_weekly_index is None:
            return
        weeklies = self._current_weeklies()
        if weeklies is None or not (0 <= self.current_weekly_index < len(weeklies)):
            return

        for row in range(self.weekly_list.count()):
            item = self.weekly_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_weekly_index:
                item.setText(self._weekly_list_text(weeklies[self.current_weekly_index]))
                return

    def _update_project_progress_ui(self, project: dict | None):
        if project is None:
            self.project_progress.setValue(0)
            self.project_progress_label.setText("Projektfortschritt: -")
            return

        start = QDate.fromString(project.get("start_date", ""), Qt.DateFormat.ISODate)
        end = QDate.fromString(project.get("end_date", ""), Qt.DateFormat.ISODate)
        if not start.isValid() or not end.isValid():
            self.project_progress.setValue(0)
            self.project_progress_label.setText("Projektfortschritt: Ungueltige Datumswerte")
            return

        if end < start:
            self.project_progress.setValue(0)
            self.project_progress_label.setText("Projektfortschritt: Enddatum liegt vor Startdatum")
            return

        today = QDate.currentDate()
        total_days = max(1, start.daysTo(end))
        elapsed_days = start.daysTo(today)

        if today <= start:
            pct = 0
        elif today >= end:
            pct = 100
        else:
            pct = int((elapsed_days / total_days) * 100)

        pct = max(0, min(100, pct))
        self.project_progress.setValue(pct)
        self.project_progress_label.setText(
            f"Projektfortschritt: {pct}% ({start.toString('dd.MM.yyyy')} - {end.toString('dd.MM.yyyy')})"
        )

    def _determine_todo_context(self) -> str:
        if self.current_student is None:
            return "Gesamt"
        if self.current_project_index is None:
            return f"Student: {self.current_student}"

        project = self._current_project()
        project_name = str(project.get("name", "Projekt")) if project else "Projekt"
        if self.current_weekly_index is None:
            return f"Student: {self.current_student} | Projekt: {project_name}"
        return f"Student: {self.current_student} | Projekt: {project_name} | Weekly aktiv"

    def _collect_open_todos_by_context(self) -> list[tuple[str, str, str]]:
        rows = []

        def project_rows(student_name: str, project: dict):
            project_name = str(project.get("name", "Projekt")).strip() or "Projekt"
            for todo in normalize_todos(project.get("project_todos", [])):
                if not todo.get("checked", False):
                    rows.append((student_name, project_name, todo["text"]))

        if self.current_student is None:
            for student_name, student_entry in self.data["students"].items():
                projects = student_entry.get("projects", []) if isinstance(student_entry, dict) else []
                for project in projects:
                    if isinstance(project, dict):
                        project_rows(student_name, project)
            return rows

        student_entry = self.data["students"].get(self.current_student, {})
        projects = student_entry.get("projects", []) if isinstance(student_entry, dict) else []
        if self.current_project_index is None:
            for project in projects:
                if isinstance(project, dict):
                    project_rows(self.current_student, project)
            return rows

        project = self._current_project()
        if project is not None:
            project_rows(self.current_student, project)
        return rows

    def refresh_todo_context_view(self):
        self.todo_context_label.setText(f"Kontext: {self._determine_todo_context()}")

        rows = self._collect_open_todos_by_context()
        self.todo_context_list.blockSignals(True)
        self.todo_context_list.clear()

        if not rows:
            self.todo_context_list.addItem("Keine offenen TODOs")
        else:
            for student_name, project_name, text in rows:
                self.todo_context_list.addItem(f"[{student_name} | {project_name}] {text}")

        self.todo_context_list.blockSignals(False)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def refresh_student_list(self, select_name: str | None = None):
        self.student_list.blockSignals(True)
        self.student_list.clear()

        for name in sorted(self.data["students"].keys(), key=str.lower):
            self.student_list.addItem(QListWidgetItem(name))

        self.student_list.blockSignals(False)

        target_name = select_name if select_name is not None else self.current_student
        if target_name:
            matches = self.student_list.findItems(target_name, Qt.MatchFlag.MatchExactly)
            if matches:
                self.student_list.setCurrentItem(matches[0])
                self._sync_action_states()
                return

        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_project_list()
        self.refresh_weekly_list()
        self.refresh_todo_context_view()
        self._sync_action_states()

    def refresh_project_list(self, select_index: int | None = None):
        self.project_list.blockSignals(True)
        self.project_list.clear()

        projects = self._current_student_projects()
        if self.current_student is None or projects is None:
            self.current_project_index = None
            self.project_summary_label.setText("Keine Studierenden ausgewaehlt")
            self.project_list.blockSignals(False)
            self._set_project_fields_enabled(False)
            self._clear_project_ui()
            self.refresh_weekly_list()
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        total_weeklies = sum(len(project.get("weeklies", [])) for project in projects if isinstance(project, dict))
        self.project_summary_label.setText(f"{self.current_student} - {len(projects)} Projekt(e) - {total_weeklies} Weekly(s)")

        for idx, project in enumerate(projects):
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", f"Projekt {idx + 1}")).strip() or f"Projekt {idx + 1}"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.project_list.addItem(item)

        self.project_list.blockSignals(False)

        has_projects = len(projects) > 0

        if not has_projects:
            self.current_project_index = None
            self.current_weekly_index = None
            self._set_project_fields_enabled(False)
            self._clear_project_ui()
            self.refresh_weekly_list()
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        target_index = select_index if select_index is not None else self.current_project_index
        if target_index is not None:
            for row in range(self.project_list.count()):
                item = self.project_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == target_index:
                    self.project_list.setCurrentItem(item)
                    self._sync_action_states()
                    return

        self.current_project_index = None
        self.current_weekly_index = None
        self._set_project_fields_enabled(False)
        self._clear_project_ui()
        self.refresh_weekly_list()
        self.refresh_todo_context_view()
        self._sync_action_states()

    def refresh_weekly_list(self, select_index: int | None = None):
        self.weekly_list.blockSignals(True)
        self.weekly_list.clear()

        weeklies = self._current_weeklies()
        project = self._current_project()
        if weeklies is None or project is None:
            self.weekly_summary_label.setText("Kein Projekt ausgewaehlt")
            self.weekly_list.blockSignals(False)
            self.current_weekly_index = None
            self._set_weekly_editor_enabled(False)
            self._clear_weekly_ui()
            self.btn_delete_weekly.setEnabled(False)
            self.act_delete_weekly.setEnabled(False)
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        count = len(weeklies)
        self.weekly_summary_label.setText(f"{project.get('name', 'Projekt')} - {count} Weekly(s)")
        for idx in reversed(range(count)):
            weekly = weeklies[idx]
            if isinstance(weekly, dict):
                item = QListWidgetItem(self._weekly_list_text(weekly))
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self.weekly_list.addItem(item)

        self.weekly_list.blockSignals(False)

        target_index = select_index if select_index is not None else self.current_weekly_index
        if target_index is not None:
            for row in range(self.weekly_list.count()):
                item = self.weekly_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == target_index:
                    self.weekly_list.setCurrentItem(item)
                    self._sync_action_states()
                    return

        self.current_weekly_index = None
        self._set_weekly_editor_enabled(False)
        self._clear_weekly_ui()
        self.btn_delete_weekly.setEnabled(False)
        self.act_delete_weekly.setEnabled(False)
        self.refresh_todo_context_view()
        self._sync_action_states()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _switch_to_project_overview(self):
        self.weekly_list.blockSignals(True)
        self.weekly_list.clearSelection()
        self.weekly_list.blockSignals(False)
        self.current_weekly_index = None
        self._set_weekly_editor_enabled(False)
        self._clear_weekly_ui()
        self.btn_delete_weekly.setEnabled(False)
        self.act_delete_weekly.setEnabled(False)
        self.refresh_todo_context_view()
        self._sync_action_states()

    def on_student_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_student = None
            self.current_project_index = None
            self.current_weekly_index = None
            self.refresh_project_list()
            self.refresh_weekly_list()
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        self.current_student = current.text()
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_project_list()
        self.refresh_todo_context_view()
        self._sync_action_states()

    def on_project_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_project_index = None
            self.current_weekly_index = None
            self._set_project_fields_enabled(False)
            self._clear_project_ui()
            self.refresh_weekly_list()
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        idx = current.data(Qt.ItemDataRole.UserRole)
        self.current_project_index = int(idx)
        self.current_weekly_index = None

        project = self._current_project()
        if project is None:
            self.current_project_index = None
            self._set_project_fields_enabled(False)
            self._clear_project_ui()
            self.refresh_weekly_list()
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        self._set_project_fields_enabled(True)
        self._load_project_into_ui(project)
        self.refresh_weekly_list()
        self.refresh_todo_context_view()
        self._sync_action_states()

    def on_weekly_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_weekly_index = None
            self._set_weekly_editor_enabled(False)
            self._clear_weekly_ui()
            self.btn_delete_weekly.setEnabled(False)
            self.act_delete_weekly.setEnabled(False)
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        idx = current.data(Qt.ItemDataRole.UserRole)
        self.current_weekly_index = int(idx)

        weeklies = self._current_weeklies()
        if weeklies is None or not (0 <= self.current_weekly_index < len(weeklies)):
            self.current_weekly_index = None
            self._set_weekly_editor_enabled(False)
            self._clear_weekly_ui()
            self.btn_delete_weekly.setEnabled(False)
            self.act_delete_weekly.setEnabled(False)
            self.refresh_todo_context_view()
            self._sync_action_states()
            return

        self._set_weekly_editor_enabled(True)
        self.btn_delete_weekly.setEnabled(True)
        self.act_delete_weekly.setEnabled(True)
        self._load_weekly_into_ui(weeklies[self.current_weekly_index])
        self.refresh_todo_context_view()
        self._sync_action_states()

    def _on_project_fields_changed(self):
        if not self._write_project_from_ui():
            return
        self._update_project_progress_ui(self._current_project())
        self.refresh_project_list(select_index=self.current_project_index)
        self.refresh_todo_context_view()
        self._on_data_changed()

    def _on_project_todos_changed(self):
        if not self._write_project_from_ui():
            return
        self.refresh_todo_context_view()
        self._on_data_changed()

    def _on_weekly_fields_changed(self):
        if not self._write_weekly_from_ui():
            return
        self._update_current_weekly_list_item()
        self.refresh_todo_context_view()
        self._on_data_changed()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add_student(self):
        name, ok = QInputDialog.getText(self, "Studierende:n hinzufuegen", "Name:")
        if not ok:
            return

        name = (name or "").strip()
        if not name:
            return

        if name in self.data["students"]:
            QMessageBox.information(self, "Hinweis", "Diese Person existiert bereits.")
            self.refresh_student_list(select_name=name)
            return

        self.data["students"][name] = {"projects": []}
        self.refresh_student_list(select_name=name)
        self._on_data_changed()

    def remove_student(self):
        item = self.student_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Person auswaehlen.")
            return

        name = item.text()
        reply = QMessageBox.question(
            self,
            "Studierende:n entfernen",
            f"Soll '{name}' inklusive aller Projekte und Weeklies wirklich entfernt werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.data["students"].pop(name, None)
        if self.current_student == name:
            self.current_student = None
            self.current_project_index = None
            self.current_weekly_index = None

        self.refresh_student_list()
        self._on_data_changed()

    def add_project(self):
        if self.current_student is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine:n Studierende:n auswaehlen.")
            return

        project_name, ok = QInputDialog.getText(self, "Projekt hinzufuegen", "Projektname:")
        if not ok:
            return

        project_name = (project_name or "").strip()
        if not project_name:
            return

        projects = self._current_student_projects()
        if projects is None:
            return

        today = QDate.currentDate()
        projects.append(
            make_empty_project(
                project_name,
                today.toString(Qt.DateFormat.ISODate),
                today.addDays(90).toString(Qt.DateFormat.ISODate),
            )
        )

        self.refresh_project_list(select_index=len(projects) - 1)
        self._on_data_changed()

    def remove_project(self):
        if self.current_student is None or self.current_project_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Projekt auswaehlen.")
            return

        projects = self._current_student_projects()
        if projects is None or not (0 <= self.current_project_index < len(projects)):
            return

        project_name = projects[self.current_project_index].get("name", "Projekt")
        reply = QMessageBox.question(
            self,
            "Projekt loeschen",
            f"Soll das Projekt '{project_name}' inklusive aller Weeklies wirklich geloescht werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del projects[self.current_project_index]
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_project_list()
        self._on_data_changed()

    def add_weekly(self):
        if self.current_student is None or self.current_project_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Projekt auswaehlen.")
            return

        weeklies = self._current_weeklies()
        if weeklies is None:
            return

        inherited_planned = ""
        if weeklies:
            inherited_planned = str(weeklies[-1].get("next_planned", ""))

        weeklies.append(make_empty_weekly(QDate.currentDate().toString(Qt.DateFormat.ISODate), inherited_planned))
        new_index = len(weeklies) - 1

        self.current_weekly_index = new_index
        self.refresh_weekly_list(select_index=new_index)
        self._on_data_changed()

    def delete_weekly(self):
        if self.current_weekly_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Weekly auswaehlen.")
            return

        weeklies = self._current_weeklies()
        if weeklies is None or not (0 <= self.current_weekly_index < len(weeklies)):
            return

        title = self._weekly_list_text(weeklies[self.current_weekly_index])
        reply = QMessageBox.question(
            self,
            "Weekly loeschen",
            f"Soll das Weekly '{title}' wirklich geloescht werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del weeklies[self.current_weekly_index]
        self.current_weekly_index = None
        self.refresh_weekly_list()
        self._on_data_changed()

    # ------------------------------------------------------------------
    # File ops
    # ------------------------------------------------------------------
    def _load_or_create_default_file(self):
        if os.path.exists(self.current_file):
            self.load_json(self.current_file)
            return

        self.data = {"version": 4, "students": {}}
        self._save_to_current_file()
        self.refresh_student_list()
        self.refresh_todo_context_view()

    def load_json_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "JSON laden",
            self.default_open_dir,
            "JSON Dateien (*.json);;Alle Dateien (*)",
        )
        if not file_path:
            return
        self.load_json(file_path)

    def load_json(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            self.data = validate_data(raw)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Laden", f"Datei konnte nicht geladen werden:\n{exc}")
            self._set_saved_state(saved=False)
            return

        self.current_file = file_path
        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_student_list()
        self.refresh_todo_context_view()
        self._set_saved_state(saved=True)

    def _save_to_current_file(self) -> bool:
        try:
            with open(self.current_file, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Datei konnte nicht gespeichert werden:\n{exc}")
            self._set_saved_state(saved=False)
            return False

        self._set_saved_state(saved=True)
        return True

    def closeEvent(self, event):
        self._write_project_from_ui()
        self._write_weekly_from_ui()
        self._save_to_current_file()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Studierenden-Weeklies Manager")
    window = WeeklyManagerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
