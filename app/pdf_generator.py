from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "assets" / "logo.png"
pdfmetrics.registerFont(TTFont("JnA-Regular", str(ROOT / "assets" / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("JnA-Bold", str(ROOT / "assets" / "DejaVuSans-Bold.ttf")))

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def integer_words(number: int) -> str:
    if number == 0:
        return "Zero"
    if number < 0:
        return "Minus " + integer_words(-number)
    if number < 20:
        return ONES[number]
    if number < 100:
        return TENS[number // 10] + ((" " + ONES[number % 10]) if number % 10 else "")
    if number < 1_000:
        return ONES[number // 100] + " Hundred" + ((" " + integer_words(number % 100)) if number % 100 else "")
    for value, label in ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand")):
        if number >= value:
            return integer_words(number // value) + f" {label}" + ((" " + integer_words(number % value)) if number % value else "")
    raise ValueError("Amount is too large")


def amount_in_words(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    dirhams = int(value)
    fils = int((value - Decimal(dirhams)) * 100)
    result = f"UAE Dirham {integer_words(dirhams)}"
    if fils:
        result += f" and {integer_words(fils)} Fils"
    return result + " Only"


def generate_pdf(data: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base = Decimal(str(data["amount"])).quantize(Decimal("0.01"))
    vat_rate = Decimal(str(data["vat_rate"]))
    vat = (base * vat_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = base + vat

    client_name = escape(str(data["client_name"]))
    address = escape(str(data["address"]))
    client_trn = escape(str(data.get("client_trn") or "Not provided"))
    description = escape(str(data["description"]))
    note = escape(str(data.get("note") or ""))

    c = canvas.Canvas(str(output_path), pagesize=A4)
    W, H = A4
    ink, grid = colors.HexColor("#222222"), colors.HexColor("#767676")
    left, right, bottom, top = 14*mm, W-14*mm, 14*mm, H-14*mm

    def line(x1, y1, x2, y2, width=.55):
        c.setStrokeColor(grid); c.setLineWidth(width); c.line(x1, y1, x2, y2)

    def text(x, y, value, size=7, bold=False, align="left"):
        c.setFillColor(ink); c.setFont("JnA-Bold" if bold else "JnA-Regular", size)
        if align == "right": c.drawRightString(x, y, str(value))
        elif align == "center": c.drawCentredString(x, y, str(value))
        else: c.drawString(x, y, str(value))

    def para(x, y, width, height, value, size=7, leading=None, align=0):
        style = ParagraphStyle("local", fontName="JnA-Regular", fontSize=size,
                               leading=leading or size*1.25, textColor=ink, alignment=align)
        p = Paragraph(value, style); p.wrapOn(c, width, height); p.drawOn(c, x, y+height-p.height)

    c.setStrokeColor(grid); c.setLineWidth(.8); c.rect(left, bottom, right-left, top-bottom)
    title = {"tax_invoice": "TAX INVOICE", "invoice": "INVOICE", "receipt": "RECEIPT",
             "acknowledgement": "ACKNOWLEDGEMENT RECEIPT"}[data["document_type"]]
    text(W/2, top+3.2*mm, title, 12, True, "center")

    header_bottom, split = top-36*mm, left+100*mm
    line(left, header_bottom, right, header_bottom); line(split, top, split, header_bottom)
    c.drawImage(str(LOGO), left+2*mm, header_bottom+3.5*mm, 34*mm, 29*mm,
                preserveAspectRatio=True, mask="auto", anchor="c")
    para(left+38*mm, header_bottom+3*mm, 60*mm, 29*mm,
         "<b>J AND A REAL ESTATE BROKERAGE LLC</b><br/>105, Al Zarooni Building, 1 Street 1 - Al Barsha 1 - Dubai"
         "<br/>Emirate: Dubai<br/><b>TRN:</b> 104705182400003<br/><b>E-mail:</b> info@jnahouse.com", 6.3, 7.2)

    mid = split+46*mm
    line(mid, top, mid, header_bottom)
    for yy in (top-12*mm, top-24*mm): line(split, yy, right, yy)
    label = "Invoice No." if data["document_type"] in ("tax_invoice", "invoice") else "Document No."
    para(split+1.5*mm, top-11*mm, 43*mm, 10*mm, f"{label}<br/><b>{data['document_number']}</b>", 7, 8)
    para(mid+1.5*mm, top-11*mm, right-mid-3*mm, 10*mm, f"Dated<br/><b>{data['date']}</b>", 7, 8)
    para(split+1.5*mm, top-23*mm, 43*mm, 10*mm, "Supplier's Ref.", 7, 8)
    para(mid+1.5*mm, top-23*mm, right-mid-3*mm, 10*mm, "Other Reference(s)", 7, 8)
    para(split+1.5*mm, header_bottom+1*mm, 43*mm, 10*mm, "Client Order No.", 7, 8)
    para(mid+1.5*mm, header_bottom+1*mm, right-mid-3*mm, 10*mm, "Dated", 7, 8)

    client_top, client_bottom = header_bottom, header_bottom-43*mm
    line(left, client_bottom, right, client_bottom); line(split, client_top, split, client_bottom)
    para(left+1.5*mm, client_bottom+2*mm, 96*mm, 38*mm,
         f"<b>Client Name</b><br/><b>{client_name}</b><br/><br/><b>Address:</b> {address}"
         f"<br/><b>TRN:</b> {client_trn}<br/><b>Place of Supply:</b> UAE, Dubai", 7.3, 9)

    table_top, table_head, table_bottom = client_bottom, client_bottom-11*mm, bottom+74*mm
    cols = [left, left+9*mm, left+105*mm, left+124*mm, left+142*mm, left+151*mm, left+165*mm, right]
    for x in cols: line(x, table_top, x, table_bottom)
    line(left, table_head, right, table_head); line(left, table_bottom, right, table_bottom)
    for label, a, b in (("Sl<br/>No.",0,1),("Particulars",1,2),("Quantity",2,3),
                        ("Rate",3,4),("per",4,5),("VAT %",5,6),("Amount",6,7)):
        para(cols[a]+.7*mm, table_head+.7*mm, cols[b]-cols[a]-1.4*mm, 9.5*mm, label, 6.2, 6.8, TA_CENTER)
    text(left+3*mm, table_head-7*mm, "1")
    para(cols[1]+2*mm, table_bottom+6*mm, cols[2]-cols[1]-4*mm, table_head-table_bottom-10*mm,
         f"<b>{data['transaction_type'].upper()}</b><br/><br/><b>Description</b><br/>{description}", 8, 10)
    if note:
        para(cols[1]+2*mm, table_bottom+11*mm, cols[2]-cols[1]-4*mm, 22*mm,
             f"<b>Note</b><br/>{note}", 8, 10)
    text((cols[5]+cols[6])/2, table_head-7*mm, f"{int(vat_rate)}%", 6.3, True, "center")
    text(right-2*mm, table_head-7*mm, f"{base:,.2f}", 6.3, True, "right")

    sum_top, sum_bottom, sum_split = table_bottom, table_bottom-27*mm, left+116*mm
    line(left, sum_bottom, right, sum_bottom); line(sum_split, sum_top, sum_split, sum_bottom)
    para(left+1.5*mm, sum_bottom+2*mm, sum_split-left-3*mm, 23*mm,
         f"Amount Chargeable (in words)<br/><b>{amount_in_words(total)}</b><br/><b>(AED {total:,.2f})</b>", 7, 8.5)
    total_label = "Invoice Total" if data["document_type"] in ("tax_invoice", "invoice") else "Receipt Total"
    rows = (("Taxable Value", base), ("Value Added Tax", vat), (total_label, total))
    rh = 8.4*mm
    for i, (label, value) in enumerate(rows):
        y = sum_top-(i+1)*rh
        if i: line(sum_split, y+rh, right, y+rh)
        text(sum_split+1.5*mm, y+2.4*mm, label, 8 if i == 2 else 7, i == 2)
        text(right-1.5*mm, y+2.4*mm, f"{value:,.2f}", 9 if i == 2 else 7, i == 2, "right")

    foot_top, foot_mid = sum_bottom, bottom+17*mm
    line(split, foot_top, split, bottom); line(split, foot_mid, right, foot_mid)
    para(split+2*mm, foot_mid+2*mm, right-split-4*mm, foot_top-foot_mid-4*mm,
         "Company's Bank Details<br/><b>A/c Holder's Name:</b> J AND A REAL ESTATE BROKERAGE LLC"
         "<br/><b>Bank Name:</b> Mashreq Bank<br/><b>A/c No.:</b> 19101525837"
         "<br/><b>IBAN:</b> AE26033000019101525837<br/><b>Branch &amp; SWIFT Code:</b> BOMLAEAD", 6.7, 8.2)
    text((split+right)/2, foot_mid-6*mm, "for J AND A REAL ESTATE BROKERAGE LLC", 6.8, True, "center")
    text(right-2*mm, bottom+2*mm, "Authorised Signatory", 6.5, False, "right")
    text(W/2, bottom-5*mm, "This is a Computer Generated Document", 6.8, False, "center")
    c.save()
    return output_path
