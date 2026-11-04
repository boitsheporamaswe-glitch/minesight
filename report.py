"""One-page-style shift report as a PDF (ReportLab)."""
import io
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.graphics.shapes import Drawing, Rect, String

CU, INK, MUTE, LINE = colors.HexColor("#B4551A"), colors.HexColor("#13232C"), colors.HexColor("#566A74"), colors.HexColor("#D5DBD9")
LVL = {"ok": (colors.HexColor("#13806A"), "Healthy"), "warning": (colors.HexColor("#A46A00"), "Plan maintenance"),
       "critical": (colors.HexColor("#C2362B"), "Urgent"), None: (MUTE, "")}
rand = lambda v: "R " + f"{v:,.0f}".replace(",", " ")

def build_pdf(org, site, hours, assets, alerts, saved, nread, tz_hours=2, orders=(), incidents=()):
    """assets: [(name, code, vib, temp, rul, level)] sorted by rul; alerts: [(ts, asset, level, msg)]"""
    now = datetime.now(timezone(timedelta(hours=tz_hours))); buf = io.BytesIO()
    ss = getSampleStyleSheet()
    P = ParagraphStyle("P", parent=ss["BodyText"], textColor=INK, fontSize=10, leading=14)
    H = ParagraphStyle("H", parent=P, fontName="Helvetica-Bold", fontSize=13, spaceBefore=16, spaceAfter=6, keepWithNext=1)
    T = ParagraphStyle("T", parent=P, fontName="Helvetica-Bold", fontSize=24, leading=28)
    S = ParagraphStyle("S", parent=P, textColor=MUTE, fontSize=9)
    C = ParagraphStyle("C", parent=P, fontSize=9, leading=12)

    def page(c, d):
        w, h = A4
        c.setFillColor(INK); c.rect(0, h - 26*mm, w, 26*mm, fill=1, stroke=0)
        c.setFillColor(CU); c.rect(0, h - 27.5*mm, w, 1.5*mm, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 18); c.drawString(18*mm, h - 16*mm, "MineSight")
        c.setFont("Helvetica", 10); c.drawRightString(w - 18*mm, h - 16*mm, f"{org} - {site}"[:70])
        c.setFillColor(MUTE); c.setFont("Helvetica", 8)
        c.drawString(18*mm, 10*mm, "Predictions are model estimates from vibration and temperature trends. Confirm by inspection before acting.")
        c.drawRightString(w - 18*mm, 10*mm, f"Page {d.page}")

    n = len(assets); ok = sum(1 for a in assets if a[5] == "ok")
    warn = sum(1 for a in assets if a[5] == "warning"); crit = sum(1 for a in assets if a[5] == "critical")
    raised = sum(1 for a in alerts if a[2] != "ok")
    st = [Paragraph("Shift report", T),
          Paragraph(f"Last {hours} hours · generated {now:%d %b %Y, %H:%M} (UTC+{tz_hours})", S), Spacer(1, 10)]
    if n:
        lead = (f"{ok} of {n} assets are healthy. " + (f"{crit} need urgent attention. " if crit else "") +
                (f"{warn} should be planned into the maintenance schedule. " if warn else ""))
        st.append(Paragraph(lead, P))
    else:
        st.append(Paragraph("No readings have been received for this site yet.", P))
    big = ParagraphStyle("B", parent=P, fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=CU)
    kp = Table([[Paragraph(f"{ok}/{n}", big), Paragraph(str(raised), big), Paragraph(rand(saved), big)],
                [Paragraph("assets healthy", S), Paragraph("alerts raised", S), Paragraph("downtime avoided", S)]],
               colWidths=[58*mm]*3)
    kp.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 2, CU), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    st += [Spacer(1, 12), kp]
    if n:
        st.append(Paragraph("Hours to failure", H))
        dh = 17 * n + 4; d = Drawing(174*mm, dh)
        for i, (name, code, vib, temp, rul, lv) in enumerate(assets):
            y = dh - 17 * (i + 1) + 2; col = LVL[lv][0]
            d.add(String(0, y + 3, name[:26], fontName="Helvetica", fontSize=9, fillColor=INK))
            d.add(Rect(48*mm, y, 100*mm, 9, fillColor=LINE, strokeColor=None))
            d.add(Rect(48*mm, y, max(1.5, 100*mm * min(1, rul / 400)), 9, fillColor=col, strokeColor=None))
            d.add(String(151*mm, y + 1, "400+ h" if rul >= 399 else f"{rul:.0f} h", fontName="Helvetica-Bold", fontSize=9, fillColor=col))
        st.append(d)
        st.append(Paragraph("Asset detail", H))
        rows = [["Asset", "Vibration", "Temperature", "Hours left", "Status"]]
        for name, code, vib, temp, rul, lv in assets:
            rows.append([name[:30], f"{vib:.1f} mm/s", f"{temp:.0f} °C", "400+" if rul >= 399 else f"{rul:.0f}", LVL[lv][1]])
        t = Table(rows, colWidths=[56*mm, 28*mm, 30*mm, 24*mm, 36*mm], repeatRows=1)
        sty = [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
               ("TEXTCOLOR", (0, 0), (-1, 0), MUTE), ("LINEBELOW", (0, 0), (-1, 0), 1, INK),
               ("LINEBELOW", (0, 1), (-1, -1), .4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
        for i, a in enumerate(assets, 1): sty.append(("TEXTCOLOR", (4, i), (4, i), LVL[a[5]][0]))
        t.setStyle(TableStyle(sty)); st.append(t)
    st.append(Paragraph("Events", H))
    if alerts:
        rows = [["Time", "Asset", "Event"]]
        for ts, asset, lv, msg in alerts:
            rows.append([datetime.fromtimestamp(ts, timezone(timedelta(hours=tz_hours))).strftime("%d %b %H:%M"),
                         asset, Paragraph(escape(msg), C)])
        t = Table(rows, colWidths=[28*mm, 22*mm, 124*mm], repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTE),
            ("FONT", (0, 1), (1, -1), "Helvetica", 9), ("LINEBELOW", (0, 0), (-1, 0), 1, INK), ("LINEBELOW", (0, 1), (-1, -1), .4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        st.append(t)
    else:
        st.append(Paragraph("No alerts in this period.", P))
    def tbl(head, rows, widths):
        t = Table([head] + rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTE),
            ("LINEBELOW", (0, 0), (-1, 0), 1, INK), ("LINEBELOW", (0, 1), (-1, -1), .4, LINE), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t
    if orders:
        st += [Paragraph("Open work orders", H), tbl(["Asset", "Job", "Priority", "Status", "Assigned to"],
            [[a, Paragraph(escape(t), C), p.title(), x.replace("_", " ").title(), Paragraph(escape(w or "-"), C)] for a, t, p, x, w in orders],
            [22*mm, 76*mm, 22*mm, 26*mm, 28*mm])]
    if incidents:
        st += [Paragraph("Safety incidents", H), tbl(["Date", "Type", "Severity", "Details"],
            [[datetime.fromtimestamp(ts, timezone(timedelta(hours=tz_hours))).strftime("%d %b"), k, sv.title(), Paragraph(escape(f"{loc}: {d}"), C)] for ts, k, sv, loc, d in incidents],
            [20*mm, 34*mm, 20*mm, 100*mm])]
    st += [Spacer(1, 10), Paragraph(f"{nread:,} sensor readings were analysed in this period.".replace(",", " "), S)]
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=36*mm, bottomMargin=18*mm,
                      title=f"MineSight shift report - {site}", author="MineSight").build(st, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()
