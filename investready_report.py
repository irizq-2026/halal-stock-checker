"""InvestReady premium PDF report generator (reportlab)."""

from __future__ import annotations

import io
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    _ARABIC_LIBS_OK = True
except Exception:
    arabic_reshaper = None  # type: ignore
    get_display = None  # type: ignore
    _ARABIC_LIBS_OK = False

# iRizq brand colors
NAVY = colors.HexColor("#0d1f3c")
NAVY_MID = colors.HexColor("#14294f")
TEAL = colors.HexColor("#1ec8b8")
TEAL_PALE = colors.HexColor("#e4f9f7")
GREEN = colors.HexColor("#3d7a45")
SILVER = colors.HexColor("#f1f2f4")
BAR_BG = colors.HexColor("#e2e5e9")
WHITE = colors.HexColor("#ffffff")
TEXT = colors.HexColor("#374151")
AMBER = colors.HexColor("#f59e0b")
RED = colors.HexColor("#ef4444")
MUTED = colors.HexColor("#6b7280")

_ARABIC_FONT = "Helvetica"
_HAS_ARABIC_FONT = False

PAGE_WIDTH, PAGE_HEIGHT = letter


def _register_fonts() -> str:
    global _ARABIC_FONT, _HAS_ARABIC_FONT
    # Prefer dedicated Arabic fonts only. Generic fonts often box the Allah ligature.
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/fonts-arabeyes/ae_AlMohanad.ttf",
        "/usr/share/fonts/truetype/kacst/KacstBook.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("InvestReadyArabic", str(path)))
                _ARABIC_FONT = "InvestReadyArabic"
                _HAS_ARABIC_FONT = True
                return _ARABIC_FONT
            except Exception:
                continue
    _HAS_ARABIC_FONT = False
    _ARABIC_FONT = "Helvetica"
    return _ARABIC_FONT


_register_fonts()

LOGO_PATH = Path(__file__).resolve().parent / "static" / "logo.png"
DISCLAIMER = (
    "Educational only. iRizq does not provide financial, legal, tax, or investment advice. "
    "Use this assessment as a learning tool and consult qualified professionals for personal guidance."
)

# Simpler Arabic without diacritics for more reliable font/ligature rendering.
BISMILLAH_AR = "بسم الله الرحمن الرحيم"
BISMILLAH_EN = "In the name of Allah, the Most Gracious, the Most Merciful"
BISMILLAH_EN_FALLBACK = "Bismillah ir-Rahman ir-Raheem"
FOUNDATION_STRENGTHS_MSG = (
    "Focus on building your financial foundation across all categories before identifying "
    "specific strengths. Your priority action plan below shows where to start."
)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "IRTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=NAVY,
            spaceAfter=8,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "IRH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "IRH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=6,
            borderPadding=3,
        ),
        "body": ParagraphStyle(
            "IRBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            textColor=TEXT,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "body_left": ParagraphStyle(
            "IRBodyLeft",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            textColor=TEXT,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "teal": ParagraphStyle(
            "IRTeal",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEAL,
            spaceAfter=6,
        ),
        "muted": ParagraphStyle(
            "IRMuted",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=10,
        ),
        "report_id": ParagraphStyle(
            "IRReportId",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=6,
        ),
        "center": ParagraphStyle(
            "IRCenter",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            textColor=TEXT,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "score_label": ParagraphStyle(
            "IRScoreLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=4,
        ),
        "score": ParagraphStyle(
            "IRScore",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=4,
            leading=26,
        ),
        "grade": ParagraphStyle(
            "IRGrade",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=6,
            leading=22,
        ),
        "profile_label": ParagraphStyle(
            "IRProfileLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=4,
        ),
        "profile": ParagraphStyle(
            "IRProfile",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=0,
            leading=20,
        ),
        "band_label": ParagraphStyle(
            "IRBandLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "band_value": ParagraphStyle(
            "IRBandValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=WHITE,
            alignment=TA_CENTER,
            leading=26,
        ),
        "band_profile": ParagraphStyle(
            "IRBandProfile",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=WHITE,
            alignment=TA_CENTER,
            leading=18,
        ),
        "toc_name": ParagraphStyle(
            "IRTocName",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            textColor=NAVY,
            leading=16,
        ),
        "toc_page": ParagraphStyle(
            "IRTocPage",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEAL,
            alignment=TA_RIGHT,
            leading=16,
        ),
        "white_center": ParagraphStyle(
            "IRWhiteCenter",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            textColor=WHITE,
            alignment=TA_CENTER,
            leading=15,
        ),
        "white_title": ParagraphStyle(
            "IRWhiteTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "bismillah_ar": ParagraphStyle(
            "IRBismillahAr",
            parent=base["BodyText"],
            fontName=_ARABIC_FONT,
            fontSize=14,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=2,
            leading=20,
        ),
        "bismillah_en": ParagraphStyle(
            "IRBismillahEn",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
        "bismillah_translit": ParagraphStyle(
            "IRBismillahTranslit",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=11,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=2,
            leading=14,
        ),
        "foundation_msg": ParagraphStyle(
            "IRFoundationMsg",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            textColor=NAVY,
            alignment=TA_LEFT,
            leading=14,
            spaceAfter=6,
        ),
        "toc_howto_h": ParagraphStyle(
            "IRTocHowToH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=10,
        ),
        "toc_howto_body": ParagraphStyle(
            "IRTocHowToBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            textColor=TEXT,
            leading=13,
            spaceAfter=12,
            alignment=TA_LEFT,
        ),
        "teal_italic": ParagraphStyle(
            "IRTealItalic",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=10,
            spaceAfter=8,
            leading=14,
        ),
        "teal_italic_small": ParagraphStyle(
            "IRTealItalicSmall",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=8,
            spaceAfter=8,
            leading=13,
        ),
        "dua": ParagraphStyle(
            "IRDua",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=11,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=10,
            spaceAfter=8,
            leading=16,
        ),
        "scenario_sub": ParagraphStyle(
            "IRScenarioSub",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            spaceAfter=6,
        ),
        "checklist_text": ParagraphStyle(
            "IRChecklistText",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            textColor=NAVY,
            leading=13,
        ),
        "cover_feature": ParagraphStyle(
            "IRCoverFeature",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=WHITE,
            alignment=TA_CENTER,
            leading=12,
        ),
        "cover_subfeature": ParagraphStyle(
            "IRCoverSubFeature",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            textColor=TEAL,
            alignment=TA_CENTER,
            leading=11,
        ),
        "cover_disclaimer": ParagraphStyle(
            "IRCoverDisclaimer",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            textColor=colors.Color(1, 1, 1, alpha=0.45),
            alignment=TA_CENTER,
            leading=10,
        ),
        "cover_copy": ParagraphStyle(
            "IRCoverCopy",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            textColor=colors.Color(1, 1, 1, alpha=0.35),
            alignment=TA_CENTER,
            leading=10,
        ),
        "shariah_label": ParagraphStyle(
            "IRShariahLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=TEAL,
            spaceAfter=3,
        ),
        "shariah_body": ParagraphStyle(
            "IRShariahBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            textColor=NAVY,
            leading=12,
        ),
    }


def _score_color(score: float) -> colors.Color:
    if score >= 80:
        return TEAL
    if score >= 60:
        return GREEN
    return RED


def _score_status(score: float) -> str:
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Developing"
    return "Needs Attention"


def _color_hex(color: colors.Color) -> str:
    return f"{int(color.red * 255):02x}{int(color.green * 255):02x}{int(color.blue * 255):02x}"


def _logo_flowable(width: float = 1.4 * inch) -> Any:
    if LOGO_PATH.is_file():
        img = Image(str(LOGO_PATH))
        aspect = float(img.imageHeight) / float(img.imageWidth or 1)
        img.drawWidth = width
        img.drawHeight = width * aspect
        img.hAlign = "CENTER"
        return img
    return Paragraph("<b>iRizq</b>", _styles()["title"])


def _header_band(title: str) -> list[Any]:
    styles = _styles()
    data = [[Paragraph(f"<font color='white'><b>{title}</b></font>", styles["center"])]]
    table = Table(data, colWidths=[7.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return [table, HRFlowable(width="100%", thickness=3, color=TEAL, spaceAfter=12)]


def _callout(title: str, body: str, border_color: colors.Color = AMBER) -> KeepTogether:
    styles = _styles()
    inner = [
        Paragraph(f"<b>{title}</b>", styles["h2"]),
        Paragraph(body, styles["body_left"]),
    ]
    table = Table([[inner]], colWidths=[6.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("BOX", (0, 0), (-1, -1), 0, WHITE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBEFORE", (0, 0), (0, -1), 4, border_color),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 8)])


def _shariah_callout() -> KeepTogether:
    styles = _styles()
    inner = [
        Paragraph("SHARIAH COMPLIANCE NOTE", styles["shariah_label"]),
        Paragraph(
            "Investment suggestions in this report reference Shariah-compliant instruments "
            "screened under AAOIFI (Accounting and Auditing Organization for Islamic "
            "Financial Institutions) standards. Use the iRizq Halal Stock Checker at "
            "stocks.irizq.com to verify any specific investment before purchasing.",
            styles["shariah_body"],
        ),
    ]
    table = Table([[inner]], colWidths=[6.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL_PALE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 10)])


def _bismillah_flowables(styles: dict[str, ParagraphStyle]) -> list[Any]:
    """Render Arabic Bismillah with shaping, or English-only fallback.

    Never raises - any Arabic shaping/rendering failure falls back to transliteration.
    Allah ligatures are disabled because some PDF fonts render them as empty boxes.
    """
    try:
        if _HAS_ARABIC_FONT and _ARABIC_LIBS_OK and arabic_reshaper and get_display:
            # Prefer Noto Arabic fonts only; DejaVu often boxes the Allah ligature.
            if _ARABIC_FONT != "InvestReadyArabic":
                raise RuntimeError("No reliable Arabic PDF font registered")
            reshaper = arabic_reshaper.ArabicReshaper(
                configuration={
                    "delete_harakat": True,
                    "support_ligatures": False,
                }
            )
            reshaped = reshaper.reshape(BISMILLAH_AR)
            bidi_text = get_display(reshaped)
            if not bidi_text or not str(bidi_text).strip():
                raise RuntimeError("Empty Arabic reshape result")
            return [
                Paragraph(bidi_text, styles["bismillah_ar"]),
                Paragraph(BISMILLAH_EN, styles["bismillah_en"]),
            ]
    except Exception:
        pass
    return [
        Paragraph(BISMILLAH_EN_FALLBACK, styles["bismillah_translit"]),
        Paragraph(BISMILLAH_EN, styles["bismillah_en"]),
    ]


def _make_report_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase, k=4))
    return f"IR-{datetime.utcnow().strftime('%Y%m%d')}-{suffix}"


def _score_info_band(overall: int, grade: str, profile: str) -> list[Any]:
    styles = _styles()
    left = [
        Paragraph("OVERALL SCORE", styles["band_label"]),
        Paragraph(f"{overall} / 100", styles["band_value"]),
    ]
    middle = [
        Paragraph("GRADE", styles["band_label"]),
        Paragraph(grade, styles["band_value"]),
    ]
    right = [
        Paragraph("INVESTOR PROFILE", styles["band_label"]),
        Paragraph(profile, styles["band_profile"]),
    ]
    table = Table([[left, middle, right]], colWidths=[2.33 * inch, 2.34 * inch, 2.33 * inch], rowHeights=[80])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return [
        table,
        HRFlowable(width="100%", thickness=2, color=TEAL, spaceBefore=0, spaceAfter=0),
        Spacer(1, 16),
    ]


class ScoreBarRow(Flowable):
    """One visual score row: category | bar | number | status."""

    def __init__(self, category: str, score: float, *, overall: bool = False, width: float = 7.0 * inch):
        super().__init__()
        self.category = category
        self.score = max(0.0, min(100.0, float(score)))
        self.overall = overall
        self.width = width
        self.height = 18

    def draw(self) -> None:
        c = self.canv
        name_w = 140
        bar_w = 200
        bar_h = 10
        bar_x = name_w + 8
        bar_y = 4
        fill_color = NAVY if self.overall else _score_color(self.score)
        status = "Overall" if self.overall else _score_status(self.score)

        c.setFillColor(NAVY)
        c.setFont("Helvetica", 10)
        c.drawString(0, 5, self.category[:28])

        c.setFillColor(BAR_BG)
        c.rect(bar_x, bar_y, bar_w, bar_h, fill=1, stroke=0)

        fill_w = (self.score / 100.0) * bar_w
        if fill_w > 0:
            c.setFillColor(fill_color)
            c.rect(bar_x, bar_y, fill_w, bar_h, fill=1, stroke=0)

        score_x = bar_x + bar_w + 10
        c.setFillColor(fill_color)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(score_x, 5, f"{int(round(self.score))}")

        status_x = score_x + 36
        c.setFont("Helvetica", 9)
        c.setFillColor(fill_color)
        c.drawString(status_x, 5, status)


class ChecklistItem(Flowable):
    """Teal bordered checkbox with checkmark + navy item text."""

    def __init__(self, text: str, width: float = 7.0 * inch):
        super().__init__()
        self.text = text
        self.width = width
        self.height = 14

    def wrap(self, availWidth: float, availHeight: float):  # noqa: N803
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        box = 10
        y = 2
        c.setStrokeColor(TEAL)
        c.setFillColor(TEAL_PALE)
        c.setLineWidth(1)
        c.rect(0, y, box, box, fill=1, stroke=1)
        c.setStrokeColor(TEAL)
        c.setLineWidth(1.3)
        c.line(2, y + 4.5, 4.2, y + 2.2)
        c.line(4.2, y + 2.2, 8.2, y + 8)
        c.setFillColor(NAVY)
        c.setFont("Helvetica", 10)
        c.drawString(16, y + 1, self.text)


class FeatureIconBox(Flowable):
    """Back-cover feature box with a simple canvas icon."""

    def __init__(self, kind: str, title: str, subtitle: str, width: float = 1.95 * inch, height: float = 92):
        super().__init__()
        self.kind = kind
        self.title = title
        self.subtitle = subtitle
        self.width = width
        self.height = height

    def draw(self) -> None:
        c = self.canv
        # Background first, then border/content on top (16pt inner padding).
        pad = 16
        c.setFillColor(colors.HexColor("#102848"))
        c.setStrokeColor(WHITE)
        c.setLineWidth(0.5)
        c.roundRect(0, 0, self.width, self.height, 6, fill=1, stroke=1)

        cx = self.width / 2
        icon_y = self.height - pad - 10
        c.setStrokeColor(TEAL)
        c.setFillColor(TEAL)
        c.setLineWidth(1.2)
        if self.kind == "check":
            c.circle(cx, icon_y, 8, fill=0, stroke=1)
            c.line(cx - 3.5, icon_y - 0.5, cx - 1, icon_y - 3)
            c.line(cx - 1, icon_y - 3, cx + 4, icon_y + 3.5)
        elif self.kind == "chart":
            c.line(cx - 8, icon_y - 6, cx - 8, icon_y + 6)
            c.line(cx - 8, icon_y - 6, cx + 8, icon_y - 6)
            c.rect(cx - 5, icon_y - 6, 3, 6, fill=1, stroke=0)
            c.rect(cx - 1, icon_y - 6, 3, 10, fill=1, stroke=0)
            c.rect(cx + 3, icon_y - 6, 3, 4, fill=1, stroke=0)
        else:
            c.rect(cx - 6, icon_y - 7, 12, 14, fill=0, stroke=1)
            c.line(cx - 3, icon_y + 2, cx + 3, icon_y + 2)
            c.line(cx - 3, icon_y - 1, cx + 3, icon_y - 1)
            c.line(cx - 3, icon_y - 4, cx + 1, icon_y - 4)

        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, pad + 18, self.title)
        c.setFillColor(TEAL)
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, pad, self.subtitle)


class BackCoverFeaturesBand(Flowable):
    """Full-width mid-band: navy background drawn first, then three feature boxes."""

    def __init__(self, width: float = 7.0 * inch, height: float = 140):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self) -> None:
        c = self.canv
        # 1) Background rectangle first so boxes never float on white.
        c.setFillColor(NAVY_MID)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)

        box_w = 1.95 * inch
        box_h = 92
        gap = (self.width - 3 * box_w) / 4.0
        y = 20  # >= 20pt padding below / above boxes (band height accommodates)
        boxes = [
            ("check", "Shariah Screened", "AAOIFI Standards"),
            ("chart", "10 Categories", "Assessed"),
            ("doc", "Personalized", "PDF Report"),
        ]
        for idx, (kind, title, subtitle) in enumerate(boxes):
            x = gap + idx * (box_w + gap)
            FeatureIconBox(kind, title, subtitle, width=box_w, height=box_h).drawOn(c, x, y)


class InvestReadyCanvas(pdfcanvas.Canvas):
    """Canvas that draws interior headers/footers and correct Page X of Y."""

    def __init__(self, *args: Any, prepared_for: str = "Investor", **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self.prepared_for = prepared_for

    def showPage(self) -> None:  # noqa: N802
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_chrome(page_count)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_page_chrome(self, page_count: int) -> None:
        page = self._pageNumber
        # Skip PAGE 1 and the last page (back cover).
        if page <= 1 or page >= page_count:
            return

        left = 0.65 * inch
        right = PAGE_WIDTH - 0.65 * inch

        # Header
        header_y = PAGE_HEIGHT - 0.42 * inch
        if LOGO_PATH.is_file():
            try:
                self.drawImage(
                    str(LOGO_PATH),
                    left,
                    header_y - 4,
                    width=20,
                    height=20,
                    mask="auto",
                    preserveAspectRatio=True,
                )
            except Exception:
                self.setFillColor(NAVY)
                self.setFont("Helvetica-Bold", 8)
                self.drawString(left, header_y, "iRizq")
        else:
            self.setFillColor(NAVY)
            self.setFont("Helvetica-Bold", 8)
            self.drawString(left, header_y, "iRizq")

        self.setFillColor(MUTED)
        self.setFont("Helvetica-Oblique", 8)
        self.drawRightString(right, header_y + 4, f"Prepared for {self.prepared_for}")
        self.setStrokeColor(NAVY)
        self.setLineWidth(0.5)
        self.line(left, header_y - 8, right, header_y - 8)

        # Footer
        footer_y = 0.40 * inch
        self.setStrokeColor(TEAL)
        self.setLineWidth(0.5)
        self.line(left, footer_y + 12, right, footer_y + 12)

        self.setFillColor(MUTED)
        self.setFont("Helvetica", 7)
        self.drawString(left, footer_y, "InvestReady Financial Readiness Report")
        self.drawCentredString(PAGE_WIDTH / 2, footer_y, f"Page {page} of {page_count}")
        self.setFillColor(TEAL)
        self.drawRightString(right, footer_y, "iRizq.com")


def _strengths_and_risks(
    category_scores: dict[str, Any],
) -> tuple[list[str], list[str], str, str | None]:
    """Return strengths, risks, strength_label, and optional foundation message."""
    ranked = sorted(
        ((str(k), float(v)) for k, v in category_scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    risks = [
        f"Needs attention: {name} ({int(score)}/100)"
        for name, score in sorted(
            ((str(k), float(v)) for k, v in category_scores.items() if float(v) < 60),
            key=lambda item: item[1],
        )[:3]
    ]

    scores = [float(v) for v in category_scores.values()]
    if not scores:
        return [], risks, "", FOUNDATION_STRENGTHS_MSG

    highest = max(scores)
    all_tied = len(set(round(s, 4) for s in scores)) == 1
    if highest < 50 or all_tied:
        return [], risks, "", FOUNDATION_STRENGTHS_MSG

    true_strengths = [(name, score) for name, score in ranked if score >= 70]
    relative_strengths = [(name, score) for name, score in ranked if 60 <= score < 70]

    if true_strengths:
        strengths = [f"Strength: {name} ({int(score)}/100)" for name, score in true_strengths[:3]]
        return strengths, risks, "Strength", None

    if relative_strengths:
        strengths = [
            f"Relatively Stronger Area: {name} ({int(score)}/100)"
            for name, score in relative_strengths[:3]
        ]
        return strengths, risks, "Relatively Stronger Area", None

    return [], risks, "", FOUNDATION_STRENGTHS_MSG


CATEGORY_GAP_COPY: dict[str, tuple[str, str]] = {
    "Insurance and Risk": (
        "Insurance and Risk Gap",
        "Your insurance and risk score of {score}/100 suggests your coverage may have gaps. "
        "Without adequate protection, a single unexpected event such as illness, disability, or "
        "property loss can undo years of careful saving and investing. Review each coverage type "
        "you currently hold and identify what is missing.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. List every insurance policy you hold and its coverage limit<br/>"
        "2. Compare against your current income, dependents, and assets<br/>"
        "3. Get quotes for any missing coverage within the next 30 days",
    ),
    "Diversification": (
        "Diversification Gap",
        "A diversification score of {score}/100 suggests your halal portfolio may be concentrated "
        "in too few areas. Concentration amplifies both gains and losses - and for most investors "
        "the losses feel far worse than the gains feel good. Spreading across sectors and "
        "geographies reduces this risk.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. List your current holdings and calculate what percentage each represents<br/>"
        "2. Identify any single position above 20% and create a plan to reduce it gradually<br/>"
        "3. Research one Shariah-compliant ETF or fund that adds diversification to your current mix",
    ),
    "Goal Clarity": (
        "Goal Clarity Gap",
        "A goal clarity score of {score}/100 suggests your financial targets may be vague or "
        "unwritten. Research consistently shows that written goals with specific dates and dollar "
        "amounts are dramatically more likely to be achieved than mental intentions alone.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Write down your top 3 financial goals with a target date and target amount for each<br/>"
        "2. Break each goal into monthly milestones so progress is visible<br/>"
        "3. Review your written goals every Monday for the next 90 days",
    ),
    "Tax Awareness": (
        "Tax Awareness Gap",
        "Your tax awareness score of {score}/100 suggests you may not be fully using "
        "tax-advantaged accounts available to you. Every dollar of tax saved is a guaranteed "
        "return that does not depend on market performance.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Confirm which tax-advantaged accounts you are eligible for (401k, IRA, HSA)<br/>"
        "2. If not maxing contributions, increase by at least 1% this month<br/>"
        "3. Schedule a 30-minute session to review your tax situation before year end",
    ),
    "Cash Flow": (
        "Cash Flow Gap",
        "A cash flow score of {score}/100 suggests income and expenses may not be fully under "
        "control. Without knowing your monthly surplus, it is very difficult to consistently "
        "invest, save, or plan for the future.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Track every expense for the next 30 days using any app or notebook<br/>"
        "2. Identify the single largest non-essential expense and reduce it this month<br/>"
        "3. Set up an automatic savings transfer on the day your income arrives",
    ),
    "Emergency Preparedness": (
        "Emergency Preparedness Gap",
        "An emergency preparedness score of {score}/100 means a financial shock could force you "
        "to sell halal investments at the wrong time or take on expensive debt. Building a buffer "
        "is the single highest-priority foundation for every financial plan.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Open a separate savings account dedicated only to emergencies<br/>"
        "2. Set a minimum target of one month of expenses as your first milestone<br/>"
        "3. Automate a fixed transfer to this account every payday",
    ),
    "Debt Management": (
        "Debt Management Gap",
        "Your debt management score of {score}/100 suggests high-interest obligations may be "
        "quietly eroding your progress. In most cases, paying down debt above 10% interest offers "
        "a better guaranteed return than investing in the market.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. List all debts with their interest rates<br/>"
        "2. Direct all extra monthly cash toward the highest rate debt first<br/>"
        "3. Stop adding new high-interest debt immediately while paying down existing",
    ),
    "Retirement Planning": (
        "Retirement Planning Gap",
        "A retirement planning score of {score}/100 suggests this long-term priority may not be "
        "receiving enough attention. The earlier contributions begin, the more compounding works "
        "in your favor - even small consistent amounts matter enormously over decades.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. If eligible, open or contribute to a retirement account this month<br/>"
        "2. Calculate your retirement number (monthly expenses multiplied by 300)<br/>"
        "3. Increase contributions by 1% with your next pay review",
    ),
    "Investing Readiness": (
        "Investing Readiness Gap",
        "Your investing readiness score of {score}/100 suggests foundational investing habits "
        "still need reinforcement. Consistent monthly contributions and clear rules protect "
        "long-term progress more than perfect timing.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Set a fixed monthly amount you can invest without stress<br/>"
        "2. Screen candidates with the iRizq Halal Stock Checker at stocks.irizq.com<br/>"
        "3. Write a simple buy-and-hold rule set before your next purchase",
    ),
    "Behavioral Discipline": (
        "Behavioral Discipline Gap",
        "A behavioral discipline score of {score}/100 flags emotional decision-making as a risk. "
        "Buying on excitement and selling on fear can erase years of compounding in a halal "
        "portfolio.<br/><br/>"
        "<b>Steps:</b><br/>"
        "1. Write a one-page investing plan and keep it visible<br/>"
        "2. Wait 48 hours before any unplanned trade<br/>"
        "3. Mute speculative tip channels for the next 30 days",
    ),
}


FOCUS_ACTIONS: dict[str, str] = {
    "Cash Flow": "Track every expense for 30 days and automate a payday savings transfer.",
    "Emergency Preparedness": "Open a dedicated emergency account and automate a fixed transfer every payday.",
    "Debt Management": "List all debts by rate and send every extra dollar to the highest-rate balance first.",
    "Investing Readiness": "Set a fixed monthly halal investment amount and keep it automated.",
    "Retirement Planning": "Increase retirement contributions by 1% and write down your retirement number.",
    "Insurance and Risk": "List every policy you hold and get quotes for any missing coverage this month.",
    "Goal Clarity": "Write your top 3 goals with dates and dollar targets, then review them each Monday.",
    "Tax Awareness": "Confirm eligible tax-advantaged accounts and raise contributions by at least 1%.",
    "Diversification": "Cap any single holding near 20% and add one diversifying Shariah-compliant fund.",
    "Behavioral Discipline": "Write your investment rules and wait 48 hours before any unplanned trade.",
}


def _mistakes(answers: dict[str, Any], category_scores: dict[str, Any]) -> list[tuple[str, str]]:
    mistakes: list[tuple[str, str]] = []
    a = {str(k): v for k, v in (answers or {}).items()}

    if int(a.get("q4", 4) or 0) <= 1:
        score = int(float(category_scores.get("Emergency Preparedness", 50)))
        title, body = CATEGORY_GAP_COPY["Emergency Preparedness"]
        mistakes.append((title, body.format(score=score)))

    if int(a.get("q7", 4) or 0) <= 2 and int(a.get("q10", 0) or 0) >= 1:
        score = int(float(category_scores.get("Debt Management", 50)))
        title, body = CATEGORY_GAP_COPY["Debt Management"]
        mistakes.append((title, body.format(score=score)))

    if int(a.get("q13", 4) or 0) <= 1:
        score = int(float(category_scores.get("Diversification", 50)))
        title, body = CATEGORY_GAP_COPY["Diversification"]
        mistakes.append((title, body.format(score=score)))

    if int(a.get("q18", 4) or 0) <= 1:
        score = int(float(category_scores.get("Insurance and Risk", 50)))
        title, body = CATEGORY_GAP_COPY["Insurance and Risk"]
        mistakes.append((title, body.format(score=score)))

    if int(a.get("q20", 4) or 0) <= 1:
        score = int(float(category_scores.get("Goal Clarity", 50)))
        title, body = CATEGORY_GAP_COPY["Goal Clarity"]
        mistakes.append((title, body.format(score=score)))

    seen = {title for title, _ in mistakes}
    ranked = sorted(category_scores.items(), key=lambda item: float(item[1]))
    for name, score in ranked:
        if len(mistakes) >= 5:
            break
        pack = CATEGORY_GAP_COPY.get(str(name))
        if not pack:
            continue
        title, body = pack
        if title in seen:
            continue
        if float(score) >= 70 and mistakes:
            continue
        mistakes.append((title, body.format(score=int(float(score)))))
        seen.add(title)

    if not mistakes:
        for name, score in ranked[:3]:
            pack = CATEGORY_GAP_COPY.get(str(name))
            if pack:
                title, body = pack
                mistakes.append((title, body.format(score=int(float(score)))))
            else:
                mistakes.append(
                    (
                        f"Priority Gap: {name}",
                        f"Your {name} score is {int(float(score))}/100. Focus on one concrete "
                        "habit this week, automate one improvement this month, and reassess in 30 days.",
                    )
                )
    return mistakes[:5]


def _personalized_insights(category_scores: dict[str, Any], overall: int, profile: str) -> list[str]:
    scores = {str(k): float(v) for k, v in category_scores.items()}

    def band(score: float) -> str:
        if score >= 80:
            return "high"
        if score >= 60:
            return "mid"
        return "low"

    templates: dict[str, dict[str, str]] = {
        "Cash Flow": {
            "high": (
                "Your cash flow management is a clear strength. With a score of {score}/100, "
                "you demonstrate the kind of income discipline that forms the base of long-term wealth building."
            ),
            "mid": (
                "Your cash flow score of {score}/100 suggests room to tighten your budgeting habits. "
                "Even small improvements in tracking and automating savings can compound meaningfully over time."
            ),
            "low": (
                "Cash flow is the foundation everything else rests on. Your score of {score}/100 "
                "suggests this deserves immediate attention before focusing on investing or other goals."
            ),
        },
        "Emergency Preparedness": {
            "high": (
                "With an emergency preparedness score of {score}/100, you have built a genuine financial buffer. "
                "This gives you the freedom to take calculated investment risks without being forced to sell "
                "at the wrong time."
            ),
            "mid": (
                "Your emergency fund score of {score}/100 suggests your buffer may not fully cover an unexpected "
                "setback. Aim for 3-6 months of expenses in a separate account."
            ),
            "low": (
                "An emergency fund score of {score}/100 signals a significant vulnerability. Before investing, "
                "prioritize building at least one month of expenses as a starting buffer."
            ),
        },
        "Debt Management": {
            "high": (
                "Your debt management score of {score}/100 reflects strong discipline. Keeping high-interest debt "
                "low means more of your income can flow toward halal investments rather than interest payments."
            ),
            "mid": (
                "Your debt score of {score}/100 suggests some high-interest obligations may be quietly eroding "
                "your investing gains. A clear paydown strategy could free up significant monthly cash flow."
            ),
            "low": (
                "With a debt score of {score}/100, addressing high-interest debt is likely your highest "
                "guaranteed return right now. Every dollar paid toward expensive debt is a risk-free halal gain."
            ),
        },
        "Investing Readiness": {
            "high": (
                "Your investing readiness score of {score}/100 reflects consistent halal investment habits. "
                "The focus now is on maintaining discipline through market volatility and avoiding overconfidence."
            ),
            "mid": (
                "An investing readiness score of {score}/100 shows you have started the journey. Building more "
                "consistent monthly investing habits and broadening your halal diversification are the next "
                "logical steps."
            ),
            "low": (
                "Your investing readiness score of {score}/100 suggests foundational work is needed before "
                "scaling investments. Focus first on emergency savings and debt reduction."
            ),
        },
        "Behavioral Discipline": {
            "high": (
                "A behavioral discipline score of {score}/100 is one of the most valuable traits an investor "
                "can have. The ability to stay calm during market drops and ignore hot tips protects years of "
                "compounding."
            ),
            "mid": (
                "Your behavioral score of {score}/100 suggests occasional emotional decisions may be affecting "
                "your returns. A written investment plan you commit to in advance is one of the best defenses."
            ),
            "low": (
                "A behavioral discipline score of {score}/100 flags this as an area to address urgently. "
                "Emotional investing - buying high on excitement and selling low on fear - destroys more wealth "
                "than poor stock selection."
            ),
        },
    }

    article = "an" if profile[:1].lower() in "aeiou" else "a"
    insights: list[str] = [
        f"Your overall readiness score of {overall}/100 places you in {article} {profile} posture toward "
        f"growth and risk. The insights below are tied directly to your category results."
    ]

    priority_order = [
        "Cash Flow",
        "Emergency Preparedness",
        "Debt Management",
        "Investing Readiness",
        "Behavioral Discipline",
    ]
    # Prefer weaker categories first for relevance, but always cover the core five.
    ordered = sorted(priority_order, key=lambda cat: scores.get(cat, 50.0))
    for cat in ordered:
        score = scores.get(cat)
        if score is None:
            continue
        text = templates[cat][band(score)].format(score=int(round(score)))
        insights.append(text)

    extras = {
        "Retirement Planning": (
            "Your retirement planning score of {score}/100 shows how actively this long horizon is being funded. "
            "Small consistent increases in contributions can matter more than short-term market timing."
        ),
        "Goal Clarity": (
            "Your goal clarity score of {score}/100 reflects how specific and written your targets are. "
            "Clear dates and dollar amounts make follow-through far more likely."
        ),
        "Tax Awareness": (
            "Your tax awareness score of {score}/100 reflects how fully you are using available tax-advantaged "
            "accounts. Tax savings are one of the few near-certain improvements available to many investors."
        ),
        "Diversification": (
            "Your diversification score of {score}/100 shows how broadly your halal holdings are spread. "
            "Reducing concentration risk protects progress when a single sector or stock is under pressure."
        ),
        "Insurance and Risk": (
            "Your insurance and risk score of {score}/100 reflects the protection layer around your plan. "
            "Coverage gaps can undo years of careful saving after one unexpected event."
        ),
    }
    for cat, score in sorted(scores.items(), key=lambda item: item[1]):
        if len(insights) >= 7:
            break
        if cat in templates:
            continue
        if cat in extras:
            insights.append(extras[cat].format(score=int(round(score))))

    while len(insights) < 5:
        insights.append(
            "Use the lowest-scoring categories in this report as your next 30-day focus. "
            "Steady habits beat perfect timing in every profile."
        )
    return insights[:7]


def _top_focus_areas(category_scores: dict[str, Any]) -> list[str]:
    ranked = sorted(
        ((str(k), float(v)) for k, v in category_scores.items()),
        key=lambda item: item[1],
    )
    focus = ranked[:3]
    while len(focus) < 3:
        focus.append((f"Priority Area {len(focus) + 1}", 0.0))
    lines: list[str] = []
    for idx, (cat, score) in enumerate(focus, start=1):
        action = FOCUS_ACTIONS.get(cat, f"Choose one concrete habit to strengthen {cat} this week.")
        lines.append(f"{idx}. {cat} ({int(round(score))}/100) - {action}")
    return lines


def _profile_allocation(profile: str) -> str:
    mapping = {
        "Conservative": "Cash/short-term 30-50%, Sukuk and Shariah-compliant income funds 30-40%, Halal equities 10-30%",
        "Moderately Conservative": "Cash 20-30%, Sukuk and income funds 30-40%, Halal equities 30-40%",
        "Moderate": "Cash 10-20%, Sukuk 20-30%, Halal equities 50-70%",
        "Moderately Aggressive": "Cash 5-15%, Sukuk 10-20%, Halal equities 65-80%",
        "Aggressive": "Cash 0-10%, Sukuk 0-15%, Halal equities 80-100%",
    }
    return mapping.get(profile, mapping["Moderate"])


PROFILE_DESCRIPTIONS = {
    "Conservative": (
        "You prefer capital preservation over growth. Focus on building your financial foundation "
        "with stable, low-risk halal investments such as Shariah-compliant money market funds and "
        "sukuk before taking on more risk."
    ),
    "Moderately Conservative": (
        "You seek some growth but prioritize stability. A balanced halal portfolio with a mix of "
        "Shariah-compliant income funds and equities suits your approach."
    ),
    "Moderate": (
        "You balance growth and stability. You can handle some volatility in pursuit of long-term "
        "gains through a diversified halal equity and sukuk portfolio."
    ),
    "Moderately Aggressive": (
        "You prioritize growth and can tolerate market swings. A halal equity-focused portfolio with "
        "broad diversification aligns with your profile."
    ),
    "Aggressive": (
        "You seek maximum growth and are comfortable with significant volatility. A halal equity "
        "portfolio with global diversification and long investment horizon suits you well."
    ),
}


CATEGORY_EDU: dict[str, dict[str, str]] = {
    "Cash Flow": {
        "why": (
            "Cash flow is the engine of every financial plan. Without knowing your monthly surplus, "
            "you cannot consistently save, invest, or plan for the future. Most financial setbacks "
            "trace back to cash flow problems that were ignored too long."
        ),
        "misconception": (
            "Many people believe they need to earn more before budgeting makes sense. In reality, "
            "budgeting is how you create the margin to build wealth at any income level."
        ),
        "improvement": (
            "You know your exact monthly income and expenses. You have a surplus every month that "
            "automatically moves to savings or investments before you can spend it."
        ),
    },
    "Emergency Preparedness": {
        "why": (
            "An emergency fund is not about pessimism - it is about freedom. Without a buffer, any "
            "unexpected expense forces a bad financial decision: selling investments early, taking "
            "on debt, or missing payments."
        ),
        "misconception": (
            "Many people keep emergency savings mixed with their regular account. This makes it "
            "invisible and too easy to spend. A separate account makes the buffer real and intentional."
        ),
        "improvement": (
            "You have 3-6 months of expenses in a separate account you never touch except for genuine "
            "emergencies. It is automated, growing, and gives you confidence under stress."
        ),
    },
    "Debt Management": {
        "why": (
            "High-interest debt is a guaranteed negative return on your money. Every month you carry "
            "it, the interest quietly erodes the gains from everything else you are doing right. It is "
            "the financial equivalent of a slow leak."
        ),
        "misconception": (
            "Many people invest while carrying high-interest debt, believing market returns will "
            "outpace interest costs. For debt above 10%, this is almost never true after risk is "
            "accounted for."
        ),
        "improvement": (
            "You have no high-interest debt. Any remaining debt is low-rate and on a clear paydown "
            "schedule. Your cash flow is not being bled by interest payments every month."
        ),
    },
    "Investing Readiness": {
        "why": (
            "Consistent halal investing over long periods is how ordinary Muslims build extraordinary "
            "wealth. The investment itself matters less than the consistency, the halal screening, and "
            "the patience to stay invested through volatility."
        ),
        "misconception": (
            "Many new investors believe they need to find the right stock or the perfect time to start. "
            "In reality, starting with any Shariah-compliant fund consistently beats waiting for perfect "
            "information indefinitely."
        ),
        "improvement": (
            "You invest a fixed halal amount every month automatically. You use Shariah-compliant ETFs "
            "or screened stocks. You do not react to short-term market swings."
        ),
    },
    "Retirement Planning": {
        "why": (
            "Retirement planning is time-sensitive in a way other goals are not. Every year of delay "
            "in starting contributions costs more than the year before due to the compounding you miss. "
            "Starting at 25 versus 35 can double the outcome with the same monthly amount."
        ),
        "misconception": (
            "Many people assume retirement planning is for older people or higher earners. In fact, "
            "small consistent contributions started early matter far more than large contributions "
            "started late."
        ),
        "improvement": (
            "You contribute regularly to a retirement account. You know your retirement number. Your "
            "contribution increases automatically with your income."
        ),
    },
    "Insurance and Risk": {
        "why": (
            "Insurance converts unpredictable catastrophic risk into a known manageable cost. Without "
            "it, a single illness, accident, or disaster can set back years of careful financial "
            "progress in a matter of weeks."
        ),
        "misconception": (
            "Many people view insurance as an expense to minimize rather than a foundation to build on. "
            "Adequate coverage is one of the highest-return decisions available to a family."
        ),
        "improvement": (
            "You have health, life, and disability coverage proportionate to your income and dependents. "
            "You review coverage every year as your life situation changes."
        ),
    },
    "Goal Clarity": {
        "why": (
            "Financial goals without written targets and dates are wishes, not plans. Research "
            "consistently shows that written specific goals are dramatically more likely to be achieved "
            "than vague intentions, regardless of income level."
        ),
        "misconception": (
            "Many people believe they know their goals because they think about them often. Mental "
            "goals are easily overridden by day-to-day spending decisions. Writing them creates a "
            "commitment."
        ),
        "improvement": (
            "You have 3-5 written financial goals with specific dollar targets and dates. You review "
            "them weekly. Your spending decisions are filtered through whether they help or hurt those "
            "goals."
        ),
    },
    "Tax Awareness": {
        "why": (
            "Tax-advantaged accounts offer guaranteed returns in the form of tax savings that do not "
            "depend on market performance. Not using them is one of the most common and most costly "
            "financial mistakes across all income levels."
        ),
        "misconception": (
            "Many people believe tax planning is only for high earners or requires a financial advisor. "
            "In reality, basic tax-advantaged account use is accessible to most working people and "
            "requires only simple annual decisions."
        ),
        "improvement": (
            "You contribute to at least one tax-advantaged account monthly. You do basic tax planning "
            "each quarter. You are not leaving obvious tax savings unused."
        ),
    },
    "Diversification": {
        "why": (
            "Concentration risk means your outcomes depend heavily on a single company, sector, or "
            "geography. For halal investors, diversification through Shariah-compliant ETFs and funds "
            "reduces this exposure while maintaining compliance."
        ),
        "misconception": (
            "Many investors believe they are diversified because they own multiple stocks. If those "
            "stocks are all in the same sector or region, the diversification is mostly illusory."
        ),
        "improvement": (
            "No single position represents more than 20% of your halal portfolio. You hold exposure "
            "across multiple sectors and geographies through Shariah-screened instruments."
        ),
    },
    "Behavioral Discipline": {
        "why": (
            "Behavioral mistakes - panic selling in downturns, chasing hot tips, overtrading - destroy "
            "more wealth than poor investment selection. The best halal portfolio fails if fear or greed "
            "drives the decisions around it."
        ),
        "misconception": (
            "Many investors believe they will stay calm during market drops because they have good "
            "intentions. In practice, seeing account values fall triggers emotional responses in almost "
            "everyone without a written plan in place."
        ),
        "improvement": (
            "You have a written investment policy that defines what you will do in a downturn before "
            "it happens. You do not check your portfolio daily. You ignore hot tips by default."
        ),
    },
}


HABITS_BY_CATEGORY: dict[str, list[str]] = {
    "Cash Flow": [
        "Track every expense for 30 days using a simple app or notebook",
        "Set up an automatic transfer to savings on the day you receive your paycheck",
        "Review your budget every Sunday for 10 minutes to catch overspending early",
    ],
    "Emergency Preparedness": [
        "Open a separate high-yield savings account dedicated only to your emergency fund",
        "Automate a fixed monthly transfer to your emergency fund before spending on anything else",
        "Review your emergency fund target every 6 months as your expenses change",
    ],
    "Debt Management": [
        "List all debts by interest rate and focus extra payments on the highest rate first",
        "Stop adding new high-interest debt by removing saved card details from online stores",
        "Celebrate each debt paid off to maintain motivation for the full payoff journey",
    ],
    "Investing Readiness": [
        "Invest a fixed amount every month regardless of market conditions - consistency beats timing",
        "Use the iRizq Halal Stock Checker at stocks.irizq.com to screen investments before buying",
        "Read one article or watch one video about halal investing every week to build knowledge",
    ],
    "Retirement Planning": [
        "Increase your retirement contribution by 1% every time you receive a pay increase",
        "Check your retirement account balance and allocation once every 6 months - not daily",
        "Calculate your retirement number (monthly expenses multiplied by 300) so you have a clear target to work toward",
    ],
    "Insurance and Risk": [
        "Schedule an annual insurance review every January to make sure coverage still fits your life situation",
        "Read your policy documents once a year so you know exactly what is and is not covered",
        "Get quotes from at least two providers before renewing any insurance policy",
    ],
    "Goal Clarity": [
        "Write your top 3 financial goals on a card and review them every Monday morning",
        "Break each goal into monthly milestones so progress is visible and measurable",
        "Tell one trusted person your financial goals for accountability and encouragement",
    ],
    "Tax Awareness": [
        "Contribute to at least one tax-advantaged account every month before spending elsewhere",
        "Keep a folder of receipts and documents throughout the year instead of scrambling at tax time",
        "Schedule a 30-minute tax planning session every quarter to stay ahead of surprises",
    ],
    "Diversification": [
        "Review your asset allocation once every 6 months and rebalance if any category has drifted more than 10% from your target",
        "Never put more than 20% of your halal portfolio into a single stock or sector",
        "Add one new halal asset class or fund each year to gradually broaden your diversification",
    ],
    "Behavioral Discipline": [
        "Wait 48 hours before making any unplanned investment decision - impulse and investing are a dangerous combination",
        "Unfollow social media accounts that promote get-rich-quick schemes or create financial anxiety",
        "Write down your investment plan and read it before making any changes to your portfolio",
    ],
}


def _habits_for_category(category: str) -> list[str]:
    habits = [h.strip() for h in HABITS_BY_CATEGORY.get(category, []) if h and str(h).strip()]
    while len(habits) < 3:
        habits.append(f"Take one concrete next step to strengthen {category}")
    return habits[:3]


def _actions_for_categories(weak: list[str]) -> dict[str, list[str]]:
    catalog = {
        "Cash Flow": [
            "Track every expense for 7 days",
            "Automate a transfer on payday",
            "Cut one recurring non-essential cost",
        ],
        "Emergency Preparedness": [
            "Open a dedicated emergency account",
            "Set a first target of $1,000",
            "Move emergency cash out of checking",
        ],
        "Debt Management": [
            "List all debts with APR and balance",
            "Pay more than the minimum on the highest APR",
            "Pause new revolving debt this month",
        ],
        "Investing Readiness": [
            "Define your investing account and contribution date",
            "Choose one broad diversified vehicle to start",
            "Write your rules for buying and selling",
        ],
        "Retirement Planning": [
            "Confirm retirement account eligibility",
            "Increase contribution by 1%",
            "Estimate a rough retirement income target",
        ],
        "Insurance and Risk": [
            "Review beneficiaries on existing policies",
            "Compare quotes for missing coverage types",
            "Calendar a semi-annual insurance review",
        ],
        "Goal Clarity": [
            "Write one 12-month financial goal",
            "Attach a dollar amount and deadline",
            "Share the goal with an accountability partner",
        ],
        "Tax Awareness": [
            "List tax-advantaged accounts you can use",
            "Contribute something this month if eligible",
            "Note one tax-efficient habit to research",
        ],
        "Diversification": [
            "Calculate your largest holding percentage",
            "Add one diversifying position this month",
            "Reduce employer-stock concentration gradually",
        ],
        "Behavioral Discipline": [
            "Create a written response plan for a 20% drop",
            "Mute speculative tip channels for 30 days",
            "Use a checklist before every new investment",
        ],
    }
    defaults = {
        "week": (
            "Visit stocks.irizq.com and screen one investment you currently hold or are "
            "considering for Shariah compliance."
        ),
        "month": (
            "Write down your top 3 financial goals with a target date and dollar amount "
            "for each - review them every Monday."
        ),
        "ninety": (
            "Schedule a 30-minute financial review to check progress on all three action "
            "plan items and set new 90-day targets."
        ),
    }
    week: list[str] = []
    month: list[str] = []
    ninety: list[str] = []
    cats = (weak[:3] + ["Cash Flow", "Emergency Preparedness", "Debt Management"])[:3]
    for idx, cat in enumerate(cats):
        items = list(catalog.get(cat, [])[:3])
        if idx == 0:
            week = items
        elif idx == 1:
            month = items
        else:
            ninety = items

    def _ensure_three(items: list[str], key: str) -> list[str]:
        out = [i for i in items if i and str(i).strip()]
        while len(out) < 3:
            filler = defaults[key]
            if filler not in out:
                out.append(filler)
            else:
                out.append(f"Complete one additional action from your {key} priorities")
        return out[:3]

    return {
        "week": _ensure_three(week, "week"),
        "month": _ensure_three(month, "month"),
        "ninety": _ensure_three(ninety, "ninety"),
    }


def _toc_page(styles: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("What's Inside Your Report"))
    toc_rows = [
        ("Executive Summary", "1"),
        ("Table of Contents", "2"),
        ("Your Score Breakdown", "3"),
        ("Costly Mistakes", "4"),
        ("Personalized Insights", "6"),
        ("Your Investor Profile", "8"),
        ("Priority Action Plan", "9"),
        ("Educational Guidance", "10"),
        ("Future Scenarios", "12"),
        ("Financial Checklist", "13"),
        ("Overall Grade and Next Steps", "14"),
    ]
    rows = []
    for section, page in toc_rows:
        dots = "." * max(8, 58 - len(section))
        left = Paragraph(f"{section} <font color='#6b7280'>{dots}</font>", styles["toc_name"])
        right = Paragraph(page, styles["toc_page"])
        rows.append([left, right])
    toc_table = Table(rows, colWidths=[5.9 * inch, 0.7 * inch])
    toc_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(toc_table)
    story.append(Spacer(1, 18))
    story.append(
        Paragraph(
            "Your personalized halal financial roadmap",
            styles["teal_italic"],
        )
    )
    story.append(Spacer(1, 14))
    story.append(Paragraph("How to Use This Report", styles["toc_howto_h"]))
    for paragraph in (
        "Start with the Executive Summary on page 1 to understand your overall score and the "
        "most urgent priorities at a glance.",
        "Review Your Score Breakdown on page 3 to see how each of the 10 categories contributes "
        "to your overall readiness and where the biggest gaps are.",
        "Work through the Priority Action Plan on page 9. The actions are ordered by urgency - "
        "start with This Week before moving to 30 and 90 day items.",
        "Return to the Educational Guidance on page 10 when you are ready to go deeper on any "
        "specific category. Each section includes habits you can start immediately.",
    ):
        story.append(Paragraph(paragraph, styles["toc_howto_body"]))
    return story


def _future_scenarios(
    styles: dict[str, ParagraphStyle],
    profile: str,
    category_scores: dict[str, Any],
) -> list[Any]:
    ranked_low = sorted(category_scores.items(), key=lambda item: float(item[1]))
    gap_names = [name for name, _ in ranked_low[:3]]
    gap_text = ", ".join(gap_names) if gap_names else "foundation areas"

    story: list[Any] = []
    story.extend(_header_band("Future Scenarios (Illustrative)"))
    story.append(
        Paragraph(
            "These scenarios are hypothetical illustrations only. They are not forecasts or promises of returns.",
            styles["muted"],
        )
    )
    story.append(Spacer(1, 6))

    article = "an" if profile[:1].lower() in "aeiou" else "a"
    s1_body = (
        f"As {article} {profile} investor, consistency can matter more than perfect timing. "
        "When monthly halal investing is automated, savings transfers happen without decision fatigue, "
        "and high-interest debt shrinks each month, readiness compounds quietly in the background. "
        "Patience and process turn small contributions into meaningful long-term optionality.<br/><br/>"
        "<b>Key actions that drive this scenario:</b><br/>"
        "- Automated monthly halal investment contribution<br/>"
        "- Emergency fund maintained above 3 months<br/>"
        "- High-interest debt eliminated<br/>"
        "- Annual portfolio review and rebalancing"
    )
    story.append(_callout("Scenario 1: The Consistent Builder", s1_body, TEAL))
    story.append(Paragraph("(Illustrative only - not a forecast)", styles["scenario_sub"]))

    s2_body = (
        f"For {article} {profile} investor, if habits stay roughly the same, short-term comfort can "
        f"mask growing opportunity cost. In your results, gaps around {gap_text} are the areas most "
        "likely to keep progress flat. Nothing dramatic has to go wrong for options to narrow - "
        "unfinished systems simply keep compounding delayed.<br/><br/>"
        "<b>Factors that keep this scenario in place:</b><br/>"
        "- No change to savings automation<br/>"
        "- Gaps in insurance or diversification continue<br/>"
        "- Written goals remain unset<br/>"
        "- Behavioral reactions to market news continue"
    )
    story.append(_callout("Scenario 2: The Comfort Zone", s2_body, AMBER))
    story.append(Paragraph("(Illustrative only - not a forecast)", styles["scenario_sub"]))

    s3_body = (
        f"Even for {article} {profile} investor, an unexpected expense, income pause, or family need "
        "can arrive at any time. Without an adequate emergency buffer or aligned insurance, recovery "
        "often means selling halal investments at the wrong moment or taking on expensive debt. "
        "This scenario is not dramatic by design - it is simply what unprepared foundations look like "
        "under ordinary stress.<br/><br/>"
        "<b>Vulnerabilities that increase this risk:</b><br/>"
        "- Emergency fund below 3 months of expenses<br/>"
        "- Insurance coverage gaps<br/>"
        "- High-interest debt with no paydown plan<br/>"
        "- Concentrated rather than diversified holdings"
    )
    story.append(_callout("Scenario 3: The Unprepared Setback", s3_body, RED))
    story.append(Paragraph("(Illustrative only - not a forecast)", styles["scenario_sub"]))

    disclaimer_box = Table(
        [[
            Paragraph(
                "These scenarios are for educational purposes only. They are not financial forecasts, "
                "projections, or personalized advice. Actual outcomes depend on many factors outside "
                "the scope of this assessment.",
                styles["body_left"],
            )
        ]],
        colWidths=[6.8 * inch],
    )
    disclaimer_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL_PALE),
                ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(Spacer(1, 8))
    story.append(disclaimer_box)
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    return story


def _back_cover(styles: dict[str, ParagraphStyle]) -> list[Any]:
    top = [
        Spacer(1, 18),
        _logo_flowable(1.35 * inch),
        Spacer(1, 10),
        Paragraph("InvestReady", styles["white_title"]),
        HRFlowable(width=100, thickness=2, color=TEAL, spaceBefore=2, spaceAfter=10),
        Paragraph("stocks.irizq.com", ParagraphStyle(
            "IRCoverLink",
            parent=styles["white_center"],
            textColor=TEAL,
            fontSize=11,
        )),
        Spacer(1, 4),
        Paragraph(
            "Halal Wealth for Every Muslim",
            ParagraphStyle(
                "IRCoverTag",
                parent=styles["white_center"],
                fontSize=10,
                textColor=colors.Color(1, 1, 1, alpha=0.75),
            ),
        ),
        Spacer(1, 12),
    ]
    top_table = Table([[top]], colWidths=[7.0 * inch])
    top_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 18),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 20),
                ("RIGHTPADDING", (0, 0), (-1, -1), 20),
            ]
        )
    )

    features = BackCoverFeaturesBand(width=7.0 * inch, height=140)

    quote_block = [
        Spacer(1, 16),
        Paragraph(
            "Earn halal - invest consistently - stay diversified - think long-term - let time grow your rizq.",
            ParagraphStyle(
                "IRCoverQuote",
                parent=styles["teal_italic"],
                fontSize=12,
                leading=16,
                textColor=TEAL,
            ),
        ),
        Spacer(1, 10),
        Paragraph(
            "May Allah bless your wealth, purify your earnings, and grant you barakah in your financial journey. Ameen.",
            ParagraphStyle(
                "IRCoverDua",
                parent=styles["white_center"],
                fontSize=10,
                fontName="Helvetica-Oblique",
                leading=14,
            ),
        ),
        Spacer(1, 18),
        Paragraph(DISCLAIMER, styles["cover_disclaimer"]),
        Spacer(1, 8),
        Paragraph("2026 iRizq.com. All rights reserved.", styles["cover_copy"]),
        Spacer(1, 12),
    ]
    bottom = Table([[quote_block]], colWidths=[7.0 * inch])
    bottom.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 24),
                ("RIGHTPADDING", (0, 0), (-1, -1), 24),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ]
        )
    )

    return [top_table, features, bottom]


def generate_investready_pdf(payload: dict[str, Any]) -> bytes:
    """Generate the InvestReady PDF and return raw bytes."""
    styles = _styles()
    name = str(payload.get("name") or "Investor").strip() or "Investor"
    email = str(payload.get("email") or "").strip()
    overall = int(round(float(payload.get("overall_score") or 0)))
    grade = str(payload.get("letter_grade") or "C")
    profile = str(payload.get("investor_profile") or "Moderate")
    category_scores = {
        str(k): float(v) for k, v in (payload.get("category_scores") or {}).items()
    }
    answers = payload.get("answers") or {}
    strengths, risks, strength_label, foundation_msg = _strengths_and_risks(category_scores)
    mistakes = _mistakes(answers, category_scores)
    weak_cats = [
        name_
        for name_, score in sorted(category_scores.items(), key=lambda item: float(item[1]))
        if float(score) < 70
    ]
    actions = _actions_for_categories(weak_cats or list(category_scores.keys())[:3])
    insights = _personalized_insights(category_scores, overall, profile)
    focus_areas = _top_focus_areas(category_scores)
    report_id = _make_report_id()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.70 * inch,
        bottomMargin=0.70 * inch,
        title="InvestReady Financial Readiness Report",
        author="iRizq.com",
    )
    story: list[Any] = []

    # PAGE 1 - Executive Summary
    for item in _bismillah_flowables(styles):
        story.append(item)
    story.append(Spacer(1, 12))
    story.append(_logo_flowable(1.15 * inch))
    story.append(Spacer(1, 16))
    story.extend(_header_band("InvestReady Financial Readiness Report"))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Prepared for <b>{name}</b>", styles["center"]))
    story.append(Paragraph(f"Report ID: {report_id}", styles["report_id"]))
    meta_bits = []
    if email:
        meta_bits.append(email)
    meta_bits.append(datetime.utcnow().strftime("Generated %B %d, %Y"))
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), styles["muted"]))
    story.append(Spacer(1, 10))
    story.extend(_score_info_band(overall, grade, profile))

    page1_h = ParagraphStyle(
        "IRPage1H",
        parent=styles["h2"],
        spaceBefore=0,
        spaceAfter=3,
        fontSize=12,
    )
    page1_item = ParagraphStyle(
        "IRPage1Item",
        parent=styles["body_left"],
        fontSize=9,
        leading=12,
        spaceAfter=2,
    )
    if foundation_msg:
        story.append(Paragraph("<b>Strengths</b>", page1_h))
        story.append(Paragraph(foundation_msg, styles["foundation_msg"]))
    else:
        strengths_heading = (
            "Your Top Strengths" if strength_label == "Strength" else "Relatively Stronger Areas"
        )
        story.append(Paragraph(f"<b>{strengths_heading}</b>", page1_h))
        for item in strengths:
            story.append(Paragraph(f"<font color='#1ec8b8'>&#10003;</font> {item}", page1_item))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Areas Needing Attention</b>", page1_h))
    if risks:
        for item in risks:
            story.append(Paragraph(f"<font color='#f59e0b'>!</font> {item}", page1_item))
    else:
        story.append(Paragraph("No categories currently fall below the attention threshold.", page1_item))
    story.append(Spacer(1, 12))
    summary = (
        f"{name}, your InvestReady score of {overall}/100 ({grade}) places you in the "
        f"{profile} profile. This report highlights where your foundation is solid and "
        f"where focused action over the next 7, 30, and 90 days can improve readiness. "
        f"Use it as an educational roadmap - not personalized investment advice."
    )
    story.append(Paragraph(summary, styles["body"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 2 - Table of Contents
    story.extend(_toc_page(styles))
    story.append(PageBreak())

    # PAGE 3 - Score Breakdown with visual bars
    story.extend(_header_band("Your Score Breakdown"))
    story.append(Spacer(1, 4))
    for cat, score in category_scores.items():
        story.append(ScoreBarRow(cat, float(score)))
        story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.8, color=NAVY, spaceBefore=4, spaceAfter=10))
    story.append(ScoreBarRow("Overall Score", float(overall), overall=True))
    story.append(Spacer(1, 16))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Costly Mistakes
    story.extend(_header_band("Costly Mistakes You May Be Making"))
    story.append(
        Paragraph(
            "These warnings are generated from your assessment answers and category scores. "
            "They are educational prompts to help you prioritize - not accusations or personalized advice.",
            styles["body"],
        )
    )
    for title, body in mistakes:
        story.append(_callout(title, body, AMBER))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Personalized Insights
    story.extend(_header_band("Personalized Insights"))
    for paragraph in insights:
        story.append(Paragraph(paragraph, styles["body"]))
        story.append(HRFlowable(width="40%", thickness=2, color=TEAL, spaceBefore=2, spaceAfter=8, hAlign="LEFT"))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Investor Profile
    story.extend(_header_band("Your Investor Profile"))
    story.append(Paragraph("YOUR PROFILE", styles["profile_label"]))
    story.append(Paragraph(f"Investor Profile: {profile}", styles["profile"]))
    story.append(Spacer(1, 16))
    profile_copy = PROFILE_DESCRIPTIONS.get(
        profile,
        "You balance growth and stability with a measured approach through a diversified halal investment portfolio.",
    )
    story.append(Paragraph(profile_copy, styles["body"]))
    story.append(Spacer(1, 8))
    story.append(_shariah_callout())
    story.append(Paragraph("<b>Illustrative allocation ranges</b>", styles["h2"]))
    story.append(Paragraph(_profile_allocation(profile), styles["body"]))
    story.append(Paragraph("<b>Common pitfalls for this profile</b>", styles["h2"]))
    story.append(
        Paragraph(
            "Overreacting to short-term news, skipping rebalancing, and letting lifestyle inflation "
            "absorb raises before goals are funded.",
            styles["body"],
        )
    )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Priority Action Plan
    story.extend(_header_band("Priority Action Plan"))
    for label, key, accent in (
        ("THIS WEEK", "week", TEAL),
        ("IN 30 DAYS", "month", GREEN),
        ("IN 90 DAYS", "ninety", NAVY),
    ):
        story.append(_callout(label, "<br/>".join(f"- {item}" for item in actions[key]), accent))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Educational Section
    story.extend(_header_band("Educational Guidance for Priority Categories"))
    edu_targets = weak_cats[:5] or list(category_scores.keys())[:3]
    for cat in edu_targets:
        edu = CATEGORY_EDU.get(cat, {})
        story.append(Paragraph(cat, styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=2, color=TEAL, spaceAfter=6))
        story.append(
            Paragraph(
                f"<b>Why {cat} matters:</b> "
                + edu.get(
                    "why",
                    "Strength in this area reduces avoidable risk and improves long-term optionality.",
                ),
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "<b>Common misconception:</b> "
                + edu.get(
                    "misconception",
                    "Waiting for perfect conditions. Progress usually comes from small repeatable "
                    "habits, not perfect timing.",
                ),
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "<b>What improvement looks like:</b> "
                + edu.get(
                    "improvement",
                    "Clear numbers, automated systems, and a written rule set you can follow under stress.",
                ),
                styles["body"],
            )
        )
        story.append(Paragraph("<b>3 habits to build:</b>", styles["body_left"]))
        for habit in _habits_for_category(cat):
            if habit:
                story.append(Paragraph(f"- {habit}", styles["body_left"]))
        story.append(Spacer(1, 6))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Future Scenarios
    story.extend(_future_scenarios(styles, profile, category_scores))
    story.append(PageBreak())

    # Checklist
    story.extend(_header_band("Your Financial Readiness Checklist"))
    story.append(Spacer(1, 4))
    checklist = [
        "Written budget and known monthly cash surplus",
        "Emergency fund separated from spending money",
        "High-interest debt paydown plan in writing",
        "Automated investing contributions",
        "Diversified holdings with concentration limits",
        "Retirement account in use (if eligible)",
        "Insurance coverage reviewed in the last year",
        "Goals with dates and dollar targets",
        "Basic tax-advantaged account strategy",
        "Behavioral rules for market drops and hot tips",
    ]
    for item in checklist:
        story.append(ChecklistItem(item))
        story.append(Spacer(1, 14))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Overall Grade and Next Steps
    story.extend(_header_band("Overall Grade and Next Steps"))
    story.extend(_score_info_band(overall, grade, profile))
    story.append(
        Paragraph(
            f"Your grade of {grade} reflects an overall score of {overall}/100. "
            f"Treat this as a snapshot of readiness, not a permanent label.",
            styles["body"],
        )
    )
    story.append(Paragraph("<b>Top 3 focus areas</b>", styles["h2"]))
    for line in focus_areas:
        story.append(Paragraph(line, styles["body_left"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Continue your journey:", styles["h2"]))
    story.append(Paragraph("iRizq.com &nbsp;|&nbsp; stocks.irizq.com", styles["teal"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # Back Cover
    story.extend(_back_cover(styles))

    def _canvas_maker(*args: Any, **kwargs: Any) -> InvestReadyCanvas:
        return InvestReadyCanvas(*args, prepared_for=name, **kwargs)

    doc.build(story, canvasmaker=_canvas_maker)
    return buffer.getvalue()
