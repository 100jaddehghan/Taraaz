from pathlib import Path
from functools import lru_cache
from PyQt6.QtGui import QFontDatabase
from html import escape
from uuid import uuid4
import json
import re
from urllib.request import Request, urlopen
from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF
from PyQt6.QtCore import QRectF, QSizeF, Qt
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QPainter, QColor, QFont, QPdfWriter, QTextDocument, QPageSize, QPageLayout


@lru_cache(maxsize=1)
def persian_font():
    for weight in ("Regular","Bold"):
        QFontDatabase.addApplicationFont(str(Path(__file__).with_name(f"Vazirmatn-{weight}.ttf")))
    return "Vazirmatn"


def statement_html(client, projects, entries, currency, bill, money, day, issued, fa):
    def t(en, local):
        return local if fa else en
    def row(values, header=False):
        tag = "th" if header else "td"
        return "<tr>" + "".join(f"<{tag}>{escape(str(v))}</{tag}>" for v in values) + "</tr>"
    amounts = [(p, bill(p), p["received"]) for p in projects]
    statuses = {"waiting":"در انتظار","paused":"متوقف","active":"در جریان","completed":"تکمیل‌شده"}
    lines = [row([t("Project","پروژه"),t("Status","وضعیت"),t("Billable","مبلغ کار"),t("Paid","دریافت"),t("Balance","مانده")],True)]
    for p,total,paid in amounts:
        lines.append(row([p["title"],statuses[p["status"]] if fa else p["status"].title(),money(total),money(paid),money(total-paid)]))
    totals = [sum(v[i] for v in amounts) for i in (1,2)]
    lines.append(row([t("Total","جمع"),"",money(totals[0]),money(totals[1]),money(totals[0]-totals[1])],True))
    payments = [row([t("Date","تاریخ"),t("Project","پروژه"),t("Payment","پرداخت")],True)]
    ids = {p["id"] for p in projects}
    for e in entries:
        if e["project_id"] in ids and e["kind"] == "income":
            payments.append(row([day(e["day"]),e["project"],money(e["amount"])]))
    if len(payments)==1:
        payments.append(row([t("No payments recorded","پرداختی ثبت نشده است"),"",""]))
    direction = "rtl" if fa else "ltr"
    alignment = "right" if fa else "left"
    def section_table(rows):
        return ('<table width="100%" cellspacing="0" cellpadding="7"><thead>' +
                rows[0] + '</thead>' + ''.join(rows[1:]) + '</table>')
    return f"""<html><head><style>
    body {{font-family:'{persian_font() if fa else 'Segoe UI'}';color:#233f39;font-size:10pt}}
    h2 {{font-size:14pt;color:#165347;margin-top:22px;margin-bottom:8px}}
    td {{border-bottom:1px solid #d6e3dd}} th {{background:#dcEAE2;color:#173c34}}
    </style></head><body dir="{direction}" style="text-align:{alignment}">
    <table width="100%" cellspacing="0" cellpadding="16"><tr><td bgcolor="#133e36" width="70%">
    <font color="#bfe899" size="4"><b>{t("Taraaz","تراز")}</b></font><br>
    <font color="#ffffff" size="6"><b>{t("Client statement","صورت‌حساب مشتری")}</b></font></td>
    <td bgcolor="#21594b"><font color="white">{issued}<br>{currency}</font></td></tr></table>
    <h2>{escape(client)}</h2>
    <table width="100%" cellpadding="10" cellspacing="2"><tr>
    <td bgcolor="#eef4ed">{t("Billable","مبلغ کار")}<br><b>{money(totals[0])}</b></td>
    <td bgcolor="#eef4ed">{t("Paid","دریافتی")}<br><b>{money(totals[1])}</b></td>
    <td bgcolor="#dbedcb">{t("Balance","ماندهٔ حساب")}<br><b>{money(totals[0]-totals[1])}</b></td></tr></table>
    <h2>{t("Project balances","ماندهٔ پروژه‌ها")}</h2>{section_table(lines)}
    <h2>{t("Payment history","ریز پرداخت‌ها")}</h2>{section_table(payments)}
    </body></html>"""


def pdf_bytes(html):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(96)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15,16,15,14), QPageLayout.Unit.Millimeter)
    writer.setTitle("Taraaz | Client statement")
    width, height = writer.width(), writer.height()
    body_height = height - 85
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(writer)
    doc.setDocumentMargin(0)
    doc.setHtml(html)
    doc.setPageSize(QSizeF(width,body_height))
    pages = doc.pageCount()
    signature = QSvgRenderer(str(Path(__file__).with_name("signature.svg")))
    painter = QPainter(writer)
    for page in range(pages):
        if page:
            writer.newPage()
        painter.save()
        painter.setClipRect(QRectF(0,0,width,body_height))
        painter.translate(0,-page*body_height)
        doc.drawContents(painter,QRectF(0,page*body_height,width,body_height))
        painter.restore()
        painter.setPen(QColor("#c7d9ce"))
        painter.drawLine(0,body_height+10,width,body_height+10)
        painter.setPen(QColor("#496959"))
        painter.setFont(QFont("Segoe UI",9))
        painter.drawText(0,height-9,f"Taraaz   /   {page+1} · {pages}")
        if page == pages-1:
            signature.render(painter,QRectF(width-185,body_height+17,185,57))
    painter.end()
    del writer
    data = bytes(buffer.data())
    if not data.startswith(b"%PDF") or b"%%EOF" not in data[-100:]:
        raise OSError("PDF creation failed.")
    return data


def send_pdf(token, chat, data):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not chat.strip():
        raise ValueError("Invalid Telegram configuration.")
    boundary = uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="Taraaz-statement.pdf"\r\n'
            'Content-Type: application/pdf\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = Request(f"https://api.telegram.org/bot{token}/sendDocument",data=body,
                  headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with urlopen(req,timeout=25) as response:
        if not json.load(response).get("ok"):
            raise ValueError("Telegram rejected the document.")
