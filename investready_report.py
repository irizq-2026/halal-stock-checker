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

CATEGORY_ORDER = [
    "Cash Stability",
    "Debt Position",
    "Savings Behavior",
    "Investing Readiness",
    "Financial Behavior",
    "Retirement Planning",
    "Risk Alignment",
    "Tax Awareness",
    "Financial Protection",
]

Q4_LABELS = {
    0: "none at all",
    1: "less than 1 month",
    2: "1 to 3 months",
    3: "3 to 6 months",
    4: "more than 6 months",
}

FINANCIAL_STAGE_DESCRIPTIONS = {
    "Foundation Builder": (
        "Your priority is building the financial foundation before focusing on growth."
    ),
    "Stability Seeker": (
        "You are working toward stability. Consistent habits will accelerate progress."
    ),
    "Growth Ready": (
        "Your foundation is developing. You are approaching readiness for focused growth."
    ),
    "Wealth Builder": (
        "You have a strong foundation and are positioned to build wealth systematically."
    ),
    "Optimizer": (
        "Your fundamentals are strong. Focus on optimizing and scaling what is working."
    ),
}

STAGE_BOTTOM_LINE = {
    "Foundation Builder": (
        "Your finances are in an early-stage build phase. The priority is stability and "
        "habit formation, not investment scaling."
    ),
    "Stability Seeker": (
        "You are in a stability-building phase. Addressing the gaps identified will create "
        "the platform for more confident financial growth."
    ),
    "Growth Ready": (
        "You are approaching a growth phase but have key gaps to close first. Addressing "
        "these now will make growth more sustainable."
    ),
    "Wealth Builder": (
        "You are in an active wealth-building phase. Fine-tuning the gaps identified will "
        "improve your trajectory meaningfully."
    ),
    "Optimizer": (
        "You are in an optimization phase. The opportunities identified here are "
        "refinements to an already strong foundation."
    ),
}

STAGE_INSIGHT = {
    "Foundation Builder": (
        "The good news is that at your stage, the actions that matter most are simple and "
        "within immediate reach. Building the foundation now creates a platform that makes "
        "everything else easier."
    ),
    "Stability Seeker": (
        "You have already built some structure. The opportunity is to close the remaining "
        "gaps before they become more expensive to fix. Progress from here accelerates as "
        "each piece of the foundation locks in."
    ),
    "Growth Ready": (
        "You are closer to a strong financial position than your score may suggest. "
        "Targeted improvements to your weakest areas will shift your trajectory "
        "meaningfully within 6 to 12 months."
    ),
    "Wealth Builder": (
        "Your foundation is solid. The focus from here is refinement and optimization "
        "rather than reconstruction. Small improvements to high-impact areas will "
        "compound into significant gains."
    ),
    "Optimizer": (
        "Your financial fundamentals are strong. The opportunities identified here are "
        "precision improvements that will protect and accelerate what you have already built."
    ),
}

STAGE_VERDICT = {
    "Foundation Builder": (
        "Your priority is building the financial habits and buffers that make everything "
        "else possible. Growth should come after stability."
    ),
    "Stability Seeker": (
        "You are making progress on your foundation. The gaps identified are addressable "
        "with consistent focused effort over the next 3 to 6 months."
    ),
    "Growth Ready": (
        "Your foundation is developing well. Closing the identified gaps will position "
        "you for more confident financial growth."
    ),
    "Wealth Builder": (
        "You are positioned to build wealth systematically. The improvements identified "
        "will strengthen an already solid foundation."
    ),
    "Optimizer": (
        "Your financial fundamentals are strong. The opportunities here are precision "
        "improvements to an already well-structured position."
    ),
}

STAGE_RECOMMENDATION = {
    "Foundation Builder": (
        "Focus entirely on stability before any growth or investment scaling."
    ),
    "Stability Seeker": (
        "Build your emergency buffer and reduce debt before increasing investment activity."
    ),
    "Growth Ready": (
        "Close your top 2 identified gaps before scaling investment contributions."
    ),
    "Wealth Builder": (
        "Optimize your existing structure and automate the remaining manual decisions."
    ),
    "Optimizer": (
        "Refine and protect what is working. Focus on the smallest high-impact "
        "improvements identified."
    ),
}

PRIMARY_GAP_LABELS = {
    "Cash Stability": "building financial stability",
    "Debt Position": "eliminating high-interest debt drag",
    "Savings Behavior": "creating consistent savings habits",
    "Investing Readiness": "establishing a halal investing foundation",
    "Financial Behavior": "removing emotion from financial decisions",
    "Retirement Planning": "securing your long-term planning",
    "Risk Alignment": "aligning stated risk tolerance with real behavior",
    "Tax Awareness": "capturing available tax advantages",
    "Financial Protection": "closing financial protection gaps",
}

STRENGTH_OBS = {
    "Cash Stability": (
        "a reliable liquid buffer that can absorb unexpected expenses without forcing "
        "reactive decisions"
    ),
    "Debt Position": (
        "manageable debt obligations that are not crowding out savings and investing capacity"
    ),
    "Savings Behavior": (
        "consistent saving habits that create quiet momentum toward long-term goals"
    ),
    "Investing Readiness": (
        "an established habit of putting capital to work through a structured approach"
    ),
    "Financial Behavior": (
        "disciplined decision-making patterns that protect progress under stress"
    ),
    "Retirement Planning": (
        "active attention to long-horizon funding rather than leaving the future to chance"
    ),
    "Risk Alignment": (
        "alignment between how you describe risk tolerance and how you would likely act"
    ),
    "Tax Awareness": (
        "awareness of tax-advantaged tools that can improve after-tax compounding"
    ),
    "Financial Protection": (
        "meaningful protection arrangements that reduce the damage from income or health shocks"
    ),
}

CONCERN_OBS = {
    "Cash Stability": (
        "Your responses suggest your emergency buffer may be insufficient to absorb "
        "income disruption or unexpected expenses."
    ),
    "Debt Position": (
        "Your responses indicate high-interest debt obligations that may be quietly "
        "reducing your financial progress."
    ),
    "Savings Behavior": (
        "Your responses suggest savings habits may be irregular or below the level "
        "needed to build durable momentum."
    ),
    "Investing Readiness": (
        "Your responses suggest investing habits are incomplete relative to a resilient "
        "long-term plan."
    ),
    "Financial Behavior": (
        "Your responses reflect patterns that suggest emotional or inconsistent "
        "financial decision-making."
    ),
    "Retirement Planning": (
        "Your responses suggest long-term retirement funding may not yet be receiving "
        "enough structured attention."
    ),
    "Risk Alignment": (
        "Your responses suggest a gap between stated risk tolerance and likely behavior "
        "under market pressure."
    ),
    "Tax Awareness": (
        "Your responses suggest available tax-advantaged accounts may be underused."
    ),
    "Financial Protection": (
        "Your responses suggest gaps in financial protection that could reverse progress "
        "after one major shock."
    ),
}


def _register_fonts() -> str:
    global _ARABIC_FONT, _HAS_ARABIC_FONT
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
FINAL_DISCLAIMER = (
    "Educational only. iRizq does not provide financial, legal, tax, or investment advice. "
    "This report is for personal educational use only. Consult qualified professionals for "
    "personalized guidance."
)

BISMILLAH_AR = "بسم الله الرحمن الرحيم"
BISMILLAH_EN = "In the name of Allah, the Most Gracious, the Most Merciful"
BISMILLAH_EN_FALLBACK = "Bismillah ir-Rahman ir-Raheem"


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
        "body_small": ParagraphStyle(
            "IRBodySmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            textColor=TEXT,
            leading=12,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "teal": ParagraphStyle(
            "IRTeal",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEAL,
            spaceAfter=6,
            alignment=TA_CENTER,
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
        "intro_muted": ParagraphStyle(
            "IRIntroMuted",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=MUTED,
            alignment=TA_LEFT,
            spaceAfter=10,
            leading=12,
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
        "privacy": ParagraphStyle(
            "IRPrivacy",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=4,
            leading=11,
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
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=10,
            spaceAfter=8,
            leading=16,
        ),
        "interp": ParagraphStyle(
            "IRInterp",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceBefore=8,
            spaceAfter=4,
            leading=13,
        ),
        "path_h_navy": ParagraphStyle(
            "IRPathNavy",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=6,
        ),
        "path_h_teal": ParagraphStyle(
            "IRPathTeal",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=TEAL,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "cost_h": ParagraphStyle(
            "IRCostH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=AMBER,
            spaceBefore=4,
            spaceAfter=3,
        ),
        "fix_h": ParagraphStyle(
            "IRFixH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=TEAL,
            spaceBefore=4,
            spaceAfter=3,
        ),
        "rec_h": ParagraphStyle(
            "IRRecH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=TEAL,
            spaceBefore=8,
            spaceAfter=6,
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
        "section_h": ParagraphStyle(
            "IRSectionH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=4,
        ),
        "item_small": ParagraphStyle(
            "IRItemSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            textColor=TEXT,
            leading=12,
            spaceAfter=2,
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


def _teal_note(body: str) -> KeepTogether:
    styles = _styles()
    inner = [Paragraph(body, styles["shariah_body"])]
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
    return KeepTogether([table, Spacer(1, 4)])


def _bismillah_flowables(styles: dict[str, ParagraphStyle]) -> list[Any]:
    """Render Arabic Bismillah with shaping, or English-only fallback."""
    try:
        if _HAS_ARABIC_FONT and _ARABIC_LIBS_OK and arabic_reshaper and get_display:
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


def _score_info_band(overall: int, grade: str, stage: str) -> list[Any]:
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
        Paragraph("FINANCIAL STAGE", styles["band_label"]),
        Paragraph(stage, styles["band_profile"]),
    ]
    table = Table(
        [[left, middle, right]],
        colWidths=[2.33 * inch, 2.34 * inch, 2.33 * inch],
        rowHeights=[80],
    )
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
        c.setFillColor(NAVY_MID)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)

        box_w = 1.95 * inch
        box_h = 92
        gap = (self.width - 3 * box_w) / 4.0
        y = 20
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
        if page <= 1 or page >= page_count:
            return

        left = 0.65 * inch
        right = PAGE_WIDTH - 0.65 * inch

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


def _ans_int(answers: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(answers.get(key, default) if answers.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _normalize_scores(raw: dict[str, Any] | None) -> dict[str, float]:
    scores = {str(k): float(v) for k, v in (raw or {}).items()}
    ordered: dict[str, float] = {}
    for name in CATEGORY_ORDER:
        if name in scores:
            ordered[name] = scores[name]
    for name, value in scores.items():
        if name not in ordered:
            ordered[name] = value
    return ordered


def _ranked(scores: dict[str, float], *, reverse: bool = False) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: item[1], reverse=reverse)


def _snapshot_phrase(overall: int) -> str:
    if overall >= 80:
        return "a strong foundation with targeted gaps to address"
    if overall >= 65:
        return "a developing foundation with meaningful opportunities to strengthen"
    if overall >= 50:
        return "a foundation in progress with several gaps that carry real financial risk"
    return (
        "an early-stage financial position where foundational stability should take "
        "priority over growth"
    )


def _q4_label(answers: dict[str, Any]) -> str:
    return Q4_LABELS.get(_ans_int(answers, "q4", 0), "limited accessible savings")


def _flag_set(payload: dict[str, Any], answers: dict[str, Any]) -> dict[str, bool]:
    behavior_flags = payload.get("behavior_flags") or []
    if not isinstance(behavior_flags, list):
        behavior_flags = []
    flag_names = {str(x).upper() for x in behavior_flags}

    def flag(name: str) -> bool:
        if name in payload:
            return _as_bool(payload.get(name))
        return name in flag_names

    critical = flag("CRITICAL_STABILITY")
    if "CRITICAL_STABILITY" not in payload:
        critical = _ans_int(answers, "q4", 4) <= 1

    low_saver = flag("LOW_SAVER")
    if "LOW_SAVER" not in payload:
        low_saver = _ans_int(answers, "q8", 4) == 0

    emotional = flag("EMOTIONAL_INVEST")
    risk_mismatch = flag("RISK_MISMATCH")
    if "RISK_MISMATCH" not in payload:
        risk_mismatch = _ans_int(answers, "q18", 0) >= 3 and _ans_int(answers, "q19", 2) == 0

    return {
        "CRITICAL_STABILITY": critical,
        "LOW_SAVER": low_saver,
        "EMOTIONAL_INVEST": emotional,
        "POOR_PLANNING": flag("POOR_PLANNING"),
        "DEBT_HABIT": flag("DEBT_HABIT"),
        "OVERSPEND": flag("OVERSPEND"),
        "LOW_DISCIPLINE": flag("LOW_DISCIPLINE"),
        "RISK_MISMATCH": risk_mismatch,
    }


def _risk_pack(
    category: str,
    score: float,
    *,
    answers: dict[str, Any],
    flags: dict[str, bool],
    scores: dict[str, float],
) -> dict[str, Any]:
    investing = float(scores.get("Investing Readiness", 0))

    if category == "Cash Stability":
        return {
            "name": "Liquidity Risk",
            "means": (
                f"Based on your responses, you currently have {_q4_label(answers)} in "
                "accessible savings. Without adequate liquid reserves, any unexpected "
                "expense or income disruption forces reactive financial decisions."
            ),
            "costs": [
                "Forced withdrawal from investments at the wrong time",
                "Reliance on high-interest debt during emergencies",
                "Financial decisions driven by panic rather than strategy",
            ],
            "fixes": [
                "Set a minimum emergency target of 3 months of expenses",
                "Open a dedicated account separate from daily spending",
                "Automate a fixed transfer every payday",
            ],
            "takaful": False,
        }

    if category == "Debt Position":
        return {
            "name": "Debt Drag Risk",
            "means": (
                "Based on your responses, high-interest debt obligations are currently "
                "competing with your ability to save and invest. Interest payments create "
                "a guaranteed negative return that is difficult to outperform through investing."
            ),
            "costs": [
                "Compounding interest quietly growing faster than your savings",
                "Reduced monthly cash available for halal investments",
                "Delayed financial independence timeline",
            ],
            "fixes": [
                "List all debts by interest rate today",
                "Direct all extra monthly cash toward the highest rate balance first",
                "Pause new discretionary spending until high-rate debt is cleared",
            ],
            "takaful": False,
        }

    if category == "Savings Behavior":
        return {
            "name": "Savings Inconsistency Risk",
            "means": (
                "Based on your responses, your savings pattern appears irregular or below "
                "the level needed to build meaningful financial momentum. Inconsistent "
                "saving creates gaps in the financial foundation that compound over time."
            ),
            "costs": [
                "Insufficient buffer to survive income disruption without debt",
                "Slower progress toward financial goals",
                "Higher stress during financial shocks",
            ],
            "fixes": [
                "Automate savings on the day income arrives",
                "Start with any fixed amount - consistency matters more than the amount",
                "Increase savings rate by 1% every 3 months",
            ],
            "takaful": False,
        }

    if category == "Investing Readiness":
        premature = flags.get("CRITICAL_STABILITY") and investing > 0
        if premature:
            return {
                "name": "Premature Investing Risk",
                "means": (
                    "Based on your responses, you appear to be investing while your financial "
                    "foundation has critical gaps. Investing without adequate emergency "
                    "reserves or high debt present means you may be forced to sell at the "
                    "worst possible time."
                ),
                "costs": [
                    "Selling halal investments at a loss during an emergency",
                    "Eliminating compounding gains built over months or years",
                    "Emotional decision-making amplified by financial pressure",
                ],
                "fixes": [
                    "Pause new investment contributions temporarily",
                    "Build emergency fund to 3 months first",
                    "Resume halal investing once buffer is in place",
                ],
                "takaful": False,
            }
        return {
            "name": "Investing Gap Risk",
            "means": (
                "Based on your responses, you have not yet begun investing or your investing "
                "foundation remains incomplete. While building stability first is correct, "
                "there is an opportunity cost to delayed investing that compounds "
                "significantly over time."
            ),
            "costs": [
                "Lost compounding years that cannot be recovered",
                "Inflation quietly eroding the purchasing power of savings",
                "Delayed financial independence timeline",
            ],
            "fixes": [
                "Start with a small Shariah-compliant ETF or fund once foundation is stable",
                "Use stocks.irizq.com to screen any investment for halal compliance",
                "Even small monthly contributions build the habit and compound meaningfully",
            ],
            "takaful": False,
        }

    if category in {"Financial Behavior", "Risk Alignment"}:
        return {
            "name": "Behavioral Risk",
            "means": (
                "Based on your responses, your financial decision-making may be "
                "influenced by emotion or inconsistency. Behavioral mistakes - not "
                "poor investments - are the primary cause of underperformance for "
                "most individual investors."
            ),
            "costs": [
                "Panic selling during market downturns locking in permanent losses",
                "Chasing performance after gains have already happened",
                "Inconsistent strategy that prevents compounding from working",
            ],
            "fixes": [
                "Write an investment policy before the next market move happens",
                "Commit to not checking your portfolio more than once a month",
                "Define in advance what you will do if markets drop 20% or 30%",
            ],
            "takaful": False,
        }

    if category == "Financial Protection":
        return {
            "name": "Protection Gap Risk",
            "means": (
                "Based on your responses, there may be gaps in your financial protection "
                "coverage. Without adequate coverage, a single health or income disruption "
                "event can reverse years of financial progress."
            ),
            "costs": [
                "Unexpected health costs depleting savings and investments",
                "Income disruption with no replacement mechanism",
                "Financial hardship for dependents in worst-case scenarios",
            ],
            "fixes": [
                "Assess your current protection gaps against your income and dependents",
                "Explore Takaful or halal-compliant protection options",
                "At minimum, build a dedicated emergency buffer as a self-insurance starting point",
            ],
            "takaful": True,
        }

    if category == "Retirement Planning":
        return {
            "name": "Long-Term Funding Risk",
            "means": (
                f"Based on your responses, retirement planning scored {int(round(score))}/100. "
                "Delayed long-term funding is rarely dramatic in the short run, but the "
                "missed compounding years are difficult to recover later."
            ),
            "costs": [
                "Compounding years permanently lost",
                "Greater contribution burden required later to catch up",
                "Reduced flexibility near retirement age",
            ],
            "fixes": [
                "Open or contribute to a halal-compatible retirement account this quarter",
                "Write a target retirement number and contribution rate",
                "Increase contributions by at least 1% at the next income review",
            ],
            "takaful": False,
        }

    if category == "Tax Awareness":
        return {
            "name": "Tax Efficiency Risk",
            "means": (
                f"Based on your responses, tax awareness scored {int(round(score))}/100. "
                "Unused tax-advantaged accounts leave guaranteed savings on the table "
                "while market returns remain uncertain."
            ),
            "costs": [
                "Higher lifetime tax drag on investment growth",
                "Missed employer or account-level advantages",
                "Less capital available to compound over time",
            ],
            "fixes": [
                "List every tax-advantaged account you qualify for",
                "Increase contributions to at least one underused account",
                "Schedule a short year-end tax planning review",
            ],
            "takaful": False,
        }

    return {
        "name": f"{category} Risk",
        "means": (
            f"Based on your responses, {category} scored {int(round(score))}/100 and "
            "is among the gaps most likely to slow your financial progress."
        ),
        "costs": [
            "Slower progress toward long-term goals",
            "Higher vulnerability during financial stress",
            "Reactive decisions replacing a clear plan",
        ],
        "fixes": [
            f"Define one measurable improvement for {category} this week",
            "Automate one supporting habit within 30 days",
            "Reassess progress in 90 days",
        ],
        "takaful": False,
    }


def _build_risks(
    scores: dict[str, float],
    answers: dict[str, Any],
    flags: dict[str, bool],
) -> list[dict[str, Any]]:
    lowest = _ranked(scores)[:3]
    while len(lowest) < 3:
        lowest.append((f"Priority Area {len(lowest) + 1}", 0.0))
    risks = []
    for cat, score in lowest:
        pack = _risk_pack(cat, score, answers=answers, flags=flags, scores=scores)
        pack["category"] = cat
        pack["score"] = score
        risks.append(pack)
    return risks


def _action_plan(
    scores: dict[str, float],
    answers: dict[str, Any],
    flags: dict[str, bool],
) -> dict[str, list[str]]:
    debt = float(scores.get("Debt Position", 100))
    savings = float(scores.get("Savings Behavior", 100))
    investing = float(scores.get("Investing Readiness", 100))
    behavior = float(scores.get("Financial Behavior", 100))
    retirement = float(scores.get("Retirement Planning", 100))
    tax = float(scores.get("Tax Awareness", 100))
    protection = float(scores.get("Financial Protection", 100))
    stability = float(scores.get("Cash Stability", 100))
    risk_align = float(scores.get("Risk Alignment", 100))

    days7: list[str] = []
    if flags.get("CRITICAL_STABILITY") or stability < 50:
        days7.append(
            "Calculate your exact monthly expenses and set an emergency fund target of "
            "3 months as your first milestone."
        )
    if debt < 55 or _ans_int(answers, "q6", 4) <= 1:
        days7.append(
            "List every debt with its balance and interest rate. Identify the highest "
            "rate and commit to paying more than the minimum this month."
        )
    if flags.get("LOW_SAVER") or savings < 50:
        days7.append(
            "Set up an automatic transfer for any fixed amount on your next payday - "
            "even $50 builds the habit."
        )
    days7.append(
        "Visit stocks.irizq.com and verify the Shariah compliance of one investment "
        "you currently hold or are considering."
    )
    if flags.get("EMOTIONAL_INVEST") or behavior < 50:
        days7.append(
            "Write a one-page rule set for what you will buy, hold, and refuse to sell "
            "under stress."
        )
    days7 = days7[:3]
    while len(days7) < 3:
        days7.append(
            "Block 20 minutes this week to review this report and choose one habit to automate."
        )

    days30: list[str] = []
    if savings < 65:
        days30.append(
            "Increase your automated savings by any percentage - even 1% creates "
            "meaningful momentum over 12 months."
        )
    if flags.get("POOR_PLANNING") or _ans_int(answers, "q15", 4) <= 1:
        days30.append(
            "Install a simple expense tracking app and categorize your last 30 days of "
            "spending to find your biggest cash leak."
        )
    if investing < 40 and stability >= 55 and debt >= 55:
        days30.append(
            "Open a halal investment account and make your first contribution - amount "
            "matters less than starting the habit."
        )
    if flags.get("EMOTIONAL_INVEST") or behavior < 60 or flags.get("RISK_MISMATCH"):
        days30.append(
            "Write one page defining your investment rules - what you will buy, hold, "
            "and sell under what conditions."
        )
    days30.append(
        "Schedule a 30-minute financial review to assess progress on your 7-day actions."
    )
    days30 = days30[:3]
    while len(days30) < 3:
        days30.append(
            "Raise one automated transfer by a small fixed amount and keep it unchanged for 30 days."
        )

    days90: list[str] = []
    if retirement < 65:
        days90.append(
            "Open or increase contributions to a halal-compatible retirement account "
            "by at least 1% of income."
        )
    if investing > 0 and investing < 70:
        days90.append(
            "Review your portfolio for concentration risk - no single position should "
            "exceed 20% of total investments."
        )
    if tax < 65:
        days90.append(
            "Schedule a 30-minute session to review which tax-advantaged accounts you "
            "qualify for and are not using."
        )
    if protection < 65:
        days90.append(
            "Research Takaful or Shariah-compliant protection options available in your "
            "area for health and income protection."
        )
    if risk_align < 60:
        days90.append(
            "Revisit your written risk rules after one calm month and confirm they still "
            "match how you would act in a 20% drop."
        )
    days90.append(
        "Reassess your Financial Readiness Score by retaking this assessment and measure "
        "your improvement."
    )
    days90 = days90[:3]
    while len(days90) < 3:
        days90.append(
            "Document one structural improvement completed in the last quarter and one still open."
        )

    return {"days7": days7, "days30": days30, "days90": days90}


def _current_path_lines(
    scores: dict[str, float],
    flags: dict[str, bool],
    answers: dict[str, Any] | None = None,
) -> list[str]:
    answers = answers or {}
    lines: list[str] = []
    if float(scores.get("Cash Stability", 100)) < 60 or flags.get("CRITICAL_STABILITY"):
        lines.append(
            "Financial shocks will likely require debt or forced investment withdrawals to manage."
        )
    if float(scores.get("Savings Behavior", 100)) < 60 or flags.get("LOW_SAVER"):
        lines.append(
            "Progress toward financial goals will be slow and vulnerable to disruption."
        )
    if (
        flags.get("EMOTIONAL_INVEST")
        or flags.get("OVERSPEND")
        or flags.get("LOW_DISCIPLINE")
        or flags.get("POOR_PLANNING")
        or flags.get("DEBT_HABIT")
        or float(scores.get("Financial Behavior", 100)) < 55
    ):
        lines.append(
            "Investment decisions may continue to be influenced by market emotion rather than strategy."
        )
    if float(scores.get("Investing Readiness", 100)) <= 5 or _ans_int(answers, "q10", 1) == 0:
        lines.append(
            "Delayed investing means compounding works for others while your savings "
            "lose purchasing power to inflation."
        )
    if float(scores.get("Debt Position", 100)) < 55:
        lines.append(
            "High-interest obligations will keep absorbing cash that could otherwise build reserves."
        )
    if not lines:
        lines.append(
            "Without tightening the weakest categories, progress will remain uneven and easier to reverse."
        )
    return lines[:4]


def _improved_path_lines(
    scores: dict[str, float],
    flags: dict[str, bool],
) -> list[str]:
    lines: list[str] = []
    if float(scores.get("Cash Stability", 100)) < 70 or flags.get("CRITICAL_STABILITY"):
        lines.append(
            "A 3-6 month buffer means financial shocks become inconveniences rather than crises."
        )
    if float(scores.get("Savings Behavior", 100)) < 70 or flags.get("LOW_SAVER"):
        lines.append(
            "Consistent automated savings creates momentum that compounds quietly in the background."
        )
    if (
        flags.get("EMOTIONAL_INVEST")
        or flags.get("RISK_MISMATCH")
        or float(scores.get("Financial Behavior", 100)) < 65
    ):
        lines.append(
            "A written investment plan eliminates most emotional decision-making before it happens."
        )
    if float(scores.get("Investing Readiness", 100)) < 50:
        lines.append(
            "Beginning halal investments now - even small amounts - creates compounding "
            "that cannot be replicated later."
        )
    if float(scores.get("Debt Position", 100)) < 65:
        lines.append(
            "Clearing high-rate debt frees monthly cash and removes a guaranteed drag on progress."
        )
    if not lines:
        lines.append(
            "Closing the remaining gaps will make growth more durable and less dependent on perfect conditions."
        )
    return lines[:4]


def _behavior_gap_labels(flags: dict[str, bool], scores: dict[str, float]) -> list[str]:
    labels: list[str] = []
    mapping = [
        ("EMOTIONAL_INVEST", "emotional investing decisions"),
        ("OVERSPEND", "lifestyle overspending"),
        ("LOW_DISCIPLINE", "weak savings discipline"),
        ("POOR_PLANNING", "poor financial planning"),
        ("DEBT_HABIT", "recurring debt habits"),
        ("CRITICAL_STABILITY", "thin cash reserves"),
        ("LOW_SAVER", "inconsistent saving"),
        ("RISK_MISMATCH", "risk tolerance mismatch"),
    ]
    for key, label in mapping:
        if flags.get(key):
            labels.append(label)
    for cat, _score in _ranked(scores)[:2]:
        labels.append(PRIMARY_GAP_LABELS.get(cat, cat.lower()))
    # de-dupe preserve order
    seen = set()
    out = []
    for item in labels:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[:2] or ["incomplete systems", "inconsistent follow-through"]


def _mistakes_for_profile(
    scores: dict[str, float],
    answers: dict[str, Any],
    flags: dict[str, bool],
    dependents: str,
) -> list[tuple[str, str]]:
    mistakes: list[tuple[str, str]] = []
    investing = float(scores.get("Investing Readiness", 0))
    debt = float(scores.get("Debt Position", 100))
    savings = float(scores.get("Savings Behavior", 100))
    behavior = float(scores.get("Financial Behavior", 100))
    protection = float(scores.get("Financial Protection", 100))
    tax = float(scores.get("Tax Awareness", 100))
    has_dependents = str(dependents).strip().lower() not in {"", "0", "none", "no", "n/a"}

    if flags.get("CRITICAL_STABILITY"):
        mistakes.append(
            (
                "Investing Before the Foundation Is Stable",
                "Many people begin investing while carrying insufficient emergency reserves. "
                "The first market drop forces a sale at exactly the wrong moment.",
            )
        )
    if flags.get("EMOTIONAL_INVEST") or behavior < 50 or _ans_int(answers, "q19", 2) == 0:
        mistakes.append(
            (
                "Reacting to Market Noise",
                "Checking portfolios daily and reacting to headlines is one of the most "
                "reliable ways to underperform a simple consistent strategy.",
            )
        )
    if flags.get("LOW_SAVER") or savings < 55:
        mistakes.append(
            (
                "Waiting for the Right Amount to Start Saving",
                "The habit matters more than the amount. Starting with any consistent "
                "number beats waiting until you can save more.",
            )
        )
    if debt < 55 and investing > 0:
        mistakes.append(
            (
                "Investing While High-Interest Debt Compounds",
                "Debt above 10% interest offers a guaranteed return when paid down that "
                "is very difficult to match through investment returns after risk is factored.",
            )
        )
    if protection < 55 and has_dependents:
        mistakes.append(
            (
                "Underestimating Protection Needs",
                "Many Muslims avoid conventional insurance or Takaful equivalents without "
                "exploring halal alternatives. A protection gap with dependents creates "
                "significant family financial risk. Takaful and Shariah-compliant protection "
                "options exist and should be explored through a qualified Islamic finance advisor.",
            )
        )
    if tax < 55:
        mistakes.append(
            (
                "Leaving Tax Advantages Unused",
                "Tax-advantaged accounts offer guaranteed returns in the form of tax "
                "savings. Not using available accounts is one of the most common and "
                "costly oversights at every income level.",
            )
        )
    if flags.get("RISK_MISMATCH"):
        mistakes.append(
            (
                "Overestimating Actual Risk Tolerance",
                "Stated risk tolerance often differs from behavioral risk tolerance. "
                "Your responses suggest a gap between how much risk you think you can "
                "handle and how you would likely react under real pressure.",
            )
        )

    fallbacks = [
        (
            "Treating Readiness as a One-Time Decision",
            "Financial readiness is built through repeated systems. A strong month "
            "followed by neglected habits usually resets progress.",
        ),
        (
            "Skipping Written Goals",
            "Without dates and dollar targets, monthly decisions drift toward comfort "
            "spending instead of structured growth.",
        ),
        (
            "Ignoring Small Structural Leaks",
            "Unused automation, unreviewed subscriptions, and unclear debt priorities "
            "quietly erase gains that investing alone cannot replace.",
        ),
    ]
    seen = {title for title, _ in mistakes}
    for title, detail in fallbacks:
        if len(mistakes) >= 5:
            break
        if title in seen:
            continue
        mistakes.append((title, detail))
        seen.add(title)
    return mistakes[:5]


def _back_cover(styles: dict[str, ParagraphStyle]) -> list[Any]:
    top = [
        Spacer(1, 18),
        _logo_flowable(1.35 * inch),
        Spacer(1, 10),
        Paragraph("InvestReady", styles["white_title"]),
        HRFlowable(width=100, thickness=2, color=TEAL, spaceBefore=2, spaceAfter=10),
        Paragraph(
            "stocks.irizq.com",
            ParagraphStyle(
                "IRCoverLink",
                parent=styles["white_center"],
                textColor=TEAL,
                fontSize=11,
            ),
        ),
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


def _safe_extend(story: list[Any], builder: Any, label: str) -> None:
    try:
        items = builder()
        if items:
            story.extend(items)
    except Exception as exc:  # noqa: BLE001
        styles = _styles()
        story.append(
            Paragraph(
                f"[{label} temporarily unavailable]",
                styles["intro_muted"],
            )
        )
        story.append(Paragraph(f"Detail: {type(exc).__name__}", styles["muted"]))


def _page_cover(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    email: str,
    report_id: str,
    overall: int,
    grade: str,
    stage: str,
) -> list[Any]:
    story: list[Any] = []
    for item in _bismillah_flowables(styles):
        story.append(item)
    story.append(Spacer(1, 12))
    story.append(_logo_flowable(1.15 * inch))
    story.append(Spacer(1, 16))
    story.extend(_header_band("InvestReady Financial Readiness Report"))
    story.append(Paragraph("Confidential Financial Summary", styles["teal_italic"]))
    story.append(Paragraph(f"Prepared for <b>{name}</b>", styles["center"]))
    story.append(
        Paragraph(
            "This report was generated based on your personal responses and is intended "
            "solely for your private use.",
            styles["privacy"],
        )
    )
    story.append(Paragraph(f"Report ID: {report_id}", styles["report_id"]))
    meta_bits = []
    if email:
        meta_bits.append(email)
    meta_bits.append(datetime.utcnow().strftime("Generated %B %d, %Y"))
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), styles["muted"]))
    story.append(Spacer(1, 10))
    story.extend(_score_info_band(overall, grade, stage))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_executive_summary(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    overall: int,
    stage: str,
    scores: dict[str, float],
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Executive Summary"))

    strengths = [(c, s) for c, s in _ranked(scores, reverse=True) if s >= 70]
    concerns = _ranked(scores)[:3]
    snapshot = _snapshot_phrase(overall)
    story.append(Paragraph("Your Financial Snapshot", styles["section_h"]))
    story.append(
        Paragraph(
            f"Based on your responses, {name}, your financial position reflects {snapshot}. "
            f"The assessment identified {len(strengths)} area(s) of strength and "
            f"{len(concerns)} priority concern(s) that warrant attention before focusing on growth.",
            styles["body"],
        )
    )

    story.append(Paragraph("Key Strengths", styles["section_h"]))
    if strengths:
        for cat, _score in strengths[:4]:
            obs = STRENGTH_OBS.get(cat, "solid habits that support long-term readiness")
            story.append(
                Paragraph(
                    f"<font color='#1ec8b8'>&#10003;</font> Based on your responses, your "
                    f"{cat} reflects {obs}.",
                    styles["item_small"],
                )
            )
    else:
        story.append(
            Paragraph(
                "Your assessment did not identify areas of established strength yet. The "
                "focus areas below represent where to build your foundation first.",
                styles["body_left"],
            )
        )

    story.append(Spacer(1, 6))
    story.append(Paragraph("Key Concerns", styles["section_h"]))
    for cat, score in concerns:
        obs = CONCERN_OBS.get(
            cat,
            f"Your responses suggest {cat} ({int(round(score))}/100) needs focused attention.",
        )
        story.append(
            Paragraph(
                f"<font color='#f59e0b'>!</font> <b>{cat}</b> - {obs}",
                styles["item_small"],
            )
        )

    story.append(Spacer(1, 8))
    story.append(Paragraph("Bottom Line", styles["section_h"]))
    bottom = STAGE_BOTTOM_LINE.get(
        stage,
        "Your next gains will come from closing the highest-impact gaps identified in this report.",
    )
    story.append(Paragraph(f"In summary, {bottom}", styles["body"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_risks(
    styles: dict[str, ParagraphStyle],
    risks: list[dict[str, Any]],
) -> list[Any]:
    story: list[Any] = []
    risk_title = ParagraphStyle(
        "IRRiskTitle",
        parent=styles["h2"],
        fontSize=11,
        spaceBefore=3,
        spaceAfter=2,
    )
    risk_body = ParagraphStyle(
        "IRRiskBody",
        parent=styles["body"],
        fontSize=9,
        leading=11,
        spaceAfter=2,
    )
    risk_bullet = ParagraphStyle(
        "IRRiskBullet",
        parent=styles["body_small"],
        fontSize=8,
        leading=10,
        spaceAfter=0,
    )
    cost_h = ParagraphStyle(
        "IRCostHDense",
        parent=styles["cost_h"],
        spaceBefore=2,
        spaceAfter=1,
    )
    fix_h = ParagraphStyle(
        "IRFixHDense",
        parent=styles["fix_h"],
        spaceBefore=2,
        spaceAfter=1,
    )
    story.extend(_header_band("The 3 Financial Risks That Could Cost You The Most"))
    story.append(
        Paragraph(
            "These risks are identified directly from your assessment responses - not generic advice.",
            styles["intro_muted"],
        )
    )
    for idx, risk in enumerate(risks, start=1):
        story.append(Paragraph(f"Risk {idx} - {risk['name']}", risk_title))
        story.append(Paragraph(risk["means"], risk_body))
        if risk.get("takaful"):
            story.append(
                _teal_note(
                    "Many Muslims prefer Takaful or Shariah-compliant protection over "
                    "conventional insurance. This risk concerns your protection level - not "
                    "a specific product. Consult a qualified Islamic finance advisor for "
                    "halal-compliant options."
                )
            )
        story.append(Paragraph("What This Could Cost You", cost_h))
        for item in risk["costs"]:
            story.append(Paragraph(f"- {item}", risk_bullet))
        story.append(Paragraph("The Fix", fix_h))
        for item in risk["fixes"]:
            story.append(Paragraph(f"- {item}", risk_bullet))
        story.append(Spacer(1, 2))
    story.append(PageBreak())
    return story


def _page_score_breakdown(
    styles: dict[str, ParagraphStyle],
    scores: dict[str, float],
    overall: int,
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Your Financial Readiness Breakdown"))
    story.append(Spacer(1, 2))
    for cat, score in scores.items():
        story.append(ScoreBarRow(cat, float(score)))
        story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.8, color=NAVY, spaceBefore=2, spaceAfter=8))
    story.append(ScoreBarRow("Overall Score", float(overall), overall=True))
    if scores:
        highest = max(scores.items(), key=lambda item: item[1])
        lowest = min(scores.items(), key=lambda item: item[1])
        story.append(
            Paragraph(
                f"Your strongest area is {highest[0]}. Your biggest gap is {lowest[0]}.",
                styles["interp"],
            )
        )
        story.append(
            Paragraph(
                "This report focuses on the gaps most likely to impact your financial trajectory.",
                styles["interp"],
            )
        )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_real_life(
    styles: dict[str, ParagraphStyle],
    scores: dict[str, float],
    flags: dict[str, bool],
    answers: dict[str, Any] | None = None,
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("What This Means in Real Life"))
    story.append(Paragraph("If Your Current Pattern Continues", styles["path_h_navy"]))
    for line in _current_path_lines(scores, flags, answers):
        story.append(Paragraph(line, styles["body"]))
    story.append(Paragraph("If You Address These Gaps", styles["path_h_teal"]))
    for line in _improved_path_lines(scores, flags):
        story.append(Paragraph(line, styles["body"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_action_plan(
    styles: dict[str, ParagraphStyle],
    actions: dict[str, list[str]],
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Your Personalized Action Plan"))
    story.append(
        Paragraph(
            "These actions are prioritized based directly on your assessment results.",
            styles["intro_muted"],
        )
    )
    story.append(
        _callout(
            "DO THIS FIRST - 0 to 7 Days",
            "<br/>".join(f"- {item}" for item in actions["days7"]),
            RED,
        )
    )
    story.append(
        _callout(
            "NEXT - 30 Days",
            "<br/>".join(f"- {item}" for item in actions["days30"]),
            AMBER,
        )
    )
    story.append(PageBreak())
    story.extend(_header_band("Your Personalized Action Plan (continued)"))
    story.append(
        _callout(
            "THEN - 90 Days",
            "<br/>".join(f"- {item}" for item in actions["days90"]),
            TEAL,
        )
    )
    story.append(
        Paragraph(
            "Complete the 0-7 day items before expanding scope. Structure beats motivation "
            "when pressure arrives.",
            styles["body"],
        )
    )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_insight(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    stage: str,
    scores: dict[str, float],
    flags: dict[str, bool],
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Personalized Insight"))
    lowest = _ranked(scores)[0][0] if scores else "Cash Stability"
    primary = PRIMARY_GAP_LABELS.get(lowest, lowest.lower())
    story.append(
        Paragraph(
            f"{name}, based on your complete profile, the single biggest opportunity "
            f"available to you right now is not higher investment returns - it is {primary}.",
            styles["body"],
        )
    )
    gap_labels = _behavior_gap_labels(flags, scores)
    joined = " and ".join(gap_labels)
    story.append(
        Paragraph(
            f"Most people at your financial stage lose progress not due to poor investment "
            f"choices, but due to {joined}. These are fixable with the right structure in place.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            STAGE_INSIGHT.get(
                stage,
                "Targeted improvements to your weakest areas will shift your trajectory "
                "meaningfully within 6 to 12 months.",
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "The report you are holding is a starting point, not a verdict. Financial "
            "readiness is built through consistent action over time - not a single decision. "
            "The action plan on the previous pages is designed to give you the clearest "
            "starting point possible.",
            styles["body"],
        )
    )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_mistakes(
    styles: dict[str, ParagraphStyle],
    mistakes: list[tuple[str, str]],
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Mistakes People With Your Profile Often Make"))
    story.append(
        Paragraph(
            "These patterns are common at your financial stage. Awareness is the first "
            "step to avoiding them.",
            styles["intro_muted"],
        )
    )
    for title, detail in mistakes:
        story.append(_callout(title, detail, AMBER))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _page_verdict(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    overall: int,
    grade: str,
    stage: str,
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("Your Financial Readiness Verdict"))
    story.extend(_score_info_band(overall, grade, stage))
    verdict = STAGE_VERDICT.get(
        stage,
        "Closing the identified gaps will strengthen your financial position.",
    )
    story.append(
        Paragraph(
            f"{name}, your Financial Readiness Score of {overall}/100 places you in the "
            f"{stage} stage. {verdict}",
            styles["body"],
        )
    )
    story.append(Paragraph("Primary Recommendation", styles["rec_h"]))
    story.append(
        Paragraph(
            STAGE_RECOMMENDATION.get(
                stage,
                "Close your top identified gaps before scaling investment contributions.",
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "May Allah bless your wealth, purify your earnings, and grant you barakah in "
            "your financial journey. Ameen.",
            styles["dua"],
        )
    )
    story.append(Paragraph("Continue your journey:", styles["center"]))
    story.append(Paragraph("iRizq.com &nbsp;|&nbsp; stocks.irizq.com", styles["teal"]))
    story.append(Paragraph(FINAL_DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def generate_investready_pdf(payload: dict[str, Any]) -> bytes:
    """Generate the InvestReady PDF and return raw bytes."""
    styles = _styles()
    name = str(payload.get("name") or "Investor").strip() or "Investor"
    email = str(payload.get("email") or "").strip()
    overall = int(round(float(payload.get("overall_score") or 0)))
    grade = str(payload.get("letter_grade") or "C")
    stage = str(
        payload.get("financial_stage")
        or payload.get("investor_profile")
        or "Growth Ready"
    ).strip() or "Growth Ready"

    scores = _normalize_scores(payload.get("category_scores") or {})
    answers = {str(k): v for k, v in (payload.get("answers") or {}).items()}
    flags = _flag_set(payload, answers)

    profile_age = str(payload.get("profile_age") or "").strip()
    profile_income = str(payload.get("profile_income") or "").strip()
    profile_dependents = str(payload.get("profile_dependents") or "").strip()
    if not profile_age and "q1" in answers:
        profile_age = str(answers.get("q1"))
    if not profile_income and "q2" in answers:
        profile_income = str(answers.get("q2"))
    if not profile_dependents and "q3" in answers:
        profile_dependents = str(answers.get("q3"))

    # Keep profile fields referenced so payload contracts remain stable.
    _ = (profile_age, profile_income)

    report_id = _make_report_id()
    risks = _build_risks(scores, answers, flags)
    actions = _action_plan(scores, answers, flags)
    mistakes = _mistakes_for_profile(scores, answers, flags, profile_dependents)

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

    _safe_extend(
        story,
        lambda: _page_cover(
            styles,
            name=name,
            email=email,
            report_id=report_id,
            overall=overall,
            grade=grade,
            stage=stage,
        ),
        "Cover",
    )
    _safe_extend(
        story,
        lambda: _page_executive_summary(
            styles,
            name=name,
            overall=overall,
            stage=stage,
            scores=scores,
        ),
        "Executive Summary",
    )
    _safe_extend(story, lambda: _page_risks(styles, risks), "Financial Risks")
    _safe_extend(
        story,
        lambda: _page_score_breakdown(styles, scores, overall),
        "Score Breakdown",
    )
    _safe_extend(
        story,
        lambda: _page_real_life(styles, scores, flags, answers),
        "What This Means",
    )
    _safe_extend(story, lambda: _page_action_plan(styles, actions), "Action Plan")
    _safe_extend(
        story,
        lambda: _page_insight(
            styles,
            name=name,
            stage=stage,
            scores=scores,
            flags=flags,
        ),
        "Personalized Insight",
    )
    _safe_extend(story, lambda: _page_mistakes(styles, mistakes), "Common Mistakes")
    _safe_extend(
        story,
        lambda: _page_verdict(
            styles,
            name=name,
            overall=overall,
            grade=grade,
            stage=stage,
        ),
        "Final Verdict",
    )
    _safe_extend(story, lambda: _back_cover(styles), "Back Cover")

    def _canvas_maker(*args: Any, **kwargs: Any) -> InvestReadyCanvas:
        return InvestReadyCanvas(*args, prepared_for=name, **kwargs)

    doc.build(story, canvasmaker=_canvas_maker)
    return buffer.getvalue()
