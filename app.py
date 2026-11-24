from html import escape
import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QTimer, QEventLoop, QSaveFile, QIODevice
from PyQt6.QtWidgets import QTextBrowser, QPlainTextEdit, QProgressDialog
from client_report import statement_html, pdf_bytes, send_pdf, persian_font
import random
import csv
import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
from PyQt6.QtCore import QSettings, QLocale, QCalendar
from PyQt6.QtGui import QIcon, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtCore import QRectF, QVariantAnimation
from PyQt6.QtWidgets import QMenu, QWidgetAction

from PyQt6.QtCore import Qt, QDate, QStandardPaths, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QFrame, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox, QDateEdit,
    QFileDialog, QAbstractItemView, QTabWidget, QButtonGroup, QGraphicsOpacityEffect
)
from ledger import Ledger, STATUSES, KINDS, MAX_AMOUNT, seed_demo

JALALI = QCalendar(QCalendar.System.Jalali)


def jalali_date(iso_day):
    return QDate.fromString(iso_day, Qt.DateFormat.ISODate).toString("yyyy/MM/dd", JALALI)


SCALES = {"IRR": 1, "USD": 100, "EUR": 100, "IRT": 1}


FA = json.loads(Path(__file__).with_name("fa.json").read_text("utf8"))
preferences = QSettings("Taraaz", "Appearance")
language = preferences.value("language", "en")


def tr(text):
    return FA.get(text, text) if language == "fa" else text


bot_token = os.getenv("TARAAZ_BOT_TOKEN","")
neon_hue = random.randrange(360)


def neon_color(offset, saturation, lightness):
    return QColor.fromHsl((neon_hue + offset) % 360, saturation, lightness)


class AuroraHeader(QFrame):
    def __init__(self):
        super().__init__()
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(450)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(1.0)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(lambda _: self.update())

    def paintEvent(self, event):
        super().paintEvent(event)
        if preferences.value("theme", "light") != "neon":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 18, 18)
        painter.setClipPath(clip)
        width, height = self.width(), self.height()
        phase = self.motion.currentValue() or 0.0
        for i in range(14):
            curve = QPainterPath()
            curve.moveTo(width * .27, height + 6 + i * 2)
            curve.cubicTo(width * .49, height * (1.4 - .04*i),
                          width * (.55 + .06*phase), -height * (.1 + .03*i),
                          width * .94, height * (.9 - .075*i))
            color = neon_color(i * 6, 215, 175)
            color.setAlpha(88)
            painter.setPen(QPen(color, 1.35))
            painter.drawPath(curve)
        painter.end()


def appearance():
    app = QApplication.instance()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if language == "fa" else Qt.LayoutDirection.LeftToRight)
    QLocale.setDefault(QLocale("fa_IR" if language == "fa" else "en_US"))
    base = Path(__file__).parent
    css = (base / "style.qss").read_text("utf-8-sig")
    theme = preferences.value("theme", "light")
    if theme in ("dark", "neon"):
        css += (base / "dark.qss").read_text("utf8")
    if theme == "neon":
        palette = (base / "neon.qss").read_text("utf8")
        for token, offset, sat, light in (
            ("ACCENT", 0, 200, 185), ("SECONDARY", 87, 140, 89),
            ("DEEP", 0, 115, 37), ("DUSK", 87, 125, 50),
            ("EDGE", 35, 104, 130)
        ):
            palette = palette.replace(token, neon_color(offset, sat, light).name())
        css += palette
    if language == "fa":
        css += f"QWidget {{font-family: '{persian_font()}';}}"
    app.setStyleSheet(css.replace("CHEVRON_PATH", (base / "chevron.svg").resolve().as_posix()))
    app.setWindowIcon(QIcon(str(base / "logo.svg")))


class ProjectPicker(QPushButton):
    def __init__(self, records):
        super().__init__()
        self.records = {r["id"]: r for r in records}
        menu = QMenu(self)
        self.setMenu(menu)
        search = QLineEdit()
        search.setPlaceholderText(tr("Search projects"))
        row = QWidgetAction(menu)
        row.setDefaultWidget(search)
        menu.addAction(row)
        actions = []
        for key, r in self.records.items():
            action = menu.addAction(r["title"] + "  ·  " + r["client"])
            action.triggered.connect(lambda checked=False, k=key: self.select(k))
            actions.append(action)
        def filter_projects(query):
            for action in actions:
                action.setVisible(query.casefold() in action.text().casefold())
        search.textChanged.connect(filter_projects)
        menu.aboutToShow.connect(search.clear)
        self.select(next(iter(self.records)))

    def select(self, key):
        self.key = key
        self.setText(self.records[key]["title"])

    def currentData(self):
        return self.key


def number(amount, currency):
    return f"{Decimal(amount) / SCALES[currency]:,.{2 if SCALES[currency] == 100 else 0}f}"


class MoneyEdit(QLineEdit):
    """Group whole digits while preserving fractional input and caret position."""
    def __init__(self, initial=""):
        super().__init__(initial)
        self.textEdited.connect(self.group_digits)

    def group_digits(self, text):
        normalized = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,"))
        raw = normalized.replace(",", "")
        whole, point, fraction = raw.partition(".")
        if (whole and not whole.isdecimal()) or (fraction and not fraction.isdecimal()):
            return
        groups = []
        for end in range(len(whole), 0, -3):
            groups.append(whole[max(0, end-3):end])
        formatted = ",".join(reversed(groups)) + point + fraction
        if formatted == text:
            return
        logical = len(normalized[:self.cursorPosition()].replace(",", ""))
        cursor = 0
        while cursor < len(formatted) and logical:
            if formatted[cursor] != ",":
                logical -= 1
            cursor += 1
        self.setText(formatted)
        self.setCursorPosition(cursor)


def units(text, scale, maximum=MAX_AMOUNT):
    try:
        value = Decimal(text.strip()) * scale
        if not value.is_finite() or not 0 <= value <= maximum or value != value.to_integral_value():
            raise ValueError
        return int(value)
    except (InvalidOperation, ValueError):
        raise ValueError(tr("Enter a valid non-negative amount with the supported precision.")) from None


def bill(p):
    return (p["contract"] * p["minutes"] + 30) // 60 if p["hourly"] else p["contract"]


def choice(options):
    widget = QComboBox()
    for key, title in options:
        widget.addItem(title, key)
    return widget


class OptionStrip(QFrame):
    currentIndexChanged = pyqtSignal()

    def __init__(self, options):
        super().__init__()
        self.setObjectName("currencyStrip")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for code, caption, description in options:
            control = QPushButton(caption)
            control.setProperty("optionValue", code)
            control.setToolTip(description)
            control.setAccessibleName(description)
            control.setObjectName("currency")
            control.setCheckable(True)
            self.group.addButton(control)
            row.addWidget(control)
            self.buttons[code] = control
        next(iter(self.buttons.values())).setChecked(True)
        self.group.buttonToggled.connect(self.changed)

    def changed(self, button, checked):
        if checked:
            self.currentIndexChanged.emit()

    def currentData(self):
        return self.group.checkedButton().property("optionValue")

    def setCurrentValue(self, code):
        self.buttons[code].setChecked(True)


class CurrencySelector(OptionStrip):
    def __init__(self):
        super().__init__(zip(SCALES, SCALES, (tr("Iranian rial"), tr("US dollar"), tr("Euro"), tr("Iranian toman"))))

    def setCurrentText(self, code):
        self.setCurrentValue(code)


def column_alignment(header):
    numeric = {tr("Billable"), tr("Outstanding"), tr("Received"), tr("Expenses"), tr("Est. profit"), tr("Net cash"), tr("Amount")}
    horizontal = Qt.AlignmentFlag.AlignRight if header in numeric else Qt.AlignmentFlag.AlignLeft
    return horizontal | Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute


def btn(title, callback, primary=False):
    widget = QPushButton(title)
    widget.setObjectName("primary" if primary else "secondary")
    widget.clicked.connect(callback)
    return widget


def title(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    return widget


def grid(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    for index, header in enumerate(headers):
        widget.horizontalHeaderItem(index).setTextAlignment(column_alignment(header))
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(43)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setShowGrid(False)
    widget.setAlternatingRowColors(True)
    return widget


def populate(table, rows):
    table.clearSelection()
    table.setRowCount(len(rows))
    for i, (key, values) in enumerate(rows):
        for j, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            item.setTextAlignment(column_alignment(table.horizontalHeaderItem(j).text()))
            item.setData(Qt.ItemDataRole.UserRole, key)
            table.setItem(i, j, item)


class Form(QDialog):
    def __init__(self, parent, caption):
        super().__init__(parent)
        self.setWindowTitle(caption)
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.addWidget(title(caption, "section"))
        self.fields = QFormLayout()
        self.fields.setVerticalSpacing(12)
        self.fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(self.fields)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def field(self, caption, widget):
        self.fields.addRow(caption, widget)
        return widget

    def accept(self):
        try:
            self.save()
        except (ValueError, sqlite3.Error) as error:
            self.error.setText(str(error))
            return
        super().accept()


class Workspace(QWidget):
    def __init__(self, ledger, demo=False):
        super().__init__()
        self.db = ledger
        self.setWindowTitle(tr("Taraaz • Freelance finance"))
        self.resize(1160, 740)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(Path(__file__).with_name("logo.svg"))).pixmap(38, 38))
        top.addWidget(logo)
        top.addWidget(title(tr("Taraaz"), "brand"))
        top.addStretch()
        top.addWidget(QLabel(tr("Reporting currency")))
        self.currency = CurrencySelector()
        top.addWidget(self.currency)
        top.addWidget(btn(tr("Settings"), self.settings_form))
        layout.addLayout(top)
        hero = self.hero = AuroraHeader()
        hero.setObjectName("hero")
        band = QHBoxLayout(hero)
        band.setContentsMargins(24, 18, 24, 18)
        intro = QVBoxLayout()
        intro.addWidget(title(tr("Financial overview"), "heading"))
        self.context = title("", "light")
        intro.addWidget(self.context)
        band.addLayout(intro)
        band.addStretch()
        band.addWidget(btn(tr("+ New project"), lambda: self.project_form(), True))
        layout.addWidget(hero)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.values = []
        for caption in (tr("Billable value"), tr("Payments received"), tr("Project expenses"), tr("Outstanding")):
            frame = QFrame()
            frame.setObjectName("card")
            column = QVBoxLayout(frame)
            column.setContentsMargins(18, 13, 18, 15)
            column.setSpacing(4)
            column.addWidget(title(caption, "muted"))
            value = title("", "value")
            column.addWidget(value)
            self.values.append(value)
            cards.addWidget(frame, 1)
        layout.addLayout(cards)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.projects = grid([tr("Project"), tr("Client"), tr("Billing"), tr("Billable"), tr("Outstanding"), tr("Status")])
        self.entries = grid([tr("Date"), tr("Project"), tr("Type"), tr("Amount"), tr("Note")])
        self.report = grid([tr("Project"), tr("Billable"), tr("Received"), tr("Expenses"), tr("Outstanding"), tr("Est. profit"), tr("Net cash")])
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search projects or clients"))
        for name, table, controls in [
            (tr("Projects"), self.projects, [self.search, btn(tr("CRM"), self.crm_form), btn(tr("Edit project"), self.edit_project), btn(tr("Log time"), self.log_time), btn(tr("Delete"), self.delete_project)]),
            (tr("Transactions"), self.entries, [btn(tr("+ Transaction"), lambda: self.entry_form(), True), btn(tr("Edit"), self.edit_entry), btn(tr("Delete"), self.delete_entry)]),
            (tr("Financial report"), self.report, [btn(tr("Client statement"), self.client_statement, True),btn(tr("Export CSV"), self.export)])]:
            page = QWidget()
            box = QVBoxLayout(page)
            box.setContentsMargins(16, 16, 16, 16)
            box.setSpacing(12)
            toolbar = QHBoxLayout()
            for control in controls:
                toolbar.addWidget(control)
            if self.search not in controls:
                toolbar.addStretch()
            box.addLayout(toolbar)
            box.addWidget(table)
            self.tabs.addTab(page, name)
        self.demo = demo
        self.currency.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.fade = QGraphicsOpacityEffect(self.tabs)
        self.tabs.setGraphicsEffect(self.fade)
        self.fade.setOpacity(1)
        self.transition = QPropertyAnimation(self.fade, b"opacity", self)
        self.transition.setDuration(190)
        self.transition.setStartValue(0.68)
        self.transition.setEndValue(1.0)
        self.transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.tabs.currentChanged.connect(self.animate)
        self.currency.currentIndexChanged.connect(self.animate)
        self.projects.cellDoubleClicked.connect(lambda *_: self.edit_project())
        self.entries.cellDoubleClicked.connect(lambda *_: self.edit_entry())
        self.refresh()

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_waiting)
        self.reminder_timer.start(60000)
        QTimer.singleShot(800, self.check_waiting)

    def check_waiting(self):
        if not self.isVisible() or QApplication.activeModalWidget():
            return
        today = QDate.currentDate().toString("yyyy-MM-dd")
        rows = self.db.db.execute("SELECT id,title FROM projects WHERE waiting=1 AND COALESCE(reminded,'')<>?",(today,)).fetchall()
        if rows:
            QMessageBox.information(self,tr("Waiting projects"),"\n".join(r["title"] for r in rows))
            with self.db.db:
                self.db.db.executemany("UPDATE projects SET reminded=? WHERE id=?",[(today,r["id"]) for r in rows])

    def crm_form(self):
        project = self.selected(self.projects,self.records)
        if not project:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("CRM · " + project["title"])
        dialog.resize(740, 650)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20,20,20,20)
        layout.setSpacing(12)
        header = QFrame()
        header.setObjectName("hero")
        heading = QVBoxLayout(header)
        heading.setContentsMargins(20,14,20,14)
        heading.addWidget(title(project["title"], "heading"))
        heading.addWidget(title(project["client"]+"   /   "+tr(STATUSES[project["status"]]), "light"))
        layout.addWidget(header)
        search = QLineEdit()
        search.setPlaceholderText(tr("Search follow-ups"))
        layout.addWidget(search)
        history = QTextBrowser()
        history.setAccessibleName(tr("History"))
        layout.addWidget(history,1)
        compose = QFrame()
        compose.setObjectName("card")
        editor = QVBoxLayout(compose)
        editor.addWidget(title(tr("New follow-up"),"section"))
        note = QPlainTextEdit()
        note.setPlaceholderText(tr("Record the conversation, decision or next step…"))
        note.setFixedHeight(82)
        editor.addWidget(note)
        bar = QHBoxLayout()
        bar.addStretch()
        add = btn(tr("Save follow-up"),lambda: save(),True)
        add.setEnabled(False)
        bar.addWidget(add)
        editor.addLayout(bar)
        layout.addWidget(compose)
        def refresh_history():
            dark = preferences.value("theme","light") != "light"
            surface,ink,accent = ("#21342f","#ecf6ef","#a6e8c8") if dark else ("#eaf3ed","#17382e","#25674e")
            cards = []
            query = search.text().strip().casefold()
            for r in self.db.db.execute("SELECT created,note FROM crm WHERE project_id=? ORDER BY id DESC",(project["id"],)):
                if query not in r["note"].casefold():
                    continue
                stamp = jalali_date(r["created"][:10])+" · "+r["created"][11:16]
                body = escape(r["note"]).replace("\n","<br>")
                cards.append(f'<table width="100%" cellspacing="0" cellpadding="10"><tr><td bgcolor="{accent}" width="4"></td>'
                             f'<td bgcolor="{surface}"><font color="{accent}"><b>{stamp}</b></font><br>'
                             f'<font color="{ink}">{body}</font></td></tr></table>')
            direction = "rtl" if language=="fa" else "ltr"
            placeholder = tr("No matching notes.") if query else tr("Add your first follow-up below.")
            history.setHtml(f'<body dir="{direction}">' + ("<br>".join(cards) or escape(placeholder)) + "</body>")
        def save():
            value = note.toPlainText().strip()
            if not value:
                return
            try:
                with self.db.db:
                    self.db.db.execute("INSERT INTO crm(project_id,created,note) VALUES(?,datetime('now','localtime'),?)",
                                       (project["id"],value))
            except sqlite3.Error as error:
                QMessageBox.warning(dialog,tr("Save"),str(error))
                return
            note.clear()
            search.clear()
            refresh_history()
        note.textChanged.connect(lambda: add.setEnabled(bool(note.toPlainText().strip())))
        search.textChanged.connect(refresh_history)
        refresh_history()
        dialog.exec()

    def client_statement(self):
        if not self.records:
            QMessageBox.information(self,tr("Client statement"),tr("Create a project in this currency first."))
            return
        dialog=QDialog(self)
        dialog.setWindowTitle(tr("Client statement"))
        dialog.resize(740,620)
        box=QVBoxLayout(dialog)
        clients=choice((name,name) for name in sorted({p["client"] for p in self.records}))
        box.addWidget(clients)
        preview=QTextBrowser()
        preview.setStyleSheet("background:white;color:#173b35")
        box.addWidget(preview)
        c=self.currency.currentData()
        def html():
            client=clients.currentData()
            return statement_html(client,[p for p in self.records if p["client"]==client],self.transactions,c,
                bill,lambda v:number(v,c),jalali_date,QDate.currentDate().toString("yyyy/MM/dd",JALALI),language=="fa")
        def render():
            preview.setHtml(html())
        clients.currentIndexChanged.connect(render)
        render()
        def export_pdf():
            path,_=QFileDialog.getSaveFileName(dialog,tr("Save PDF"),"Taraaz-statement.pdf","PDF (*.pdf)")
            if path:
                try:
                    data=pdf_bytes(html())
                    out=QSaveFile(path)
                    if not out.open(QIODevice.OpenModeFlag.WriteOnly) or out.write(data)!=len(data) or not out.commit():
                        raise OSError(out.errorString())
                except OSError as error:
                    QMessageBox.warning(dialog,tr("Export failed"),str(error))
        def telegram():
            chat=str(preferences.value("telegram_chat","")).strip()
            if not bot_token or not chat:
                QMessageBox.information(dialog,"Telegram",tr("Enter the bot token and chat ID in Settings."))
                return
            if QMessageBox.question(dialog,"Telegram",tr("Send statement?")+"\n"+clients.currentData()+" → "+chat,
                                    defaultButton=QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
            data=pdf_bytes(html())
            progress=QProgressDialog(tr("Sending document…"),"",0,0,dialog)
            progress.setCancelButton(None)
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.show()
            with ThreadPoolExecutor(max_workers=1) as pool:
                job=pool.submit(send_pdf,bot_token,chat,data)
                loop=QEventLoop()
                poll=QTimer()
                poll.timeout.connect(lambda: loop.quit() if job.done() else None)
                poll.start(100)
                loop.exec()
                poll.stop()
                progress.close()
                if job.exception():
                    QMessageBox.warning(dialog,"Telegram",tr("Delivery could not be confirmed. Check the destination and connection."))
                else:
                    QMessageBox.information(dialog,"Telegram",tr("Delivered."))
        row=QHBoxLayout()
        row.addWidget(btn(tr("Save PDF"),export_pdf,True))
        row.addWidget(btn(tr("Send via Telegram"),telegram))
        box.addLayout(row)
        dialog.exec()

    def settings_form(self):
        global language, bot_token
        form = Form(self, tr("Settings"))
        lang = form.field(tr("Language"), OptionStrip([("en","English","English"),("fa","فارسی","فارسی")]))
        theme = form.field(tr("Theme"), OptionStrip([(key,tr(text),tr(text)) for key,text in (("light","Light"),("dark","Dark"),("neon","Neon"))]))
        token=form.field(tr("Bot token (this session)"),QLineEdit(bot_token))
        token.setEchoMode(QLineEdit.EchoMode.Password)
        chat=form.field(tr("Telegram chat ID"),QLineEdit(str(preferences.value("telegram_chat",""))))
        lang.setCurrentValue(language)
        theme.setCurrentValue(preferences.value("theme","light"))
        form.save = lambda: None
        if not form.exec():
            return
        bot_token=token.text().strip()
        preferences.setValue("telegram_chat",chat.text().strip())
        language = lang.currentData()
        preferences.setValue("language", language)
        preferences.setValue("theme", theme.currentData())
        preferences.sync()
        appearance()
        replacement = Workspace(self.db, self.demo)
        replacement.currency.setCurrentText(self.currency.currentData())
        replacement.tabs.setCurrentIndex(self.tabs.currentIndex())
        replacement.search.setText(self.search.text())
        replacement.setGeometry(self.geometry())
        replacement.setWindowState(self.windowState())
        QApplication.instance().workspace = replacement
        replacement.show()
        self.close()
        self.deleteLater()

    def rotate_neon(self):
        global neon_hue
        if preferences.value("theme", "light") == "neon":
            neon_hue = (neon_hue + random.randint(68, 157)) % 360
            appearance()
            self.hero.motion.stop()
            self.hero.motion.start()

    def animate(self):
        self.rotate_neon()
        self.transition.stop()
        self.transition.start()

    def refresh(self):
        c = self.currency.currentData()
        self.records = [p for p in self.db.projects() if p["currency"] == c]
        ids = {p["id"] for p in self.records}
        self.transactions = [e for e in self.db.entries() if e["project_id"] in ids]
        self.rows = []
        projects = []
        query = self.search.text().strip().casefold()
        for p in self.records:
            total, paid, spent = bill(p), p["received"], p["spent"]
            due = max(0, total - paid)
            self.rows.append((p["id"], (p["title"], total, paid, spent, due, total - spent, paid - spent)))
            billing = f"{p['minutes']//60}h {p['minutes']%60}m @ {number(p['contract'], c)}/h" if p["hourly"] else tr("Fixed fee")
            if query in (p["title"] + " " + p["client"]).casefold():
                projects.append((p["id"], (p["title"], p["client"], billing, number(total,c), number(due,c), tr(STATUSES[p["status"]]))))
        for i, widget in enumerate(self.values, 1):
            widget.setText(number(sum(row[i] for _, row in self.rows), c))
        self.context.setText(f"{len(ids)} {tr('Projects')}   /   {c}" + (tr("   /   Demo workspace") if self.demo else ""))
        populate(self.projects, projects)
        populate(self.entries, [(e["id"], (jalali_date(e["day"]), e["project"], tr(KINDS[e["kind"]]), number(e["amount"], c), e["note"])) for e in self.transactions])
        populate(self.report, [(key, (row[0], *(number(v,c) for v in row[1:]))) for key,row in self.rows])

    def selected(self, table, rows):
        indexes = table.selectionModel().selectedRows()
        if indexes:
            key = indexes[0].data(Qt.ItemDataRole.UserRole)
            return next((r for r in rows if r["id"] == key), None)
        QMessageBox.information(self, tr("Select a row"), tr("Select a row first."))

    def edit_project(self):
        record = self.selected(self.projects, self.records)
        if record:
            self.project_form(record)

    def project_form(self, p=None):
        form = Form(self, tr("Edit project") if p else tr("New project"))
        name = form.field(tr("Project name"), QLineEdit(p["title"] if p else ""))
        client = form.field(tr("Client"), QLineEdit(p["client"] if p else ""))
        form.setMinimumWidth(485)
        form.fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.fields.setVerticalSpacing(12)
        c = form.field(tr("Currency"), CurrencySelector())
        c.setCurrentText(p["currency"] if p else self.currency.currentData())
        c.setEnabled(p is None)
        mode = form.field(tr("Billing method"), OptionStrip([(0,tr("Fixed fee"),tr("Total contract amount")),(1,tr("Hourly"),tr("Fixed rate per hour worked"))]))
        mode.setCurrentValue(p["hourly"] if p else 0)
        mode.setEnabled(p is None)
        amount = form.field(tr("Fee / hourly rate"), MoneyEdit(number(p["contract"], c.currentData()) if p else ""))
        amount.setReadOnly(bool(p and p["hourly"] and p["minutes"]))
        def update_amount_label():
            caption = tr("Hourly rate") if mode.currentData() else tr("Contract amount")
            form.fields.labelForField(amount).setText(f"{caption} ({c.currentData()})")
            amount.setPlaceholderText("0.00" if SCALES[c.currentData()] == 100 else "0")
        c.currentIndexChanged.connect(update_amount_label)
        mode.currentIndexChanged.connect(update_amount_label)
        update_amount_label()
        status = form.field(tr("Status"), OptionStrip([(key, tr(text), tr(text)) for key, text in STATUSES.items()]))
        if p:
            status.setCurrentValue(p["status"])
        def save():
            if not name.text().strip() or not client.text().strip():
                raise ValueError(tr("Enter a project name and client."))
            rate = units(amount.text().replace(",",""), SCALES[c.currentData()])
            if mode.currentData() and not rate:
                raise ValueError(tr("Hourly rate must be positive."))
            self.db.save_project(p["id"] if p else None, name.text(), client.text(), rate, status.currentData(),
                                 c.currentData(), mode.currentData(), p["minutes"] if p else 0)
        form.save = save
        if form.exec():
            self.rotate_neon()
            self.currency.setCurrentText(c.currentData())
            self.refresh()

    def log_time(self):
        p = self.selected(self.projects, self.records)
        if not p:
            return
        if not p["hourly"]:
            QMessageBox.information(self,tr("Fixed-fee project"),tr("Time can be logged on hourly projects."))
            return
        form = Form(self, tr("Log time"))
        form.field(tr("Project"), QLabel(p["title"]))
        hours = form.field(tr("Hours"), QLineEdit("0"))
        minutes = form.field(tr("Minutes (0–59)"), QLineEdit("0"))
        def save():
            duration = units(hours.text(),1,9999)*60 + units(minutes.text(),1,59)
            if not duration:
                raise ValueError(tr("Enter a positive duration."))
            with self.db.db:
                self.db.db.execute("UPDATE projects SET minutes=minutes+? WHERE id=?", (duration,p["id"]))
        form.save = save
        if form.exec():
            self.rotate_neon()
            self.refresh()

    def edit_entry(self):
        e = self.selected(self.entries, self.transactions)
        if e:
            self.entry_form(e)

    def entry_form(self, e=None):
        if not self.records:
            QMessageBox.information(self,tr("New transaction"),tr("Create a project in this currency first."))
            return
        form = Form(self,tr("Edit transaction") if e else tr("New transaction"))
        project = form.field(tr("Project"),ProjectPicker(self.records))
        kind = form.field(tr("Type"),OptionStrip([(key,tr(text),tr(text)) for key,text in KINDS.items()]))
        c = self.currency.currentData()
        amount = form.field(f"{tr('Amount')} ({c})",MoneyEdit(number(e["amount"],c) if e else ""))
        day = form.field(tr("Date (Solar Hijri)"),QDateEdit(QDate.currentDate()))
        day.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        day.setCalendarPopup(True)
        day.setCalendar(JALALI)
        day.calendarWidget().setCalendar(JALALI)
        day.setDisplayFormat("yyyy/MM/dd")
        note = form.field(tr("Note"),QLineEdit(e["note"] if e else ""))
        if e:
            project.select(e["project_id"])
            kind.setCurrentValue(e["kind"])
            day.setDate(QDate.fromString(e["day"],"yyyy-MM-dd"))
        def save():
            value = units(amount.text().replace(",",""), SCALES[c])
            if not value:
                raise ValueError(tr("Amount must be positive."))
            self.db.save_entry(e["id"] if e else None,project.currentData(),kind.currentData(),value,day.date().toString("yyyy-MM-dd"),note.text())
        form.save = save
        if form.exec():
            self.rotate_neon()
            self.refresh()

    def remove(self, table, rows, delete):
        row = self.selected(table, rows)
        if row and QMessageBox.question(self,tr("Delete record"),tr("Permanently delete this record?"),defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                delete(row["id"])
                self.rotate_neon()
            except sqlite3.Error:
                QMessageBox.warning(self,tr("Deletion blocked"),tr("A project with transactions cannot be deleted."))
            self.refresh()

    def delete_project(self):
        self.remove(self.projects,self.records,self.db.delete_project)

    def delete_entry(self):
        self.remove(self.entries,self.transactions,self.db.delete_entry)

    def export(self):
        c = self.currency.currentData()
        path,_ = QFileDialog.getSaveFileName(self,tr("Export financial report"),f"taraaz-{c}.csv","CSV (*.csv)")
        if path:
            try:
                with open(path,"w",encoding="utf-8-sig",newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow([tr("Project"),tr("Currency"),tr("Billable"),tr("Received"),tr("Expenses"),tr("Outstanding"),tr("Est. profit"),tr("Net cash")])
                    for _,row in self.rows:
                        name = row[0]
                        if name.lstrip().startswith(("=","+","-","@")) or name.startswith(("\t","\n","\r")):
                            name = "'" + name
                        writer.writerow([name,c,*(number(v,c).replace(",","") for v in row[1:])])
                self.rotate_neon()
            except OSError as error:
                QMessageBox.warning(self,tr("Export failed"),str(error))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo",action="store_true")
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Taraaz")
    app.setStyle("Fusion")
    appearance()
    path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "taraaz.sqlite3"
    ledger = Ledger(":memory:" if args.demo else path)
    if args.demo:
        seed_demo(ledger)
    window = Workspace(ledger,args.demo)
    window.show()
    try:
        return app.exec()
    finally:
        ledger.close()


if __name__ == "__main__":
    sys.exit(main())



