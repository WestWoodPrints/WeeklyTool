# weekly_manager_pyqt.py
# Python 3.10+
# Benoetigt: PyQt6
# Installation: pip install PyQt6

import json
import os
import sys

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyleFactory,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


WEEKDAY_NAMES_DE = {
    1: "Montag",
    2: "Dienstag",
    3: "Mittwoch",
    4: "Donnerstag",
    5: "Freitag",
    6: "Samstag",
    7: "Sonntag",
}


def normalize_iso_date(value: str, fallback: QDate | None = None) -> str:
    fallback = fallback or QDate.currentDate()
    qd = QDate.fromString(str(value), Qt.DateFormat.ISODate)
    if not qd.isValid():
        qd = fallback
    return qd.toString(Qt.DateFormat.ISODate)


def make_empty_weekly(date_str: str, planned: str = "") -> dict:
    return {
        "date": normalize_iso_date(date_str),
        "planned": planned,
        "done": "",
        "next_planned": "",
    }


def make_empty_project(name: str, start_date: str, end_date: str) -> dict:
    return {
        "name": name.strip() or "Projekt",
        "start_date": normalize_iso_date(start_date),
        "end_date": normalize_iso_date(end_date),
        "weeklies": [],
    }


def _clean_weekly(raw_weekly: dict) -> dict:
    return {
        "date": normalize_iso_date(raw_weekly.get("date", QDate.currentDate().toString(Qt.DateFormat.ISODate))),
        "planned": str(raw_weekly.get("planned", "")),
        "done": str(raw_weekly.get("done", "")),
        "next_planned": str(raw_weekly.get("next_planned", "")),
    }


def _clean_project(raw_project: dict, fallback_name: str) -> dict:
    project_name = str(raw_project.get("name", fallback_name)).strip() or fallback_name
    start = normalize_iso_date(raw_project.get("start_date", QDate.currentDate().toString(Qt.DateFormat.ISODate)))
    end = normalize_iso_date(raw_project.get("end_date", QDate.currentDate().addDays(90).toString(Qt.DateFormat.ISODate)))

    raw_weeklies = raw_project.get("weeklies", [])
    if not isinstance(raw_weeklies, list):
        raw_weeklies = []

    cleaned_weeklies = []
    for weekly in raw_weeklies:
        if isinstance(weekly, dict):
            cleaned_weeklies.append(_clean_weekly(weekly))

    return {
        "name": project_name,
        "start_date": start,
        "end_date": end,
        "weeklies": cleaned_weeklies,
    }


def validate_data(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON-Wurzel muss ein Objekt sein.")

    students_raw = data.get("students", {})
    if not isinstance(students_raw, dict):
        students_raw = {}

    cleaned = {"version": 2, "students": {}}

    for student_name, student_value in students_raw.items():
        if not isinstance(student_name, str):
            continue

        cleaned_projects = []

        # Migration Altformat: students[name] = [weeklies]
        if isinstance(student_value, list):
            cleaned_projects.append(
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

        # Neues Format
        elif isinstance(student_value, dict):
            if isinstance(student_value.get("projects"), list):
                for idx, project in enumerate(student_value["projects"]):
                    if isinstance(project, dict):
                        cleaned_projects.append(_clean_project(project, f"Projekt {idx + 1}"))
            elif isinstance(student_value.get("weeklies"), list):
                # Zwischenformat: student mit weeklies direkt
                cleaned_projects.append(
                    _clean_project(
                        {
                            "name": student_value.get("name", "Standardprojekt"),
                            "start_date": student_value.get(
                                "start_date",
                                QDate.currentDate().toString(Qt.DateFormat.ISODate),
                            ),
                            "end_date": student_value.get(
                                "end_date",
                                QDate.currentDate().addDays(90).toString(Qt.DateFormat.ISODate),
                            ),
                            "weeklies": student_value.get("weeklies", []),
                        },
                        "Standardprojekt",
                    )
                )

        cleaned["students"][student_name] = {"projects": cleaned_projects}

    return cleaned


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
        self.resize(1420, 860)

        self.data = {"version": 2, "students": {}}
        self.current_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "weeklies.json",
        )

        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None

        self._loading_ui = False
        self._dirty = False

        self._build_ui()
        self._apply_style()
        self._connect_signals()
        self._load_or_create_default_file()

        self.statusBar().showMessage("Bereit")
        self._update_window_title()

    # -------------------------------------------------------------------------
    # UI Aufbau
    # -------------------------------------------------------------------------
    def _build_ui(self):
        self.setStatusBar(QStatusBar(self))

        toolbar = QToolBar("Hauptleiste")
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        self.addToolBar(toolbar)

        self.act_open = QAction("Laden", self)
        toolbar.addAction(self.act_open)
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

        # --- Linke Spalte: Studierende ---
        left_card = Card("Studierende")
        splitter.addWidget(left_card)

        left_card.content_layout.addWidget(QLabel("Auswahl"))

        self.student_list = QListWidget()
        self.student_list.setObjectName("StudentList")
        self.student_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        left_card.content_layout.addWidget(self.student_list, 1)

        student_btn_row = QHBoxLayout()
        self.btn_add_student = QPushButton("+ Hinzufuegen")
        self.btn_remove_student = QPushButton("- Entfernen")
        student_btn_row.addWidget(self.btn_add_student)
        student_btn_row.addWidget(self.btn_remove_student)
        left_card.content_layout.addLayout(student_btn_row)

        # --- Mittlere Spalte: Projekte + Weeklies ---
        middle_card = Card("Projekte und Weeklies")
        splitter.addWidget(middle_card)

        self.project_summary_label = QLabel("Keine Studierenden ausgewaehlt")
        self.project_summary_label.setObjectName("SubtleLabel")
        middle_card.content_layout.addWidget(self.project_summary_label)

        self.project_list = QListWidget()
        self.project_list.setObjectName("ProjectList")
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

        self.weekly_list = QListWidget()
        self.weekly_list.setObjectName("WeeklyList")
        self.weekly_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        middle_card.content_layout.addWidget(self.weekly_list, 1)

        weekly_btn_row = QHBoxLayout()
        self.btn_new_weekly = QPushButton("Neues Weekly")
        self.btn_delete_weekly = QPushButton("Weekly loeschen")
        weekly_btn_row.addWidget(self.btn_new_weekly)
        weekly_btn_row.addWidget(self.btn_delete_weekly)
        middle_card.content_layout.addLayout(weekly_btn_row)

        # --- Rechte Spalte: Projektinfos + Weekly Editor ---
        right_card = Card("Projekt und Weekly bearbeiten")
        splitter.addWidget(right_card)

        project_meta_row = QHBoxLayout()

        lbl_project_name = QLabel("Projektname")
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("Projektname")
        self.project_name_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lbl_start = QLabel("Projektstart")
        self.project_start_edit = QDateEdit()
        self.project_start_edit.setCalendarPopup(True)
        self.project_start_edit.setDisplayFormat("dd.MM.yyyy")
        self.project_start_edit.setDate(QDate.currentDate())
        self.project_start_edit.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        lbl_end = QLabel("Projektende")
        self.project_end_edit = QDateEdit()
        self.project_end_edit.setCalendarPopup(True)
        self.project_end_edit.setDisplayFormat("dd.MM.yyyy")
        self.project_end_edit.setDate(QDate.currentDate().addDays(90))
        self.project_end_edit.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        project_meta_row.addWidget(lbl_project_name)
        project_meta_row.addWidget(self.project_name_edit, 1)
        project_meta_row.addWidget(lbl_start)
        project_meta_row.addWidget(self.project_start_edit)
        project_meta_row.addWidget(lbl_end)
        project_meta_row.addWidget(self.project_end_edit)
        project_meta_row.addStretch(1)
        right_card.content_layout.addLayout(project_meta_row)

        self.project_progress_label = QLabel("Projektfortschritt: -")
        self.project_progress_label.setObjectName("SubtleLabel")
        right_card.content_layout.addWidget(self.project_progress_label)

        self.project_progress = QProgressBar()
        self.project_progress.setRange(0, 100)
        self.project_progress.setValue(0)
        right_card.content_layout.addWidget(self.project_progress)

        meta_row = QHBoxLayout()
        lbl_date = QLabel("Weekly-Datum")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setObjectName("DirtyLabel")
        self.lbl_dirty.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        meta_row.addWidget(lbl_date)
        meta_row.addWidget(self.date_edit)
        meta_row.addStretch(1)
        meta_row.addWidget(self.lbl_dirty)
        right_card.content_layout.addLayout(meta_row)

        self.grp_planned = QGroupBox("Was war geplant?")
        self.txt_planned = QTextEdit()
        self.txt_planned.setPlaceholderText("Plan aus der letzten Woche wird hier automatisch uebernommen ...")
        self._set_group_layout(self.grp_planned, self.txt_planned)
        right_card.content_layout.addWidget(self.grp_planned, 1)

        self.grp_done = QGroupBox("Was wurde gemacht?")
        self.txt_done = QTextEdit()
        self.txt_done.setPlaceholderText("Kurz zusammenfassen, was tatsaechlich erledigt wurde ...")
        self._set_group_layout(self.grp_done, self.txt_done)
        right_card.content_layout.addWidget(self.grp_done, 1)

        self.grp_next = QGroupBox("Was ist geplant?")
        self.txt_next = QTextEdit()
        self.txt_next.setPlaceholderText("Plan fuer das naechste Weekly ...")
        self._set_group_layout(self.grp_next, self.txt_next)
        right_card.content_layout.addWidget(self.grp_next, 1)

        splitter.setSizes([250, 470, 700])

        self._set_project_fields_enabled(False)
        self._set_editor_enabled(False)

    def _set_group_layout(self, groupbox: QGroupBox, editor: QTextEdit):
        layout = QVBoxLayout(groupbox)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.addWidget(editor)

    def _connect_signals(self):
        # Toolbar Aktionen
        self.act_open.triggered.connect(self.load_json_dialog)
        self.act_add_student.triggered.connect(self.add_student)
        self.act_remove_student.triggered.connect(self.remove_student)
        self.act_add_project.triggered.connect(self.add_project)
        self.act_remove_project.triggered.connect(self.remove_project)
        self.act_new_weekly.triggered.connect(self.add_weekly)
        self.act_delete_weekly.triggered.connect(self.delete_weekly)

        # Buttons
        self.btn_add_student.clicked.connect(self.add_student)
        self.btn_remove_student.clicked.connect(self.remove_student)
        self.btn_add_project.clicked.connect(self.add_project)
        self.btn_remove_project.clicked.connect(self.remove_project)
        self.btn_new_weekly.clicked.connect(self.add_weekly)
        self.btn_delete_weekly.clicked.connect(self.delete_weekly)

        # Listen
        self.student_list.currentItemChanged.connect(self.on_student_changed)
        self.project_list.currentItemChanged.connect(self.on_project_changed)
        self.weekly_list.currentItemChanged.connect(self.on_weekly_changed)

        # Projekt- und Weekly-Aenderungen
        self.project_start_edit.dateChanged.connect(self._on_project_dates_changed)
        self.project_end_edit.dateChanged.connect(self._on_project_dates_changed)
        self.project_name_edit.editingFinished.connect(self._on_project_name_changed)
        self.date_edit.dateChanged.connect(self._on_editor_changed)
        self.txt_planned.textChanged.connect(self._on_editor_changed)
        self.txt_done.textChanged.connect(self._on_editor_changed)
        self.txt_next.textChanged.connect(self._on_editor_changed)

    # -------------------------------------------------------------------------
    # Styling
    # -------------------------------------------------------------------------
    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))

        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        self.setStyleSheet(
            """
            QMainWindow {
                background: #f3f6fb;
            }

            QToolBar {
                background: #ffffff;
                border: 1px solid #e3e8f0;
                spacing: 6px;
                padding: 6px;
                border-radius: 10px;
            }

            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px 10px;
            }
            QToolButton:hover {
                background: #eef3ff;
                border: 1px solid #d9e4ff;
            }

            QLabel#SubtleLabel {
                color: #5b6b7a;
            }

            QLabel#DirtyLabel {
                color: #b45309;
                font-weight: 600;
            }

            QFrame#Card {
                background: #ffffff;
                border: 1px solid #e3e8f0;
                border-radius: 14px;
            }

            QLabel#CardTitle {
                font-size: 15px;
                font-weight: 700;
                color: #1f2a37;
                padding-bottom: 4px;
            }

            QListWidget {
                background: #fbfcff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 6px;
            }

            QListWidget::item {
                border-radius: 8px;
                padding: 8px;
                margin: 2px 0px;
            }

            QListWidget::item:selected {
                background: #dbeafe;
                color: #0f172a;
                border: 1px solid #bfdbfe;
            }

            QListWidget::item:hover:!selected {
                background: #f1f5f9;
            }

            QPushButton {
                background: #ffffff;
                color: #1f2937;
                border: 1px solid #d8e0ea;
                border-radius: 10px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background: #f8fbff;
                border-color: #c8d6ea;
            }
            QPushButton:disabled {
                color: #94a3b8;
                background: #f8fafc;
                border-color: #e2e8f0;
            }

            QGroupBox {
                font-weight: 600;
                color: #1f2a37;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                margin-top: 8px;
                background: #fcfdff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }

            QTextEdit, QDateEdit, QProgressBar {
                background: white;
                border: 1px solid #dbe2ec;
                border-radius: 10px;
                padding: 6px;
            }
            QTextEdit:focus, QDateEdit:focus {
                border: 1px solid #60a5fa;
            }
            QProgressBar {
                text-align: center;
            }
            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 8px;
            }

            QStatusBar {
                background: #ffffff;
                border-top: 1px solid #e3e8f0;
            }
        """
        )

    # -------------------------------------------------------------------------
    # Hilfsmethoden
    # -------------------------------------------------------------------------
    def _mark_dirty(self):
        if self._loading_ui:
            return
        self._dirty = True
        self.lbl_dirty.setText("Nicht gespeichert")
        self._update_window_title()

    def _clear_dirty(self):
        self._dirty = False
        self.lbl_dirty.setText("")
        self._update_window_title()

    def _update_window_title(self):
        filename = os.path.basename(self.current_file) if self.current_file else "Unbenannt"
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"Studierenden-Weeklies Manager - {filename}{dirty}")

    def _set_editor_enabled(self, enabled: bool):
        self.date_edit.setEnabled(enabled)
        self.txt_planned.setEnabled(enabled)
        self.txt_done.setEnabled(enabled)
        self.txt_next.setEnabled(enabled)

    def _set_project_fields_enabled(self, enabled: bool):
        self.project_name_edit.setEnabled(enabled)
        self.project_start_edit.setEnabled(enabled)
        self.project_end_edit.setEnabled(enabled)
        self.project_progress.setEnabled(enabled)

    def _current_student_projects(self):
        if self.current_student is None:
            return None
        student_entry = self.data["students"].get(self.current_student, {})
        projects = student_entry.get("projects", [])
        if not isinstance(projects, list):
            return None
        return projects

    def _current_project(self):
        projects = self._current_student_projects()
        if projects is None or self.current_project_index is None:
            return None
        if not (0 <= self.current_project_index < len(projects)):
            return None
        return projects[self.current_project_index]

    def _current_project_weeklies(self):
        project = self._current_project()
        if project is None:
            return None
        weeklies = project.get("weeklies", [])
        if not isinstance(weeklies, list):
            return None
        return weeklies

    def _weekly_title_from_iso(self, date_str: str) -> str:
        qd = QDate.fromString(date_str, Qt.DateFormat.ISODate)
        if not qd.isValid():
            qd = QDate.currentDate()
        weekday = WEEKDAY_NAMES_DE.get(qd.dayOfWeek(), "Tag")
        return f"{qd.toString('dd.MM.yyyy')} {weekday}"

    def _weekly_preview_text(self, weekly: dict) -> str:
        title = self._weekly_title_from_iso(weekly.get("date", ""))
        done_lines = (weekly.get("done", "") or "").strip().splitlines()
        next_lines = (weekly.get("next_planned", "") or "").strip().splitlines()

        preview = ""
        if done_lines:
            preview = done_lines[0]
        elif next_lines:
            preview = "Naechster Plan: " + next_lines[0]
        else:
            preview = "Noch keine Inhalte"

        preview = preview.strip()
        if len(preview) > 70:
            preview = preview[:67] + "..."

        return f"{title}  -  {preview}"

    def _load_project_into_fields(self, project: dict):
        self._loading_ui = True
        try:
            start_qd = QDate.fromString(project.get("start_date", ""), Qt.DateFormat.ISODate)
            end_qd = QDate.fromString(project.get("end_date", ""), Qt.DateFormat.ISODate)
            if not start_qd.isValid():
                start_qd = QDate.currentDate()
            if not end_qd.isValid():
                end_qd = start_qd.addDays(90)

            self.project_name_edit.setText(str(project.get("name", "Projekt")).strip() or "Projekt")
            self.project_start_edit.setDate(start_qd)
            self.project_end_edit.setDate(end_qd)
        finally:
            self._loading_ui = False

        self._update_project_progress_ui(project)

    def _write_project_fields_to_current_project(self) -> bool:
        if self._loading_ui:
            return False
        project = self._current_project()
        if project is None:
            return False

        project["name"] = (self.project_name_edit.text() or "").strip() or "Projekt"
        project["start_date"] = self.project_start_edit.date().toString(Qt.DateFormat.ISODate)
        project["end_date"] = self.project_end_edit.date().toString(Qt.DateFormat.ISODate)
        return True

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
            progress_percent = 0
        elif today >= end:
            progress_percent = 100
        else:
            progress_percent = int((elapsed_days / total_days) * 100)

        progress_percent = max(0, min(100, progress_percent))
        self.project_progress.setValue(progress_percent)
        self.project_progress_label.setText(
            f"Projektfortschritt: {progress_percent}% ({start.toString('dd.MM.yyyy')} - {end.toString('dd.MM.yyyy')})"
        )

    def _load_weekly_into_editor(self, weekly: dict):
        self._loading_ui = True
        try:
            qd = QDate.fromString(weekly.get("date", ""), Qt.DateFormat.ISODate)
            if not qd.isValid():
                qd = QDate.currentDate()
            self.date_edit.setDate(qd)
            self.txt_planned.setPlainText(weekly.get("planned", ""))
            self.txt_done.setPlainText(weekly.get("done", ""))
            self.txt_next.setPlainText(weekly.get("next_planned", ""))
        finally:
            self._loading_ui = False
        self._clear_dirty()

    def _write_editor_to_current_weekly(self) -> bool:
        if self._loading_ui:
            return False
        weekly_list = self._current_project_weeklies()
        if weekly_list is None or self.current_weekly_index is None:
            return False
        if not (0 <= self.current_weekly_index < len(weekly_list)):
            return False

        entry = weekly_list[self.current_weekly_index]
        entry["date"] = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        entry["planned"] = self.txt_planned.toPlainText().rstrip()
        entry["done"] = self.txt_done.toPlainText().rstrip()
        entry["next_planned"] = self.txt_next.toPlainText().rstrip()
        return True

    def _update_current_weekly_list_item(self):
        if self.current_weekly_index is None:
            return
        for row in range(self.weekly_list.count()):
            item = self.weekly_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == self.current_weekly_index:
                weekly_list = self._current_project_weeklies()
                if weekly_list is not None and 0 <= self.current_weekly_index < len(weekly_list):
                    item.setText(self._weekly_preview_text(weekly_list[self.current_weekly_index]))
                return

    def _on_project_dates_changed(self):
        if not self._write_project_fields_to_current_project():
            return
        self._update_project_progress_ui(self._current_project())
        self._save_to_current_file()
        self.refresh_project_list(select_index=self.current_project_index)

    def _on_project_name_changed(self):
        if not self._write_project_fields_to_current_project():
            return
        self._save_to_current_file()
        self.refresh_project_list(select_index=self.current_project_index)

    def _on_editor_changed(self):
        if not self._write_editor_to_current_weekly():
            return
        self._update_current_weekly_list_item()
        self._save_to_current_file()

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------
    def refresh_student_list(self, select_name: str | None = None):
        self.student_list.blockSignals(True)
        self.student_list.clear()

        for name in sorted(self.data["students"].keys(), key=str.lower):
            self.student_list.addItem(QListWidgetItem(name))

        self.student_list.blockSignals(False)

        if select_name:
            matches = self.student_list.findItems(select_name, Qt.MatchFlag.MatchExactly)
            if matches:
                self.student_list.setCurrentItem(matches[0])
                return

        if self.student_list.count() > 0 and self.student_list.currentItem() is None:
            self.student_list.setCurrentRow(0)
        elif self.student_list.count() == 0:
            self.current_student = None
            self.current_project_index = None
            self.current_weekly_index = None
            self.refresh_project_list()
            self.refresh_weekly_list()

    def refresh_project_list(self, select_index: int | None = None):
        self.project_list.blockSignals(True)
        self.project_list.clear()

        projects = self._current_student_projects()
        if self.current_student is None or projects is None:
            self.current_project_index = None
            self.project_summary_label.setText("Keine Studierenden ausgewaehlt")
            self.project_list.blockSignals(False)
            self._set_project_fields_enabled(False)
            self.refresh_weekly_list()
            return

        total_weeklies = sum(len(p.get("weeklies", [])) for p in projects if isinstance(p, dict))
        self.project_summary_label.setText(
            f"{self.current_student} - {len(projects)} Projekt(e) - {total_weeklies} Weekly(s)"
        )

        for original_index, project in enumerate(projects):
            name = str(project.get("name", f"Projekt {original_index + 1}")).strip() or f"Projekt {original_index + 1}"
            self.project_list.addItem(QListWidgetItem(name))
            self.project_list.item(self.project_list.count() - 1).setData(Qt.ItemDataRole.UserRole, original_index)

        self.project_list.blockSignals(False)

        has_projects = len(projects) > 0
        self.btn_add_project.setEnabled(self.current_student is not None)
        self.act_add_project.setEnabled(self.current_student is not None)
        self.btn_remove_project.setEnabled(has_projects)
        self.act_remove_project.setEnabled(has_projects)
        self.btn_new_weekly.setEnabled(has_projects)
        self.act_new_weekly.setEnabled(has_projects)

        if not has_projects:
            self.current_project_index = None
            self._set_project_fields_enabled(False)
            self._update_project_progress_ui(None)
            self.refresh_weekly_list()
            return

        target_row = 0
        if select_index is not None:
            for row in range(self.project_list.count()):
                if self.project_list.item(row).data(Qt.ItemDataRole.UserRole) == select_index:
                    target_row = row
                    break

        self.project_list.setCurrentRow(target_row)

    def refresh_weekly_list(self, select_index: int | None = None):
        self.weekly_list.blockSignals(True)
        self.weekly_list.clear()

        weekly_list = self._current_project_weeklies()
        project = self._current_project()

        if weekly_list is None or project is None:
            self.weekly_summary_label.setText("Kein Projekt ausgewaehlt")
            self.weekly_list.blockSignals(False)
            self.current_weekly_index = None
            self._set_editor_enabled(False)
            self.btn_delete_weekly.setEnabled(False)
            self.act_delete_weekly.setEnabled(False)
            return

        count = len(weekly_list)
        self.weekly_summary_label.setText(f"{project.get('name', 'Projekt')} - {count} Weekly(s)")

        for original_index in reversed(range(count)):
            weekly = weekly_list[original_index]
            item = QListWidgetItem(self._weekly_preview_text(weekly))
            item.setData(Qt.ItemDataRole.UserRole, original_index)
            self.weekly_list.addItem(item)

        self.weekly_list.blockSignals(False)

        self._set_editor_enabled(count > 0)
        self.btn_delete_weekly.setEnabled(count > 0)
        self.act_delete_weekly.setEnabled(count > 0)

        if count == 0:
            self.current_weekly_index = None
            self._loading_ui = True
            try:
                self.date_edit.setDate(QDate.currentDate())
                self.txt_planned.clear()
                self.txt_done.clear()
                self.txt_next.clear()
            finally:
                self._loading_ui = False
            self._clear_dirty()
            return

        target_row = 0
        if select_index is not None:
            for row in range(self.weekly_list.count()):
                if self.weekly_list.item(row).data(Qt.ItemDataRole.UserRole) == select_index:
                    target_row = row
                    break

        self.weekly_list.setCurrentRow(target_row)

    # -------------------------------------------------------------------------
    # Events: Auswahlwechsel
    # -------------------------------------------------------------------------
    def on_student_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_student = None
            self.current_project_index = None
            self.current_weekly_index = None
            self.refresh_project_list()
            self.refresh_weekly_list()
            return

        self.current_student = current.text()
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_project_list()

    def on_project_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_project_index = None
            self.current_weekly_index = None
            self._set_project_fields_enabled(False)
            self._update_project_progress_ui(None)
            self.refresh_weekly_list()
            return

        idx = current.data(Qt.ItemDataRole.UserRole)
        self.current_project_index = int(idx)
        self.current_weekly_index = None

        project = self._current_project()
        if project is None:
            self.current_project_index = None
            self._set_project_fields_enabled(False)
            self._update_project_progress_ui(None)
            self.refresh_weekly_list()
            return

        self._set_project_fields_enabled(True)
        self._load_project_into_fields(project)
        self.refresh_weekly_list()

    def on_weekly_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_weekly_index = None
            self._set_editor_enabled(False)
            return

        idx = current.data(Qt.ItemDataRole.UserRole)
        self.current_weekly_index = int(idx)

        weekly_list = self._current_project_weeklies()
        if weekly_list is None or not (0 <= self.current_weekly_index < len(weekly_list)):
            self.current_weekly_index = None
            self._set_editor_enabled(False)
            return

        self._set_editor_enabled(True)
        self._load_weekly_into_editor(weekly_list[self.current_weekly_index])

    # -------------------------------------------------------------------------
    # CRUD Studierende
    # -------------------------------------------------------------------------
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
        self._save_to_current_file()
        self.statusBar().showMessage(f"Studierende:r '{name}' hinzugefuegt", 3000)

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
        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None
        self.refresh_student_list()
        self._save_to_current_file()
        self.statusBar().showMessage(f"'{name}' entfernt", 3000)

    # -------------------------------------------------------------------------
    # CRUD Projekte
    # -------------------------------------------------------------------------
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
        new_index = len(projects) - 1
        self.refresh_project_list(select_index=new_index)
        self._save_to_current_file()
        self.statusBar().showMessage(f"Projekt '{project_name}' angelegt", 3000)

    def remove_project(self):
        if self.current_student is None or self.current_project_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Projekt auswaehlen.")
            return

        projects = self._current_student_projects()
        if projects is None or not (0 <= self.current_project_index < len(projects)):
            return

        project = projects[self.current_project_index]
        project_name = project.get("name", "Projekt")
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
        self._save_to_current_file()
        self.statusBar().showMessage(f"Projekt '{project_name}' geloescht", 3000)

    # -------------------------------------------------------------------------
    # CRUD Weeklies
    # -------------------------------------------------------------------------
    def add_weekly(self):
        if self.current_student is None or self.current_project_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Projekt auswaehlen.")
            return

        weekly_list = self._current_project_weeklies()
        if weekly_list is None:
            return

        inherited_planned = ""
        if len(weekly_list) > 0:
            inherited_planned = weekly_list[-1].get("next_planned", "")

        new_entry = make_empty_weekly(
            date_str=QDate.currentDate().toString(Qt.DateFormat.ISODate),
            planned=inherited_planned,
        )
        weekly_list.append(new_entry)
        new_index = len(weekly_list) - 1

        self.refresh_weekly_list(select_index=new_index)
        self._save_to_current_file()
        self.statusBar().showMessage("Neues Weekly angelegt", 3000)

    def delete_weekly(self):
        if self.current_student is None or self.current_project_index is None or self.current_weekly_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Weekly auswaehlen.")
            return

        weekly_list = self._current_project_weeklies()
        if weekly_list is None or not (0 <= self.current_weekly_index < len(weekly_list)):
            return

        weekly = weekly_list[self.current_weekly_index]
        weekly_title = self._weekly_title_from_iso(weekly.get("date", ""))
        reply = QMessageBox.question(
            self,
            "Weekly loeschen",
            f"Soll das Weekly '{weekly_title}' wirklich geloescht werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del weekly_list[self.current_weekly_index]
        self.current_weekly_index = None
        self.refresh_weekly_list()
        self._save_to_current_file()
        self.statusBar().showMessage("Weekly geloescht", 3000)

    # -------------------------------------------------------------------------
    # Dateioperationen (JSON)
    # -------------------------------------------------------------------------
    def _load_or_create_default_file(self):
        if os.path.exists(self.current_file):
            self.load_json(self.current_file)
            return

        self.data = {"version": 2, "students": {}}
        self._save_to_current_file()
        self.refresh_student_list()
        self.statusBar().showMessage("Neue weeklies.json angelegt", 4000)

    def load_json_dialog(self):
        if not os.path.exists(self.current_file):
            QMessageBox.information(self, "Hinweis", "Die Datei weeklies.json existiert noch nicht.")
            return
        self.load_json(self.current_file)

    def load_json(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            self.data = validate_data(raw)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Laden", f"Datei konnte nicht geladen werden:\n{exc}")
            return

        self.current_file = file_path
        self.current_student = None
        self.current_project_index = None
        self.current_weekly_index = None
        self._clear_dirty()
        self.refresh_student_list()
        self.statusBar().showMessage(f"Geladen: {os.path.basename(file_path)}", 4000)

    def _save_to_current_file(self) -> bool:
        try:
            with open(self.current_file, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Datei konnte nicht gespeichert werden:\n{exc}")
            self._mark_dirty()
            return False

        self._clear_dirty()
        return True

    # -------------------------------------------------------------------------
    # Fenster schliessen
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        self._write_editor_to_current_weekly()
        self._write_project_fields_to_current_project()
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
