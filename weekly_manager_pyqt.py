# weekly_manager_pyqt.py
# Python 3.10+
# Benötigt: PyQt6
# Installation: pip install PyQt6

import json
import os
import sys
from copy import deepcopy

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QDateEdit,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QGroupBox,
    QFrame,
    QToolBar,
    QStatusBar,
    QStyleFactory,
    QSizePolicy,
)


def make_empty_weekly(date_str: str, planned: str = "") -> dict:
    return {
        "date": date_str,                  # ISO-Format: YYYY-MM-DD
        "planned": planned,                # Was war geplant
        "done": "",                        # Was wurde gemacht
        "next_planned": "",                # Was ist geplant
    }


def validate_data(data: dict) -> dict:
    """
    Stellt sicher, dass die JSON-Struktur gültig ist.
    Falls Felder fehlen, werden sie sinnvoll ergänzt.
    """
    if not isinstance(data, dict):
        raise ValueError("JSON-Wurzel muss ein Objekt sein.")

    if "students" not in data or not isinstance(data["students"], dict):
        data["students"] = {}

    cleaned = {"version": 1, "students": {}}

    for student_name, weeklies in data["students"].items():
        if not isinstance(student_name, str):
            continue
        if not isinstance(weeklies, list):
            weeklies = []

        cleaned_weeklies = []
        for w in weeklies:
            if not isinstance(w, dict):
                continue

            date_str = str(w.get("date", QDate.currentDate().toString(Qt.DateFormat.ISODate)))
            # Datum grob prüfen
            qd = QDate.fromString(date_str, Qt.DateFormat.ISODate)
            if not qd.isValid():
                date_str = QDate.currentDate().toString(Qt.DateFormat.ISODate)

            cleaned_weeklies.append({
                "date": date_str,
                "planned": str(w.get("planned", "")),
                "done": str(w.get("done", "")),
                "next_planned": str(w.get("next_planned", "")),
            })

        cleaned["students"][student_name] = cleaned_weeklies

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
        self.resize(1350, 820)

        # Datenmodell
        self.data = {"version": 1, "students": {}}
        self.current_file = None

        # Auswahlzustand
        self.current_student = None              # str | None
        self.current_weekly_index = None         # int | None (Index in self.data["students"][student])
        self._loading_ui = False
        self._dirty = False

        self._build_ui()
        self._apply_style()
        self._connect_signals()

        self.statusBar().showMessage("Bereit")
        self._update_window_title()

    # -------------------------------------------------------------------------
    # UI Aufbau
    # -------------------------------------------------------------------------
    def _build_ui(self):
        self.setStatusBar(QStatusBar(self))

        # Toolbar
        toolbar = QToolBar("Hauptleiste")
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        self.addToolBar(toolbar)

        self.act_new = QAction("Neu", self)
        self.act_open = QAction("Laden", self)
        self.act_save = QAction("Speichern", self)
        self.act_save_as = QAction("Speichern unter", self)

        toolbar.addAction(self.act_new)
        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_save)
        toolbar.addAction(self.act_save_as)

        toolbar.addSeparator()

        self.act_add_student = QAction("Studierende:n hinzufügen", self)
        self.act_remove_student = QAction("Studierende:n entfernen", self)
        toolbar.addAction(self.act_add_student)
        toolbar.addAction(self.act_remove_student)

        toolbar.addSeparator()

        self.act_new_weekly = QAction("Neues Weekly", self)
        self.act_delete_weekly = QAction("Weekly löschen", self)
        self.act_commit = QAction("Änderungen übernehmen", self)
        toolbar.addAction(self.act_new_weekly)
        toolbar.addAction(self.act_delete_weekly)
        toolbar.addAction(self.act_commit)

        # Zentraler Bereich
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        self.info_label = QLabel(
            "Tipp: Ein neues Weekly übernimmt automatisch „Was ist geplant“ aus dem letzten Weekly als „Was war geplant“."
        )
        self.info_label.setObjectName("InfoLabel")
        root_layout.addWidget(self.info_label)

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
        self.btn_add_student = QPushButton("＋ Hinzufügen")
        self.btn_remove_student = QPushButton("－ Entfernen")
        student_btn_row.addWidget(self.btn_add_student)
        student_btn_row.addWidget(self.btn_remove_student)
        left_card.content_layout.addLayout(student_btn_row)

        # --- Mittlere Spalte: Übersicht Weeklies ---
        middle_card = Card("Weekly-Übersicht")
        splitter.addWidget(middle_card)

        self.weekly_summary_label = QLabel("Keine Studierenden ausgewählt")
        self.weekly_summary_label.setObjectName("SubtleLabel")
        middle_card.content_layout.addWidget(self.weekly_summary_label)

        self.weekly_list = QListWidget()
        self.weekly_list.setObjectName("WeeklyList")
        self.weekly_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        middle_card.content_layout.addWidget(self.weekly_list, 1)

        weekly_btn_row = QHBoxLayout()
        self.btn_new_weekly = QPushButton("Neues Weekly")
        self.btn_delete_weekly = QPushButton("Löschen")
        self.btn_duplicate_hint = QPushButton("Letzten Plan übernehmen")
        self.btn_duplicate_hint.setEnabled(False)  # nur Hinweis/Shortcut für neues Weekly
        weekly_btn_row.addWidget(self.btn_new_weekly)
        weekly_btn_row.addWidget(self.btn_delete_weekly)
        weekly_btn_row.addWidget(self.btn_duplicate_hint)
        middle_card.content_layout.addLayout(weekly_btn_row)

        # --- Rechte Spalte: Editor ---
        right_card = Card("Weekly bearbeiten")
        splitter.addWidget(right_card)

        meta_row = QHBoxLayout()
        lbl_date = QLabel("Datum")
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
        self.txt_planned.setPlaceholderText("Plan aus der letzten Woche wird hier automatisch übernommen …")
        self._set_group_layout(self.grp_planned, self.txt_planned)
        right_card.content_layout.addWidget(self.grp_planned, 1)

        self.grp_done = QGroupBox("Was wurde gemacht?")
        self.txt_done = QTextEdit()
        self.txt_done.setPlaceholderText("Kurz zusammenfassen, was tatsächlich erledigt wurde …")
        self._set_group_layout(self.grp_done, self.txt_done)
        right_card.content_layout.addWidget(self.grp_done, 1)

        self.grp_next = QGroupBox("Was ist geplant?")
        self.txt_next = QTextEdit()
        self.txt_next.setPlaceholderText("Plan für das nächste Weekly …")
        self._set_group_layout(self.grp_next, self.txt_next)
        right_card.content_layout.addWidget(self.grp_next, 1)

        editor_btn_row = QHBoxLayout()
        self.btn_commit = QPushButton("Änderungen übernehmen")
        self.btn_commit.setObjectName("PrimaryButton")
        self.btn_reset_editor = QPushButton("Editor leeren")
        editor_btn_row.addWidget(self.btn_commit)
        editor_btn_row.addWidget(self.btn_reset_editor)
        right_card.content_layout.addLayout(editor_btn_row)

        splitter.setSizes([260, 360, 730])

        self._set_editor_enabled(False)

    def _set_group_layout(self, groupbox: QGroupBox, editor: QTextEdit):
        layout = QVBoxLayout(groupbox)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.addWidget(editor)

    def _connect_signals(self):
        # Toolbar Aktionen
        self.act_new.triggered.connect(self.new_dataset)
        self.act_open.triggered.connect(self.load_json_dialog)
        self.act_save.triggered.connect(self.save_json)
        self.act_save_as.triggered.connect(self.save_json_as)
        self.act_add_student.triggered.connect(self.add_student)
        self.act_remove_student.triggered.connect(self.remove_student)
        self.act_new_weekly.triggered.connect(self.add_weekly)
        self.act_delete_weekly.triggered.connect(self.delete_weekly)
        self.act_commit.triggered.connect(self.commit_current_weekly)

        # Buttons
        self.btn_add_student.clicked.connect(self.add_student)
        self.btn_remove_student.clicked.connect(self.remove_student)
        self.btn_new_weekly.clicked.connect(self.add_weekly)
        self.btn_delete_weekly.clicked.connect(self.delete_weekly)
        self.btn_commit.clicked.connect(self.commit_current_weekly)
        self.btn_reset_editor.clicked.connect(self.clear_editor)
        self.btn_duplicate_hint.clicked.connect(self.add_weekly)

        # Listen
        self.student_list.currentItemChanged.connect(self.on_student_changed)
        self.weekly_list.currentItemChanged.connect(self.on_weekly_changed)

        # Editor-Änderungen -> dirty markieren
        self.date_edit.dateChanged.connect(self._mark_dirty)
        self.txt_planned.textChanged.connect(self._mark_dirty)
        self.txt_done.textChanged.connect(self._mark_dirty)
        self.txt_next.textChanged.connect(self._mark_dirty)

    # -------------------------------------------------------------------------
    # Styling
    # -------------------------------------------------------------------------
    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))

        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        self.setStyleSheet("""
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

            QLabel#InfoLabel {
                color: #3a4a5e;
                background: #ffffff;
                border: 1px solid #e3e8f0;
                border-radius: 10px;
                padding: 10px 12px;
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
            QPushButton#PrimaryButton {
                background: #2563eb;
                color: white;
                border: 1px solid #1d4ed8;
                font-weight: 600;
            }
            QPushButton#PrimaryButton:hover {
                background: #1d4ed8;
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

            QTextEdit, QDateEdit {
                background: white;
                border: 1px solid #dbe2ec;
                border-radius: 10px;
                padding: 8px;
            }
            QTextEdit:focus, QDateEdit:focus {
                border: 1px solid #60a5fa;
            }

            QStatusBar {
                background: #ffffff;
                border-top: 1px solid #e3e8f0;
            }
        """)

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
        self.setWindowTitle(f"Studierenden-Weeklies Manager – {filename}{dirty}")

    def _set_editor_enabled(self, enabled: bool):
        self.date_edit.setEnabled(enabled)
        self.txt_planned.setEnabled(enabled)
        self.txt_done.setEnabled(enabled)
        self.txt_next.setEnabled(enabled)
        self.btn_commit.setEnabled(enabled)
        self.btn_reset_editor.setEnabled(enabled)

    def _current_student_weeklies(self):
        if self.current_student is None:
            return None
        return self.data["students"].get(self.current_student)

    def _weekly_preview_text(self, w: dict) -> str:
        """
        Text für die Weekly-Übersicht.
        """
        date_str = w.get("date", "")
        done = (w.get("done") or "").strip().splitlines()
        nextp = (w.get("next_planned") or "").strip().splitlines()

        preview = ""
        if done:
            preview = done[0]
        elif nextp:
            preview = "Nächster Plan: " + nextp[0]
        else:
            preview = "Noch keine Inhalte"

        preview = preview.strip()
        if len(preview) > 70:
            preview = preview[:67] + "…"

        return f"{date_str}  •  {preview}"

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

    def clear_editor(self):
        if self.current_weekly_index is None:
            return
        self._loading_ui = True
        try:
            self.date_edit.setDate(QDate.currentDate())
            self.txt_planned.clear()
            self.txt_done.clear()
            self.txt_next.clear()
        finally:
            self._loading_ui = False
        self._mark_dirty()

    # -------------------------------------------------------------------------
    # Datenoperationen / Rendering
    # -------------------------------------------------------------------------
    def refresh_student_list(self, select_name: str | None = None):
        self.student_list.blockSignals(True)
        self.student_list.clear()

        for name in sorted(self.data["students"].keys(), key=str.lower):
            item = QListWidgetItem(name)
            self.student_list.addItem(item)

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
            self.current_weekly_index = None
            self.refresh_weekly_list()
            self._set_editor_enabled(False)

    def refresh_weekly_list(self, select_index: int | None = None):
        self.weekly_list.blockSignals(True)
        self.weekly_list.clear()

        weeklies = self._current_student_weeklies()

        if self.current_student is None or weeklies is None:
            self.weekly_summary_label.setText("Keine Studierenden ausgewählt")
            self.weekly_list.blockSignals(False)
            self._set_editor_enabled(False)
            self.current_weekly_index = None
            return

        count = len(weeklies)
        self.weekly_summary_label.setText(f"{self.current_student} • {count} Weekly(s)")

        # Neueste oben anzeigen, aber Originalindex als UserRole speichern
        for original_index in reversed(range(count)):
            w = weeklies[original_index]
            item = QListWidgetItem(self._weekly_preview_text(w))
            item.setData(Qt.ItemDataRole.UserRole, original_index)
            self.weekly_list.addItem(item)

        self.weekly_list.blockSignals(False)

        self._set_editor_enabled(count > 0)
        self.btn_delete_weekly.setEnabled(count > 0)
        self.act_delete_weekly.setEnabled(count > 0)
        self.btn_duplicate_hint.setEnabled(self.current_student is not None)

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

        # Auswahl wiederherstellen
        target_row = None
        if select_index is not None:
            for row in range(self.weekly_list.count()):
                if self.weekly_list.item(row).data(Qt.ItemDataRole.UserRole) == select_index:
                    target_row = row
                    break

        if target_row is None:
            target_row = 0  # neueste zuerst

        self.weekly_list.setCurrentRow(target_row)

    # -------------------------------------------------------------------------
    # Events: Auswahlwechsel
    # -------------------------------------------------------------------------
    def on_student_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        # Vorheriges Weekly übernehmen (falls offen)
        if previous is not None:
            self.commit_current_weekly(show_message=False)

        if current is None:
            self.current_student = None
            self.current_weekly_index = None
            self.refresh_weekly_list()
            return

        self.current_student = current.text()
        self.current_weekly_index = None
        self.refresh_weekly_list()

    def on_weekly_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        # Vorheriges Weekly übernehmen
        if previous is not None:
            self.commit_current_weekly(show_message=False)

        if current is None:
            self.current_weekly_index = None
            self._set_editor_enabled(False)
            return

        idx = current.data(Qt.ItemDataRole.UserRole)
        self.current_weekly_index = int(idx)

        weeklies = self._current_student_weeklies()
        if weeklies is None or not (0 <= self.current_weekly_index < len(weeklies)):
            self.current_weekly_index = None
            self._set_editor_enabled(False)
            return

        self._set_editor_enabled(True)
        self._load_weekly_into_editor(weeklies[self.current_weekly_index])

    # -------------------------------------------------------------------------
    # CRUD Studierende
    # -------------------------------------------------------------------------
    def add_student(self):
        name, ok = QInputDialog.getText(self, "Studierende:n hinzufügen", "Name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return

        if name in self.data["students"]:
            QMessageBox.information(self, "Hinweis", "Diese Person existiert bereits.")
            self.refresh_student_list(select_name=name)
            return

        self.data["students"][name] = []
        self._mark_dirty()
        self.refresh_student_list(select_name=name)
        self.statusBar().showMessage(f"Studierende:r '{name}' hinzugefügt", 3000)

    def remove_student(self):
        item = self.student_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine Person auswählen.")
            return

        name = item.text()
        reply = QMessageBox.question(
            self,
            "Studierende:n entfernen",
            f"Soll '{name}' inklusive aller Weeklies wirklich entfernt werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.data["students"].pop(name, None)
        self.current_student = None
        self.current_weekly_index = None
        self._mark_dirty()
        self.refresh_student_list()
        self.statusBar().showMessage(f"'{name}' entfernt", 3000)

    # -------------------------------------------------------------------------
    # CRUD Weeklies
    # -------------------------------------------------------------------------
    def add_weekly(self):
        if self.current_student is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst eine:n Studierende:n auswählen.")
            return

        # Aktuelles Weekly speichern
        self.commit_current_weekly(show_message=False)

        weeklies = self._current_student_weeklies()
        if weeklies is None:
            return

        # Automatisch Plan aus letztem Weekly übernehmen:
        # letztes Weekly = zuletzt angelegter Eintrag in der Liste (append-Reihenfolge)
        inherited_planned = ""
        if len(weeklies) > 0:
            inherited_planned = weeklies[-1].get("next_planned", "")

        new_entry = make_empty_weekly(
            date_str=QDate.currentDate().toString(Qt.DateFormat.ISODate),
            planned=inherited_planned
        )
        weeklies.append(new_entry)
        new_index = len(weeklies) - 1

        self._mark_dirty()
        self.refresh_weekly_list(select_index=new_index)
        self.statusBar().showMessage("Neues Weekly angelegt (Plan übernommen)", 3000)

    def delete_weekly(self):
        if self.current_student is None or self.current_weekly_index is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst ein Weekly auswählen.")
            return

        weeklies = self._current_student_weeklies()
        if weeklies is None or not (0 <= self.current_weekly_index < len(weeklies)):
            return

        w = weeklies[self.current_weekly_index]
        reply = QMessageBox.question(
            self,
            "Weekly löschen",
            f"Soll das Weekly vom {w.get('date', 'unbekannt')} wirklich gelöscht werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del weeklies[self.current_weekly_index]
        self.current_weekly_index = None
        self._mark_dirty()
        self.refresh_weekly_list()
        self.statusBar().showMessage("Weekly gelöscht", 3000)

    def commit_current_weekly(self, show_message: bool = True):
        """
        Überträgt den Editor-Inhalt in das aktuell ausgewählte Weekly.
        """
        if self._loading_ui:
            return True

        if self.current_student is None or self.current_weekly_index is None:
            return True

        weeklies = self._current_student_weeklies()
        if weeklies is None:
            return False

        if not (0 <= self.current_weekly_index < len(weeklies)):
            return False

        entry = weeklies[self.current_weekly_index]
        entry["date"] = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        entry["planned"] = self.txt_planned.toPlainText().rstrip()
        entry["done"] = self.txt_done.toPlainText().rstrip()
        entry["next_planned"] = self.txt_next.toPlainText().rstrip()

        # Liste neu zeichnen, damit Preview aktualisiert wird
        selected_index = self.current_weekly_index
        self.refresh_weekly_list(select_index=selected_index)

        self._clear_dirty()
        if show_message:
            self.statusBar().showMessage("Änderungen übernommen", 2000)
        return True

    # -------------------------------------------------------------------------
    # Dateioperationen (JSON)
    # -------------------------------------------------------------------------
    def new_dataset(self):
        if not self._confirm_discard_if_needed():
            return

        self.data = {"version": 1, "students": {}}
        self.current_file = None
        self.current_student = None
        self.current_weekly_index = None
        self._clear_dirty()
        self.refresh_student_list()
        self.statusBar().showMessage("Neuer Datensatz erstellt", 3000)

    def load_json_dialog(self):
        if not self._confirm_discard_if_needed():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Weeklies laden",
            "",
            "JSON-Dateien (*.json);;Alle Dateien (*)"
        )
        if not file_path:
            return

        self.load_json(file_path)

    def load_json(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.data = validate_data(raw)
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Laden", f"Datei konnte nicht geladen werden:\n{e}")
            return

        self.current_file = file_path
        self.current_student = None
        self.current_weekly_index = None
        self._clear_dirty()
        self.refresh_student_list()
        self.statusBar().showMessage(f"Geladen: {os.path.basename(file_path)}", 4000)

    def save_json(self):
        # Vor dem Speichern Änderungen aus dem Editor übernehmen
        self.commit_current_weekly(show_message=False)

        if not self.current_file:
            return self.save_json_as()

        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Datei konnte nicht gespeichert werden:\n{e}")
            return

        self._clear_dirty()
        self.statusBar().showMessage(f"Gespeichert: {os.path.basename(self.current_file)}", 3000)

    def save_json_as(self):
        self.commit_current_weekly(show_message=False)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Weeklies speichern",
            self.current_file or "weeklies.json",
            "JSON-Dateien (*.json);;Alle Dateien (*)"
        )
        if not file_path:
            return

        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        self.current_file = file_path
        self.save_json()

    def _confirm_discard_if_needed(self) -> bool:
        if not self._dirty:
            return True

        reply = QMessageBox.question(
            self,
            "Ungespeicherte Änderungen",
            "Es gibt ungespeicherte Änderungen. Möchtest du sie verwerfen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    # -------------------------------------------------------------------------
    # Fenster schließen
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        # Letzte Editoränderungen übernehmen (nur in-memory)
        self.commit_current_weekly(show_message=False)

        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Beenden",
                "Es gibt ungespeicherte Änderungen. Wirklich beenden?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Studierenden-Weeklies Manager")

    window = WeeklyManagerWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()