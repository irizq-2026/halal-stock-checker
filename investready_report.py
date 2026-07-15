"""InvestReady premium PDF report generator (reportlab)."""

from __future__ import annotations

import io
import os
import random
import re
import string
import urllib.request
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
    "Profile: Foundation": (
        "Your priority is building the financial foundation before focusing on growth."
    ),
    "Profile: Stability": (
        "You are working toward stability. Consistent habits will accelerate progress."
    ),
    "Profile: Pre-Growth": (
        "Your foundation is developing. You are approaching readiness for focused growth."
    ),
    "Profile: Growth": (
        "You have a strong foundation and are positioned to build wealth systematically."
    ),
    "Profile: Advanced": (
        "Your fundamentals are strong. Focus on optimizing and scaling what is working."
    ),
}

STAGE_BOTTOM_LINE = {
    "Profile: Foundation": (
        "Your finances are in an early-stage build phase. The priority is stability and "
        "habit formation, not investment scaling."
    ),
    "Profile: Stability": (
        "You are in a stability-building phase. Addressing the gaps identified will create "
        "the platform for more confident financial growth."
    ),
    "Profile: Pre-Growth": (
        "You are approaching a growth phase but have key gaps to close first. Addressing "
        "these now will make growth more sustainable."
    ),
    "Profile: Growth": (
        "You are in an active wealth-building phase. Fine-tuning the gaps identified will "
        "improve your trajectory meaningfully."
    ),
    "Profile: Advanced": (
        "You are in an optimization phase. The opportunities identified here are "
        "refinements to an already strong foundation."
    ),
}

STAGE_INSIGHT = {
    "Profile: Foundation": (
        "The good news is that at your stage, the actions that matter most are simple and "
        "within immediate reach. Building the foundation now creates a platform that makes "
        "everything else easier."
    ),
    "Profile: Stability": (
        "You have already built some structure. The opportunity is to close the remaining "
        "gaps before they become more expensive to fix. Progress from here accelerates as "
        "each piece of the foundation locks in."
    ),
    "Profile: Pre-Growth": (
        "You are closer to a strong financial position than your score may suggest. "
        "Targeted improvements to your weakest areas will shift your trajectory "
        "meaningfully within 6 to 12 months."
    ),
    "Profile: Growth": (
        "Your foundation is solid. The focus from here is refinement and optimization "
        "rather than reconstruction. Small improvements to high-impact areas will "
        "compound into significant gains."
    ),
    "Profile: Advanced": (
        "Your financial fundamentals are strong. The opportunities identified here are "
        "precision improvements that will protect and accelerate what you have already built."
    ),
}

STAGE_VERDICT = {
    "Profile: Foundation": (
        "Your priority is building the financial habits and buffers that make everything "
        "else possible. Growth should come after stability."
    ),
    "Profile: Stability": (
        "You are making progress on your foundation. The gaps identified are addressable "
        "with consistent focused effort over the next 3 to 6 months."
    ),
    "Profile: Pre-Growth": (
        "Your foundation is developing well. Closing the identified gaps will position "
        "you for more confident financial growth."
    ),
    "Profile: Growth": (
        "You are positioned to build wealth systematically. The improvements identified "
        "will strengthen an already solid foundation."
    ),
    "Profile: Advanced": (
        "Your financial fundamentals are strong. The opportunities here are precision "
        "improvements to an already well-structured position."
    ),
}

STAGE_RECOMMENDATION = {
    "Profile: Foundation": (
        "Focus entirely on stability before any growth or investment scaling."
    ),
    "Profile: Stability": (
        "Build your emergency buffer and reduce debt before increasing investment activity."
    ),
    "Profile: Pre-Growth": (
        "Close your top 3 identified gaps before scaling investment contributions."
    ),
    "Profile: Growth": (
        "Optimize your existing structure and automate the remaining manual decisions."
    ),
    "Profile: Advanced": (
        "Refine and protect what is working. Focus on the smallest high-impact "
        "improvements identified."
    ),
}

PRIMARY_GAP_LABELS = {
    "Cash Stability": "building financial stability",
    "Debt Position": "eliminating high-interest debt drag",
    "Savings Behavior": "creating consistent savings habits",
    "Investing Readiness": "establishing a halal investing foundation",
    "Financial Behavior": "building disciplined decision-making under stress",
    "Retirement Planning": "securing your long-term planning",
    "Risk Alignment": "aligning stated risk tolerance with real behavior",
    "Tax Awareness": "capturing available tax advantages",
    "Financial Protection": "closing financial protection gaps",
}

INSIGHT_PROBLEM_LABELS = {
    "Cash Stability": (
        "insufficient emergency buffers that force reactive financial decisions"
    ),
    "Debt Position": (
        "high-interest debt quietly competing with savings and investment capacity"
    ),
    "Savings Behavior": (
        "irregular savings habits that fail to build meaningful momentum"
    ),
    "Investing Readiness": (
        "delayed or inconsistent investing that allows inflation to quietly erode purchasing power"
    ),
    "Financial Behavior": (
        "emotional or inconsistent financial decision-making"
    ),
    "Retirement Planning": (
        "deferred retirement planning that costs more to correct with each passing year"
    ),
    "Tax Awareness": (
        "underused tax-advantaged accounts leaving guaranteed returns unclaimed"
    ),
    "Financial Protection": (
        "unaddressed financial protection gaps that create binary risk for the family"
    ),
    "Risk Alignment": (
        "a gap between stated and behavioral risk tolerance that affects decisions under market pressure"
    ),
}

STAGE_ALIASES = {
    "Foundation Builder": "Profile: Foundation",
    "Stability Seeker": "Profile: Stability",
    "Growth Ready": "Profile: Pre-Growth",
    "Wealth Builder": "Profile: Growth",
    "Optimizer": "Profile: Advanced",
    "Stage 1: Foundation Building": "Profile: Foundation",
    "Stage 2: Stability Building": "Profile: Stability",
    "Stage 3: Growth Preparation": "Profile: Pre-Growth",
    "Stage 4: Wealth Building": "Profile: Growth",
    "Stage 5: Optimization": "Profile: Advanced",
    "Profile: Foundation": "Profile: Foundation",
    "Profile: Stability": "Profile: Stability",
    "Profile: Pre-Growth": "Profile: Pre-Growth",
    "Profile: Growth": "Profile: Growth",
    "Profile: Advanced": "Profile: Advanced",
}

PROFILE_SHORT_NAMES = {
    "Profile: Foundation": "Foundation",
    "Profile: Stability": "Stability",
    "Profile: Pre-Growth": "Pre-Growth",
    "Profile: Growth": "Growth",
    "Profile: Advanced": "Advanced",
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


def _ensure_amiri_font() -> Path | None:
    """Download Amiri Regular into static/fonts if missing. Fail gracefully."""
    try:
        base = Path(__file__).resolve().parent
        font_path = base / "static" / "fonts" / "Amiri-Regular.ttf"
        if font_path.is_file() and font_path.stat().st_size > 1000:
            return font_path
        font_path.parent.mkdir(parents=True, exist_ok=True)
        urls = (
            "https://github.com/aliftype/amiri/raw/main/Amiri-Regular.ttf",
            "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf",
        )
        for url in urls:
            try:
                urllib.request.urlretrieve(url, str(font_path))
                if font_path.is_file() and font_path.stat().st_size > 1000:
                    return font_path
            except Exception:
                continue
    except Exception:
        return None
    return None


def _register_fonts() -> str:
    global _ARABIC_FONT, _HAS_ARABIC_FONT
    # Prefer Amiri for reliable Arabic shaping in reportlab.
    amiri = _ensure_amiri_font()
    if amiri is not None:
        try:
            pdfmetrics.registerFont(TTFont("Amiri", str(amiri)))
            _ARABIC_FONT = "Amiri"
            _HAS_ARABIC_FONT = True
            return _ARABIC_FONT
        except Exception:
            pass
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
                pdfmetrics.registerFont(TTFont("Amiri", str(path)))
                _ARABIC_FONT = "Amiri"
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

BISMILLAH_AR = "بِسْمِ اللهِ الرَّحْمٰنِ الرَّحِيْمِ"
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
            fontSize=10,
            textColor=WHITE,
            alignment=TA_CENTER,
            leading=13,
        ),
        "band_clarify": ParagraphStyle(
            "IRBandClarify",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
            leading=11,
            spaceBefore=8,
            spaceAfter=8,
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
        "toc_howto_h": ParagraphStyle(
            "IRTocHowToH",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "toc_howto_body": ParagraphStyle(
            "IRTocHowToBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=TEXT,
            leading=11,
            spaceAfter=6,
            alignment=TA_LEFT,
        ),
        "mistake_note": ParagraphStyle(
            "IRMistakeNote",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=TEAL,
            alignment=TA_LEFT,
            leading=12,
            spaceBefore=4,
            spaceAfter=2,
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
            fontSize=18,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=4,
            leading=26,
        ),
        "bismillah_en": ParagraphStyle(
            "IRBismillahEn",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=6,
            leading=12,
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


def _letter_grade(score: float) -> str:
    """Intuitive grade scale used in the app and PDF."""
    value = float(score)
    if value >= 85:
        return "A"
    if value >= 70:
        return "B"
    if value >= 55:
        return "C"
    if value >= 40:
        return "D"
    return "F"


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


def _pluralize_count(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural}"


def _clean_text(text: str) -> str:
    """Collapse whitespace and normalize hyphen variants to regular hyphens."""
    cleaned = str(text or "").replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", cleaned).strip()


def _sentence_join(prefix: str, continuation: str) -> str:
    """Join prefix + continuation with correct mid-sentence capitalization."""
    text = _clean_text(continuation)
    if not text:
        return _clean_text(prefix)
    fixed = text[0].lower() + text[1:] if text[0].isupper() else text
    return _clean_text(f"{prefix}{fixed}")


def _grade_label(score: float) -> str:
    grade = _letter_grade(score)
    labels = {
        "A": "Excellent Financial Readiness",
        "B": "Strong Foundation",
        "C": "Developing Foundation",
        "D": "Needs Attention",
        "F": "Foundation Building Required",
    }
    return labels.get(grade, "Developing Foundation")


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


def _callout(
    title: str,
    body: str,
    border_color: colors.Color = AMBER,
    note: str | None = None,
) -> KeepTogether:
    styles = _styles()
    inner = [
        Paragraph(f"<b>{title}</b>", styles["h2"]),
        Paragraph(body, styles["body_left"]),
    ]
    if note:
        inner.append(Paragraph(_clean_text(note), styles["mistake_note"]))
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


def _dense_callout(
    title: str,
    body: str,
    border_color: colors.Color = AMBER,
) -> KeepTogether:
    """Tighter callout used by the consolidated action plan page."""
    styles = _styles()
    title_style = ParagraphStyle(
        "IRDenseCalloutTitle",
        parent=styles["h2"],
        fontSize=11,
        spaceBefore=0,
        spaceAfter=3,
        leading=13,
    )
    body_style = ParagraphStyle(
        "IRDenseCalloutBody",
        parent=styles["body_left"],
        fontSize=9,
        leading=12,
        spaceAfter=0,
    )
    inner = [
        Paragraph(f"<b>{title}</b>", title_style),
        Paragraph(body, body_style),
    ]
    table = Table([[inner]], colWidths=[6.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("BOX", (0, 0), (-1, -1), 0, WHITE),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
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
        use_arabic = bool(_HAS_ARABIC_FONT and _ARABIC_FONT == "Amiri" and _ARABIC_LIBS_OK)
        bidi_text = None
        if use_arabic and arabic_reshaper and get_display:
            reshaper = arabic_reshaper.ArabicReshaper(
                configuration={
                    "delete_harakat": False,
                    "support_ligatures": True,
                }
            )
            reshaped = reshaper.reshape(BISMILLAH_AR)
            bidi_text = get_display(reshaped)
            if not bidi_text or not str(bidi_text).strip():
                raise RuntimeError("Empty Arabic reshape result")
            return [
                Paragraph(bidi_text, styles["bismillah_ar"]),
                Spacer(1, 6),
                Paragraph(BISMILLAH_EN, styles["bismillah_en"]),
            ]
    except Exception:
        pass
    return [
        Paragraph(BISMILLAH_EN_FALLBACK, styles["bismillah_translit"]),
        Spacer(1, 4),
        Paragraph(BISMILLAH_EN, styles["bismillah_en"]),
    ]


def _normalize_stage(stage: str) -> str:
    value = str(stage or "").strip()
    if value in STAGE_ALIASES:
        return STAGE_ALIASES[value]
    for alias, canonical in STAGE_ALIASES.items():
        if value.lower() == alias.lower() or value.lower() == canonical.lower():
            return canonical
    return "Profile: Pre-Growth"


def _profile_short(stage: str) -> str:
    canonical = _normalize_stage(stage)
    return PROFILE_SHORT_NAMES.get(canonical, canonical.replace("Profile: ", ""))


def _peer_percentile(overall: int) -> str:
    score = int(overall)
    if score >= 85:
        return "top 10%"
    if score >= 70:
        return "top 25%"
    if score >= 55:
        return "top 50%"
    if score >= 40:
        return "bottom 40%"
    if score >= 25:
        return "bottom 25%"
    return "bottom 10%"


def _grade_stage_clarify() -> list[Any]:
    styles = _styles()
    clarify = ParagraphStyle(
        "IRBandClarifyTight",
        parent=styles["band_clarify"],
        spaceBefore=6,
        spaceAfter=4,
    )
    return [
        Spacer(1, 4),
        Paragraph(
            "Your grade measures overall readiness. Your profile reflects your financial "
            "behavior and habits pattern - independent of your score.",
            clarify,
        ),
    ]


def _make_report_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase, k=4))
    return f"IR-{datetime.utcnow().strftime('%Y%m%d')}-{suffix}"


class ScoreInfoBand(Flowable):
    """Navy score band with thin vertical separators between columns."""

    def __init__(self, overall: int, grade: str, stage: str, width: float = 7.0 * inch, height: float = 72):
        super().__init__()
        self.overall = overall
        self.grade = grade
        self.stage = stage
        self.width = width
        self.height = height

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(NAVY)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)

        # Thin vertical separators between the three columns.
        sep_color = colors.Color(1, 1, 1, alpha=0.15)
        sep_h = self.height * 0.60
        sep_y = (self.height - sep_h) / 2.0
        for frac in (1.0 / 3.0, 2.0 / 3.0):
            x = self.width * frac
            c.setFillColor(sep_color)
            c.rect(x - 0.25, sep_y, 0.5, sep_h, fill=1, stroke=0)

        col_w = self.width / 3.0
        centers = [col_w * 0.5, col_w * 1.5, col_w * 2.5]
        labels = ["OVERALL SCORE", "GRADE", "PROFILE"]
        values = [f"{self.overall} / 100", str(self.grade), str(self.stage)]
        value_sizes = [22, 22, 10 if len(self.stage) > 18 else 12]

        for cx, label, value, vsize in zip(centers, labels, values, value_sizes):
            c.setFillColor(TEAL)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(cx, self.height - 22, label)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", vsize)
            # Wrap long stage names onto two lines if needed.
            if label == "PROFILE" and ":" in value:
                left, right = value.split(":", 1)
                c.drawCentredString(cx, self.height / 2 + 2, f"{left}:")
                c.setFont("Helvetica-Bold", max(9, vsize - 1))
                c.drawCentredString(cx, self.height / 2 - 12, right.strip())
            else:
                c.drawCentredString(cx, self.height / 2 - 6, value)


def _score_info_band(overall: int, grade: str, stage: str) -> list[Any]:
    return [
        ScoreInfoBand(overall, grade, stage),
        HRFlowable(width="100%", thickness=2, color=TEAL, spaceBefore=0, spaceAfter=0),
        *_grade_stage_clarify(),
        Spacer(1, 4),
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

        # Always show a visible stub so zero never looks like a rendering error.
        if self.score <= 0:
            fill_w = 5
            fill_color = RED
        else:
            fill_w = (self.score / 100.0) * bar_w
            if self.score <= 10:
                fill_w = max(fill_w, 12)
        c.setFillColor(fill_color)
        c.rect(bar_x, bar_y, fill_w, bar_h, fill=1, stroke=0)

        score_x = bar_x + bar_w + 10
        c.setFillColor(fill_color)
        c.setFont("Helvetica-Bold", 10)
        score_text = f"{int(round(self.score))}"
        c.drawString(score_x, 5, score_text)

        cursor_x = score_x + c.stringWidth(score_text, "Helvetica-Bold", 10) + 4
        if self.score <= 0 and not self.overall:
            c.setFillColor(MUTED)
            c.setFont("Helvetica-Oblique", 8)
            note = "(not yet started)"
            c.drawString(cursor_x, 5, note)
            cursor_x += c.stringWidth(note, "Helvetica-Oblique", 8) + 6
        else:
            cursor_x = score_x + 36

        c.setFont("Helvetica", 9)
        c.setFillColor(fill_color)
        c.drawString(cursor_x, 5, status)


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
            ("chart", "9 Categories", "Assessed"),
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

    if category == "Risk Alignment":
        return {
            "name": "Risk Alignment Risk",
            "means": (
                "Based on your responses, there may be a gap between the risk you say "
                "you can handle and how you would likely react under real market pressure. "
                "That mismatch is one of the most common ways investors abandon otherwise "
                "sound halal strategies."
            ),
            "costs": [
                "Selling during a drawdown after previously claiming high risk tolerance",
                "Taking more risk than your behavior can sustain",
                "Strategy changes that interrupt long-term compounding",
            ],
            "fixes": [
                "Write down your maximum acceptable drawdown before the next market move",
                "Match portfolio risk to the action you would take in a 20% drop",
                "Review risk rules once a quarter when markets are calm",
            ],
            "takaful": False,
        }

    if category == "Financial Behavior":
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


def _opportunity_cost_risk() -> dict[str, Any]:
    return {
        "name": "Opportunity Cost Risk",
        "category": "General",
        "score": 0.0,
        "means": (
            "Based on your responses, there may be areas where inaction is itself a "
            "financial risk. Delayed decisions on saving, investing, or protection carry "
            "a compounding cost that is easy to underestimate."
        ),
        "costs": [
            "Lost compounding years that cannot be recovered later",
            "Inflation quietly reducing the purchasing power of idle cash",
            "Protection and savings gaps that become more expensive to close over time",
        ],
        "fixes": [
            "Choose one delayed decision from this report and complete it this week",
            "Automate one savings or investing transfer so progress does not depend on motivation",
            "Reassess in 90 days and measure whether the gap has narrowed",
        ],
        "takaful": False,
    }


def _build_risks(
    scores: dict[str, float],
    answers: dict[str, Any],
    flags: dict[str, bool],
) -> list[dict[str, Any]]:
    """Build exactly 3 risks from unique categories/names."""
    ranked = _ranked(scores)
    risks: list[dict[str, Any]] = []
    used_names: set[str] = set()
    used_categories: set[str] = set()

    # If RISK_MISMATCH is set, prioritize Risk Alignment once.
    if flags.get("RISK_MISMATCH"):
        score = float(scores.get("Risk Alignment", 50))
        pack = _risk_pack(
            "Risk Alignment",
            score,
            answers=answers,
            flags=flags,
            scores=scores,
        )
        pack["category"] = "Risk Alignment"
        pack["score"] = score
        risks.append(pack)
        used_names.add(pack["name"])
        used_categories.add("Risk Alignment")
        # Do not also consume Financial Behavior as a second behavioral slot.
        used_categories.add("Financial Behavior")

    for cat, score in ranked:
        if len(risks) >= 3:
            break
        if cat in used_categories:
            continue
        # If Risk Alignment already used, skip Financial Behavior (and vice versa name clash).
        if cat == "Financial Behavior" and "Risk Alignment Risk" in used_names:
            continue
        if cat == "Risk Alignment" and "Behavioral Risk" in used_names:
            continue
        pack = _risk_pack(cat, score, answers=answers, flags=flags, scores=scores)
        name = str(pack.get("name") or "")
        if not name or name in used_names:
            continue
        pack["category"] = cat
        pack["score"] = score
        risks.append(pack)
        used_names.add(name)
        used_categories.add(cat)

    while len(risks) < 3:
        filler = _opportunity_cost_risk()
        if filler["name"] in used_names:
            filler["name"] = f"Opportunity Cost Risk {len(risks) + 1}"
        risks.append(filler)
        used_names.add(filler["name"])

    # Final uniqueness verification.
    final: list[dict[str, Any]] = []
    seen: set[str] = set()
    for risk in risks:
        name = str(risk.get("name") or "")
        if name in seen:
            continue
        seen.add(name)
        final.append(risk)
    while len(final) < 3:
        final.append(_opportunity_cost_risk())
    assert len({r["name"] for r in final[:3]}) == 3
    return final[:3]


def _action_core(text: str) -> str:
    """Normalize an action to a short core key for cross-section deduplication."""
    cleaned = _clean_text(text).lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Collapse near-duplicates around the same core instruction.
    if "investment rule" in cleaned or "rule set" in cleaned or "no panic rule" in cleaned:
        return "write investment rules"
    if "list every debt" in cleaned:
        return "list every debt"
    if "emergency fund" in cleaned and ("transfer" in cleaned or "automatic" in cleaned or "open" in cleaned):
        return "emergency fund transfer"
    if "retake" in cleaned or "reassess your financial readiness" in cleaned:
        return "retake assessment"
    if "takaful" in cleaned or "shariah compliant protection" in cleaned:
        return "research protection options"
    if "stocks.irizq.com" in cleaned or "shariah compliance" in cleaned:
        return "screen shariah compliance"
    return cleaned[:56]


def _pick_unique_actions(candidates: list[str], used: set[str], limit: int = 3) -> list[str]:
    picked: list[str] = []
    for action in candidates:
        text = _clean_text(action)
        core = _action_core(text)
        if not text or core in used:
            continue
        picked.append(text)
        used.add(core)
        if len(picked) >= limit:
            break
    return picked


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

    days7_candidates: list[str] = []
    if flags.get("CRITICAL_STABILITY") or stability < 50:
        days7_candidates.append(
            "Calculate your exact monthly expenses and set an emergency fund target of "
            "3 months as your first milestone."
        )
    if debt < 55 or _ans_int(answers, "q6", 4) <= 1:
        days7_candidates.append(
            "List every debt with its balance and interest rate. Identify the highest "
            "rate and commit to paying more than the minimum this month."
        )
    if flags.get("LOW_SAVER") or savings < 50:
        days7_candidates.append(
            "Set up an automatic transfer for any fixed amount on your next payday - "
            "even $50 builds the habit."
        )
    days7_candidates.append(
        "Visit stocks.irizq.com and verify the Shariah compliance of one investment "
        "you currently hold or are considering."
    )
    if flags.get("EMOTIONAL_INVEST") or behavior < 50 or flags.get("RISK_MISMATCH"):
        days7_candidates.append(
            "Write a one-page rule set for what you will buy, hold, and refuse to sell "
            "under stress."
        )
    days7_candidates.append(
        "Block 20 minutes this week to review this report and choose one habit to automate."
    )
    used: set[str] = set()
    days7 = _pick_unique_actions(days7_candidates, used, 3)
    while len(days7) < 3:
        filler = "Write down your top financial priority for this week and one action that moves it forward."
        if _action_core(filler) not in used:
            days7.append(filler)
            used.add(_action_core(filler))
        else:
            break

    days30_candidates: list[str] = []
    if investing < 50:
        days30_candidates.append(
            "Build your halal investing knowledge through structured resources rather than "
            "social media or YouTube influencers. Start with iRizq.com educational content, "
            "then consider a reputable Islamic finance course or book. Unstructured tips from "
            "online gurus are one of the leading causes of poor investment decisions for beginners."
        )
    if savings < 65:
        days30_candidates.append(
            "Increase your automated savings by any percentage - even 1% creates "
            "meaningful momentum over 12 months."
        )
    if flags.get("POOR_PLANNING") or _ans_int(answers, "q15", 4) <= 1:
        days30_candidates.append(
            "Install a simple expense tracking app and categorize your last 30 days of "
            "spending to find your biggest cash leak."
        )
    if investing < 40 and stability >= 55 and debt >= 55:
        days30_candidates.append(
            "Open a halal investment account and make your first contribution - amount "
            "matters less than starting the habit."
        )
    days30_candidates.extend(
        [
            "List every debt with its balance, minimum payment, and interest rate - then "
            "commit to paying double the minimum on the highest rate this month.",
            "Open a separate savings account specifically for your emergency fund and make "
            "the first transfer today - any amount starts the habit.",
            "Screen your top 3 current or planned investments at stocks.irizq.com to "
            "confirm their Shariah compliance status.",
            "Calculate your actual monthly savings rate from the last 3 months of bank "
            "statements and compare it to your target rate.",
            "Schedule a 30-minute financial review to assess progress on your 7-day actions.",
            "Raise one automated transfer by a small fixed amount and keep it unchanged for 30 days.",
        ]
    )
    days30 = _pick_unique_actions(days30_candidates, used, 3)

    days90_candidates: list[str] = []
    if retirement < 65:
        days90_candidates.append(
            "Open or increase contributions to a halal-compatible retirement account "
            "by at least 1% of income."
        )
    if investing > 0 and investing < 70:
        days90_candidates.append(
            "Review your portfolio for concentration risk - no single position should "
            "exceed 20% of total investments."
        )
    if tax < 65:
        days90_candidates.append(
            "Schedule a 30-minute session to review which tax-advantaged accounts you "
            "qualify for and are not using."
        )
    if protection < 65:
        days90_candidates.append(
            "Research Takaful or Shariah-compliant protection options available in your "
            "area for health and income protection."
        )
    if risk_align < 60:
        days90_candidates.append(
            "Revisit your written risk rules after one calm month and confirm they still "
            "match how you would act in a 20% drop."
        )
    days90_candidates.extend(
        [
            "Increase your retirement or long-term savings contribution by 1% of income "
            "and automate it so it does not require a monthly decision.",
            "Research at least one Takaful or Shariah-compliant protection option "
            "available in your area and compare it to your current coverage gap.",
            "Write your 3 financial goals with specific dollar targets and dates, then "
            "review them every Monday morning for the next month.",
            "Set a calendar reminder to retake the InvestReady assessment in 90 days to "
            "measure improvement across all 9 categories.",
            "Document one structural improvement completed in the last quarter and one still open.",
        ]
    )
    days90 = _pick_unique_actions(days90_candidates, used, 3)

    return {"days7": days7[:3], "days30": days30[:3], "days90": days90[:3]}


def _current_path_lines(
    scores: dict[str, float],
    flags: dict[str, bool],
    answers: dict[str, Any] | None = None,
    overall: int | None = None,
) -> list[str]:
    _ = answers or {}
    overall_score = int(overall if overall is not None else 0)
    pool = {
        "Financial Behavior": (
            "Investment decisions influenced by emotion tend to compound negatively over time. "
            "The pattern of reacting to market moves rather than following a plan typically "
            "results in buying high and selling low - the opposite of what builds wealth."
        ),
        "Debt Position": (
            "High-interest debt that remains unaddressed continues to quietly consume cash flow "
            "that could otherwise be building your halal investment base. The longer it remains, "
            "the more expensive it becomes relative to your savings rate."
        ),
        "Cash Stability": (
            "Without an adequate emergency buffer, the next financial shock - whether a job "
            "change, medical cost, or unexpected expense - will force reactive decisions rather "
            "than strategic ones. This pattern typically resets months of careful progress in a "
            "short period."
        ),
        "Savings Behavior": (
            "Inconsistent savings creates a gap between intention and outcome that widens "
            "gradually. Without automation, savings decisions compete with spending decisions "
            "every month - and spending usually wins."
        ),
        "Retirement Planning": (
            "Delayed or inconsistent retirement contributions mean compounding works at a "
            "fraction of its potential. Each year of delay requires proportionally more "
            "contribution later to reach the same outcome."
        ),
        "Tax Awareness": (
            "Unused tax-advantaged accounts represent a guaranteed return being left on the "
            "table. At any income level, this is one of the most accessible and consistently "
            "overlooked improvements available."
        ),
        "Financial Protection": (
            "Protection gaps mean that a single health or income disruption event could reverse "
            "significant financial progress. This risk grows in proportion to your dependents "
            "and financial responsibilities."
        ),
    }
    lines: list[str] = []
    used: set[str] = set()
    for cat, score in _ranked(scores):
        if score >= 70:
            continue
        text = pool.get(cat)
        if not text or cat in used:
            continue
        used.add(cat)
        lines.append(_clean_text(text))
        if len(lines) >= 3:
            break
    if flags.get("CRITICAL_STABILITY") and "Cash Stability" not in used:
        lines.insert(0, _clean_text(pool["Cash Stability"]))
        used.add("Cash Stability")
    if flags.get("LOW_SAVER") and "Savings Behavior" not in used and len(lines) < 4:
        lines.append(_clean_text(pool["Savings Behavior"]))
        used.add("Savings Behavior")
    if (
        (
            flags.get("EMOTIONAL_INVEST")
            or flags.get("OVERSPEND")
            or flags.get("LOW_DISCIPLINE")
            or flags.get("POOR_PLANNING")
            or flags.get("DEBT_HABIT")
        )
        and "Financial Behavior" not in used
        and len(lines) < 4
    ):
        lines.append(_clean_text(pool["Financial Behavior"]))
        used.add("Financial Behavior")
    if not lines:
        lines = [
            "Without tightening the weakest categories, progress will remain uneven and easier to reverse.",
            "Small gaps in buffering, saving, and discipline tend to compound quietly over time.",
            "Leaving weaker categories unaddressed usually delays compounding more than market timing ever helps.",
        ]
    while len(lines) < 3:
        lines.append(
            "Leaving weaker categories unaddressed usually delays compounding more than market timing ever helps."
        )
    lines = [_clean_text(x) for x in lines[:4]]
    lines.append(
        _clean_text(
            f"At a readiness score of {overall_score}/100, the gap between current habits and a "
            "resilient financial foundation grows with each passing month that patterns stay "
            "unchanged. The cost of inaction is not dramatic - it is gradual and quiet, which "
            "makes it more dangerous."
        )
    )
    return lines


def _improved_path_lines(
    scores: dict[str, float],
    flags: dict[str, bool],
) -> list[str]:
    pool = {
        "Financial Behavior": (
            "A written investment policy created before the next market move removes most "
            "emotional decision-making before it happens. Investors with written rules "
            "consistently outperform those without them, not because of better picks but "
            "because of fewer mistakes."
        ),
        "Debt Position": (
            "Clearing high-rate debt frees monthly cash flow and eliminates a guaranteed drag "
            "on your net worth. This cash can then compound in your favor rather than working "
            "against you."
        ),
        "Cash Stability": (
            "A 3 to 6 month emergency buffer converts financial shocks from crises into "
            "inconveniences. It also removes the pressure that causes most premature "
            "investment sales at exactly the wrong time."
        ),
        "Savings Behavior": (
            "Automating savings removes the monthly decision entirely. Consistent automated "
            "contributions - even small ones - compound more reliably than larger irregular "
            "deposits made when motivation is high."
        ),
        "Retirement Planning": (
            "Increasing retirement contributions by even 1% with each pay review creates a "
            "compounding improvement that is difficult to replicate later. The earlier this "
            "habit is in place, the more it works in your favor."
        ),
        "Tax Awareness": (
            "Using available tax-advantaged accounts creates a compounding advantage that "
            "grows tax-deferred or tax-free. This improvement requires one decision and then "
            "works automatically in the background."
        ),
        "Financial Protection": (
            "Addressing protection gaps - whether through Takaful or other Shariah-compliant "
            "arrangements - converts a binary risk into a managed one. With dependents, this "
            "improvement has an immediate positive impact on family financial security."
        ),
    }
    lines: list[str] = []
    used: set[str] = set()
    for cat, score in _ranked(scores):
        if score >= 70:
            continue
        text = pool.get(cat)
        if not text or cat in used:
            continue
        used.add(cat)
        lines.append(_clean_text(text))
        if len(lines) >= 3:
            break
    if flags.get("CRITICAL_STABILITY") and "Cash Stability" not in used:
        lines.insert(0, _clean_text(pool["Cash Stability"]))
    if not lines:
        lines = [
            "Closing the remaining gaps will make growth more durable and less dependent on perfect conditions.",
            "A clearer monthly surplus and automatic contribution habit create consistency that markets alone cannot provide.",
            "Closing foundation gaps first makes every later investment decision more resilient.",
        ]
    while len(lines) < 3:
        lines.append(
            "Closing foundation gaps first makes every later investment decision more resilient."
        )
    lines = [_clean_text(x) for x in lines[:4]]
    lines.append(
        "Financial readiness built on these foundations creates compounding momentum that "
        "grows regardless of what markets do."
    )
    return lines


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
) -> list[tuple[str, str, str]]:
    """Return (title, detail, profile_note) tuples tied to the user's scores/flags."""
    mistakes: list[tuple[str, str, str]] = []
    investing = float(scores.get("Investing Readiness", 0))
    debt = float(scores.get("Debt Position", 100))
    savings = float(scores.get("Savings Behavior", 100))
    behavior = float(scores.get("Financial Behavior", 100))
    protection = float(scores.get("Financial Protection", 100))
    tax = float(scores.get("Tax Awareness", 100))
    risk_align = float(scores.get("Risk Alignment", 100))
    stability = float(scores.get("Cash Stability", 100))
    has_dependents = str(dependents).strip().lower() not in {"", "0", "none", "no", "n/a"}

    if flags.get("CRITICAL_STABILITY"):
        mistakes.append(
            (
                "Investing Before the Foundation Is Stable",
                "Many people begin investing while carrying insufficient emergency reserves. "
                "The first market drop forces a sale at exactly the wrong moment.",
                f"Based on your responses, your cash stability score of {int(round(stability))} "
                "and thin emergency buffer flag indicate investing before reserves are solid "
                "is a live risk for your profile.",
            )
        )
    if flags.get("EMOTIONAL_INVEST") or behavior < 50 or _ans_int(answers, "q19", 2) == 0:
        mistakes.append(
            (
                "Reacting to Market Noise",
                "Checking portfolios daily and reacting to headlines is one of the most "
                "reliable ways to underperform a simple consistent strategy.",
                f"Based on your responses, your financial behavior score of {int(round(behavior))} "
                "suggests emotion-driven decisions are more likely under market pressure.",
            )
        )
    if investing < 50:
        mistakes.append(
            (
                "Learning to Invest from Social Media",
                "YouTube influencers and social media gurus optimize for engagement, not for "
                "your financial outcomes. Their advice often promotes high-risk, concentrated, or "
                "haram-adjacent strategies that perform well in bull markets and devastate beginners "
                "in corrections. The excitement of following trending stocks or crypto tips is real - "
                "the returns usually are not.",
                f"Based on your responses, your investing readiness score of {int(round(investing))} "
                "suggests structured foundational learning will create more lasting progress than "
                "tips-based approaches.",
            )
        )
    if flags.get("LOW_SAVER") or savings < 55:
        mistakes.append(
            (
                "Waiting for the Right Amount to Start Saving",
                "The habit matters more than the amount. Starting with any consistent "
                "number beats waiting until you can save more.",
                f"Based on your responses, your savings behavior score of {int(round(savings))} "
                "points to inconsistent saving as a primary drag on readiness.",
            )
        )
    if debt < 55 and investing > 0:
        mistakes.append(
            (
                "Investing While High-Interest Debt Compounds",
                "Debt above 10% interest offers a guaranteed return when paid down that "
                "is very difficult to match through investment returns after risk is factored.",
                f"Based on your responses, your debt position score of {int(round(debt))} "
                "combined with active investing readiness means high-rate debt may be competing "
                "with your investment contributions.",
            )
        )
    dep_label = str(dependents or "").strip()
    dep_lower = dep_label.lower()
    has_dep_count = dep_lower in {"1 to 2", "3 or more"} or (
        has_dependents and dep_lower not in {"none", "0", "no", "n/a", ""}
    )
    if protection < 55:
        if has_dep_count:
            prot_note = (
                f"Based on your responses, your financial protection score of {int(round(protection))} "
                "and the dependents relying on your income make protection gaps especially costly "
                "for your household."
            )
        else:
            prot_note = (
                f"Based on your responses, your financial protection score of {int(round(protection))} "
                "suggests coverage gaps that could create financial vulnerability in unexpected situations."
            )
        mistakes.append(
            (
                "Underestimating Protection Needs",
                "Many Muslims avoid conventional insurance or Takaful equivalents without "
                "exploring halal alternatives. A protection gap creates significant financial risk. "
                "Takaful and Shariah-compliant protection options exist and should be explored "
                "through a qualified Islamic finance advisor.",
                prot_note,
            )
        )
    if tax < 55:
        mistakes.append(
            (
                "Leaving Tax Advantages Unused",
                "Tax-advantaged accounts offer guaranteed returns in the form of tax "
                "savings. Not using available accounts is one of the most common and "
                "costly oversights at every income level.",
                f"Based on your responses, your tax awareness score of {int(round(tax))} "
                "suggests available tax-advantaged accounts may be underused.",
            )
        )
    if flags.get("RISK_MISMATCH"):
        mistakes.append(
            (
                "Overestimating Actual Risk Tolerance",
                "Stated risk tolerance often differs from behavioral risk tolerance. "
                "Your responses suggest a gap between how much risk you think you can "
                "handle and how you would likely react under real pressure.",
                f"Based on your responses, your risk alignment score of {int(round(risk_align))} "
                "suggests a gap between your stated tolerance and likely behavior under real "
                "market pressure.",
            )
        )

    fallbacks = [
        (
            "Treating Readiness as a One-Time Decision",
            "Financial readiness is built through repeated systems. A strong month "
            "followed by neglected habits usually resets progress.",
            "Based on your responses, uneven category scores show readiness gains will "
            "fade unless habits are reviewed on a recurring schedule.",
        ),
        (
            "Skipping Written Goals",
            "Without dates and dollar targets, monthly decisions drift toward comfort "
            "spending instead of structured growth.",
            "Based on your responses, clearer written targets would sharpen the priorities "
            "already surfaced by your lowest scoring categories.",
        ),
        (
            "Ignoring Small Structural Leaks",
            "Unused automation, unreviewed subscriptions, and unclear debt priorities "
            "quietly erase gains that investing alone cannot replace.",
            "Based on your responses, structural gaps in your weaker categories are more "
            "likely to erase progress than a single market setback.",
        ),
    ]
    seen = {title for title, _detail, _note in mistakes}
    for title, detail, note in fallbacks:
        if len(mistakes) >= 5:
            break
        if title in seen:
            continue
        mistakes.append((title, detail, note))
        seen.add(title)
    return [
        (_clean_text(t), _clean_text(d), _clean_text(n))
        for t, d, n in mistakes[:5]
    ]


class FullBleedBackCover(Flowable):
    """Full-page navy back cover drawn from page origin with no top white margin."""

    LEFT_M = 0.65 * inch
    BOTTOM_M = 0.70 * inch
    TOP_M = 0.70 * inch

    def __init__(self, styles: dict[str, ParagraphStyle]):
        super().__init__()
        self.styles = styles

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self.width = availWidth
        # Fit the current frame exactly so reportlab does not reject the flowable.
        self.height = max(1.0, float(availHeight))
        return self.width, self.height

    def _draw_para(self, c: Any, text: str, style: ParagraphStyle, x: float, y: float, width: float) -> float:
        para = Paragraph(_clean_text(text), style)
        _w, h = para.wrap(width, 800)
        para.drawOn(c, x, y - h)
        return h

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        # Draw FIRST: full-bleed navy from page (0,0) to (page_width, page_height).
        c.setFillColor(NAVY)
        c.rect(-self.LEFT_M, -self.BOTTOM_M, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

        cx = self.width / 2.0
        y = self.height - 28

        if LOGO_PATH.is_file():
            try:
                logo_w = 1.2 * inch
                c.drawImage(
                    str(LOGO_PATH),
                    cx - logo_w / 2,
                    y - logo_w,
                    width=logo_w,
                    height=logo_w,
                    mask="auto",
                    preserveAspectRatio=True,
                )
                y -= logo_w + 12
            except Exception:
                pass

        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(cx, y, "InvestReady")
        y -= 14
        c.setStrokeColor(TEAL)
        c.setLineWidth(2)
        c.line(cx - 50, y, cx + 50, y)
        y -= 18
        c.setFillColor(TEAL)
        c.setFont("Helvetica", 11)
        c.drawCentredString(cx, y, "stocks.irizq.com")
        y -= 16
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.75))
        c.setFont("Helvetica", 10)
        c.drawCentredString(cx, y, "Halal Wealth for Every Muslim")
        y -= 28

        box_w = 1.95 * inch
        box_h = 92
        gap = (self.width - 3 * box_w) / 4.0
        box_y = max(8, y - box_h)
        boxes = [
            ("check", "Shariah Screened", "AAOIFI Standards"),
            ("chart", "9 Categories", "Assessed"),
            ("doc", "Personalized", "PDF Report"),
        ]
        for idx, (kind, title, subtitle) in enumerate(boxes):
            x = gap + idx * (box_w + gap)
            FeatureIconBox(kind, title, subtitle, width=box_w, height=box_h).drawOn(c, x, box_y)
        y = box_y - 24

        quote_style = ParagraphStyle(
            "IRCoverQuoteDraw",
            parent=self.styles["teal_italic"],
            fontSize=12,
            leading=16,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=0,
        )
        dua_style = ParagraphStyle(
            "IRCoverDuaDraw",
            parent=self.styles["white_center"],
            fontSize=10,
            fontName="Helvetica-Oblique",
            leading=14,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=0,
        )
        pad_x = 18
        text_w = self.width - 2 * pad_x
        h = self._draw_para(
            c,
            "Earn halal - invest consistently - stay diversified - think long-term - let time grow your rizq.",
            quote_style,
            pad_x,
            y,
            text_w,
        )
        y -= h + 12
        h = self._draw_para(
            c,
            "May Allah bless your wealth, purify your earnings, and grant you barakah in your financial journey. Ameen.",
            dua_style,
            pad_x,
            y,
            text_w,
        )
        y -= h + 16
        h = self._draw_para(c, DISCLAIMER, self.styles["cover_disclaimer"], pad_x, y, text_w)
        y -= h + 10
        self._draw_para(
            c,
            "2026 iRizq.com. All rights reserved.",
            self.styles["cover_copy"],
            pad_x,
            y,
            text_w,
        )
        c.restoreState()


def _back_cover(styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [FullBleedBackCover(styles)]


def _page_toc(
    styles: dict[str, ParagraphStyle],
    *,
    overall: int,
    grade: str,
    stage: str,
    scores: dict[str, float],
) -> list[Any]:
    """PAGE 2 - Table of contents matching the current report structure."""
    story: list[Any] = []
    story.extend(_header_band("What's Inside Your Report"))
    toc_rows = [
        ("Executive Summary", "3"),
        ("Your 3 Financial Risks", "4"),
        ("Financial Readiness Breakdown", "5"),
        ("What This Means in Real Life", "6"),
        ("Your Personalized Action Plan", "7"),
        ("Personalized Insight", "8"),
        ("Mistakes to Avoid", "9"),
        ("Your Financial Readiness Verdict", "10"),
    ]
    rows = []
    for section, page in toc_rows:
        dots = "." * max(8, 58 - len(section))
        left = Paragraph(
            f"{section} <font color='#6b7280'>{dots}</font>",
            styles["toc_name"],
        )
        right = Paragraph(page, styles["toc_page"])
        rows.append([left, right])
    toc_table = Table(rows, colWidths=[5.9 * inch, 0.7 * inch])
    toc_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(toc_table)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Your personalized halal financial roadmap",
            styles["teal_italic"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(Paragraph("How to Use This Report", styles["toc_howto_h"]))
    for paragraph in (
        "Start with the Executive Summary on page 3 for your overall score and urgent priorities.",
        "Review Your 3 Financial Risks on page 4 and the Financial Readiness Breakdown on page 5.",
        "Work through Your Personalized Action Plan on page 7 in order: 0 to 7 days, then 30, then 90.",
        "Use Personalized Insight and Mistakes to Avoid on pages 8 and 9, then finish with the Verdict on page 10.",
    ):
        story.append(Paragraph(_clean_text(paragraph), styles["toc_howto_body"]))

    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Your Results at a Glance",
            ParagraphStyle(
                "IRGlanceTitle",
                parent=styles["toc_howto_h"],
                fontSize=11,
                spaceBefore=4,
                spaceAfter=8,
            ),
        )
    )
    strongest = max(scores.items(), key=lambda item: item[1])[0] if scores else "N/A"
    biggest = min(scores.items(), key=lambda item: item[1])[0] if scores else "N/A"
    label_style = ParagraphStyle(
        "IRGlanceLabel",
        parent=styles["body"],
        fontName="Helvetica",
        fontSize=8,
        textColor=MUTED,
        leading=11,
        alignment=TA_LEFT,
    )
    value_style = ParagraphStyle(
        "IRGlanceValue",
        parent=styles["body"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=NAVY,
        leading=14,
        alignment=TA_LEFT,
    )
    left_col = [
        Paragraph("OVERALL SCORE", label_style),
        Paragraph(f"{overall}/100", value_style),
        Spacer(1, 6),
        Paragraph("GRADE", label_style),
        Paragraph(str(grade), value_style),
        Spacer(1, 6),
        Paragraph("PROFILE", label_style),
        Paragraph(_profile_short(stage), value_style),
    ]
    right_col = [
        Paragraph("STRONGEST AREA", label_style),
        Paragraph(strongest, value_style),
        Spacer(1, 6),
        Paragraph("BIGGEST GAP", label_style),
        Paragraph(biggest, value_style),
        Spacer(1, 6),
        Paragraph("CATEGORIES", label_style),
        Paragraph("9 assessed", value_style),
    ]
    glance = Table([[left_col, right_col]], colWidths=[3.3 * inch, 3.3 * inch])
    glance.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(glance)
    story.append(PageBreak())
    return story

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


def _cover_snapshot_box(
    styles: dict[str, ParagraphStyle],
    *,
    report_id: str,
    stage: str,
    scores: dict[str, float],
) -> Table:
    label_style = ParagraphStyle(
        "IRCoverSnapLabel",
        parent=styles["body"],
        fontName="Helvetica",
        fontSize=7,
        textColor=MUTED,
        leading=9,
        alignment=TA_LEFT,
        spaceAfter=1,
    )
    value_style = ParagraphStyle(
        "IRCoverSnapValue",
        parent=styles["body"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        leading=12,
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    strongest = max(scores.items(), key=lambda item: item[1])[0] if scores else "N/A"
    weakest = min(scores.items(), key=lambda item: item[1])[0] if scores else "N/A"
    completed = datetime.utcnow().strftime("%B %d, %Y")
    left = [
        Paragraph("COMPLETED", label_style),
        Paragraph(completed, value_style),
        Paragraph("REPORT ID", label_style),
        Paragraph(report_id, value_style),
        Paragraph("SECTIONS", label_style),
        Paragraph("9 categories assessed", value_style),
    ]
    right = [
        Paragraph("STRONGEST", label_style),
        Paragraph(strongest, value_style),
        Paragraph("PRIORITY GAP", label_style),
        Paragraph(weakest, value_style),
        Paragraph("STAGE", label_style),
        Paragraph(_profile_short(stage), value_style),
    ]
    table = Table([[left, right]], colWidths=[3.4 * inch, 3.4 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _cover_contains_rows(styles: dict[str, ParagraphStyle]) -> list[Any]:
    row_style = ParagraphStyle(
        "IRCoverContains",
        parent=styles["body"],
        fontName="Helvetica",
        fontSize=9,
        textColor=NAVY,
        leading=12,
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    items = [
        "A diagnosis of your 3 biggest financial risks identified from your responses",
        "A personalized 7, 30, and 90-day action plan based on your specific gaps",
        "Educational guidance tailored to your financial stage and Muslim values",
    ]
    rows: list[Any] = []
    for item in items:
        bullet = Paragraph("<font color='#1ec8b8'>&#9679;</font>", row_style)
        body = Paragraph(_clean_text(item), row_style)
        row = Table([[bullet, body]], colWidths=[0.22 * inch, 6.5 * inch])
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        rows.append(row)
    return rows


def _page_cover(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    email: str,
    report_id: str,
    overall: int,
    grade: str,
    stage: str,
    scores: dict[str, float] | None = None,
) -> list[Any]:
    scores = scores or {}
    story: list[Any] = []
    for item in _bismillah_flowables(styles):
        story.append(item)
    story.append(Spacer(1, 4))
    story.append(_logo_flowable(0.95 * inch))
    story.append(Spacer(1, 6))
    story.extend(_header_band("InvestReady Financial Readiness Report"))
    cover_sub = ParagraphStyle(
        "IRCoverSub",
        parent=styles["teal_italic"],
        spaceBefore=2,
        spaceAfter=2,
    )
    story.append(Paragraph("Confidential Financial Summary", cover_sub))
    story.append(Paragraph(f"Prepared for <b>{name}</b>", styles["center"]))
    if email:
        story.append(Paragraph(email, styles["muted"]))
    story.append(Spacer(1, 6))
    story.extend(_score_info_band(overall, grade, stage))
    story.append(Spacer(1, 8))
    snap_h = ParagraphStyle(
        "IRCoverSnapH",
        parent=styles["section_h"],
        fontSize=11,
        spaceBefore=0,
        spaceAfter=4,
    )
    story.append(Paragraph("Your Assessment Snapshot", snap_h))
    story.append(_cover_snapshot_box(styles, report_id=report_id, stage=stage, scores=scores))
    story.append(Spacer(1, 8))
    story.append(Paragraph("What This Report Contains", snap_h))
    story.extend(_cover_contains_rows(styles))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceBefore=2, spaceAfter=6))
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
    grade = _letter_grade(overall)
    grade_label = _grade_label(overall)
    story.append(Paragraph("Your Financial Snapshot", styles["section_h"]))
    story.append(
        Paragraph(
            _clean_text(
                f"Based on your responses, {name}, your financial position reflects {snapshot}. "
                f"Your grade is {grade} - {grade_label}. "
                f"The assessment identified {_pluralize_count(len(strengths), 'area', 'areas')} of strength and "
                f"{_pluralize_count(len(concerns), 'priority concern', 'priority concerns')} that warrant "
                f"attention before focusing on growth."
            ),
            styles["body"],
        )
    )
    percentile = _peer_percentile(overall)
    peer_note_style = ParagraphStyle(
        "IRPeerNote",
        parent=styles["body"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=MUTED,
        leading=11,
        spaceBefore=4,
        spaceAfter=0,
    )
    peer_body = (
        f"Based on assessment data, a score of {overall} places you in approximately the "
        f"{percentile} of respondents who have completed this assessment."
    )
    peer_inner = [
        Paragraph(_clean_text(peer_body), styles["shariah_body"]),
        Paragraph(
            "Percentile estimates are based on aggregate scoring distributions and are "
            "provided for educational context only.",
            peer_note_style,
        ),
    ]
    peer_table = Table([[peer_inner]], colWidths=[6.8 * inch])
    peer_table.setStyle(
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
    story.append(Spacer(1, 6))
    story.append(KeepTogether([peer_table, Spacer(1, 6)]))

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
    strongest_cat, strongest_score = (
        max(scores.items(), key=lambda item: item[1]) if scores else ("Cash Stability", 0)
    )
    weakest_cat, weakest_score = (
        min(scores.items(), key=lambda item: item[1]) if scores else ("Investing Readiness", 0)
    )
    bottom = (
        f"In summary, {name}, your score of {overall}/100 places you in the "
        f"{_profile_short(stage)} profile. Your {strongest_cat} score of "
        f"{int(round(strongest_score))} shows what is possible when good habits are in place. "
        f"Closing the gap on {weakest_cat} ({int(round(weakest_score))}/100) is the single "
        f"highest-leverage improvement available to you right now."
    )
    story.append(Paragraph(_clean_text(bottom), styles["body"]))
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
    overall: int = 0,
) -> list[Any]:
    story: list[Any] = []
    story.extend(_header_band("What This Means in Real Life"))
    story.append(Paragraph("If Your Current Pattern Continues", styles["path_h_navy"]))
    for line in _current_path_lines(scores, flags, answers, overall=overall):
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
        _dense_callout(
            "DO THIS FIRST - 0 to 7 Days",
            "<br/>".join(f"- {item}" for item in actions["days7"]),
            RED,
        )
    )
    story.append(
        _dense_callout(
            "NEXT - 30 Days",
            "<br/>".join(f"- {item}" for item in actions["days30"]),
            AMBER,
        )
    )
    story.append(
        _dense_callout(
            "THEN - 90 Days",
            "<br/>".join(f"- {item}" for item in actions["days90"]),
            TEAL,
        )
    )
    reminder = _dense_callout(
        "Reminder",
        "Complete the 0 to 7 day items before expanding scope. Financial progress "
        "compounds through sequential wins, not parallel attempts. Structure beats "
        "motivation when pressure arrives.",
        TEAL,
    )
    # Prefer a single page. If content is still long, reportlab may overflow;
    # keep the reminder on the same flow without a forced continued page.
    story.append(reminder)
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
    problem = INSIGHT_PROBLEM_LABELS.get(
        lowest,
        "small structural gaps left unaddressed",
    )
    story.append(
        Paragraph(
            _clean_text(
                f"{name}, based on your complete profile, the single biggest opportunity "
                f"available to you right now is not higher investment returns - it is {primary}."
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            _clean_text(
                "Most people at your financial stage lose progress not due to poor investment "
                f"choices, but due to {problem} and the compounding effect of small structural "
                "gaps left unaddressed. These are fixable with consistent focused effort over "
                "the next 3 to 6 months."
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            _clean_text(
                STAGE_INSIGHT.get(
                    stage,
                    "Targeted improvements to your weakest areas will shift your trajectory "
                    "meaningfully within 6 to 12 months.",
                )
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            _clean_text(
                "The report you are holding is a starting point, not a verdict. Financial "
                "readiness is built through consistent action over time - not a single decision. "
                "The action plan on the previous pages is designed to give you the clearest "
                "starting point possible."
            ),
            styles["body"],
        )
    )
    investing = float(scores.get("Investing Readiness", 100))
    if investing < 50:
        story.append(Spacer(1, 6))
        story.append(
            _teal_note(
                "One specific note on investing education: your responses suggest you may be "
                "in the early stages of building investing knowledge. The most reliable path "
                "forward is structured learning - not social media gurus, YouTube channels, or "
                "tips from friends. These sources create the illusion of knowledge while building "
                "habits that destroy long-term returns. Start with foundational resources, learn "
                "the basics of halal screening at stocks.irizq.com, and build from there before "
                "scaling contributions."
            )
        )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story

def _page_mistakes(
    styles: dict[str, ParagraphStyle],
    mistakes: list[tuple[str, str, str]],
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
    dense_title = ParagraphStyle(
        "IRMistakeTitle",
        parent=styles["h2"],
        fontSize=10,
        spaceBefore=0,
        spaceAfter=2,
        leading=12,
    )
    dense_body = ParagraphStyle(
        "IRMistakeBody",
        parent=styles["body_left"],
        fontSize=9,
        leading=11,
        spaceAfter=2,
    )
    dense_note = ParagraphStyle(
        "IRMistakeNoteDense",
        parent=styles["mistake_note"],
        fontSize=8,
        leading=10,
        spaceBefore=2,
        spaceAfter=0,
    )
    for title, detail, note in mistakes:
        inner = [
            Paragraph(f"<b>{_clean_text(title)}</b>", dense_title),
            Paragraph(_clean_text(detail), dense_body),
        ]
        if note:
            inner.append(Paragraph(_clean_text(note), dense_note))
        table = Table([[inner]], colWidths=[6.8 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), SILVER),
                    ("BOX", (0, 0), (-1, -1), 0, WHITE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBEFORE", (0, 0), (0, -1), 4, AMBER),
                ]
            )
        )
        story.append(KeepTogether([table, Spacer(1, 5)]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())
    return story


def _next_milestone_text(scores: dict[str, float]) -> str:
    if not scores:
        return (
            "Choose one gap from this report and complete one concrete action on it within "
            "the next 7 days."
        )
    lowest = min(scores.items(), key=lambda item: item[1])[0]
    milestones = {
        "Investing Readiness": (
            "Begin your first halal investment contribution - even $25 per month - within "
            "the next 30 days. Use stocks.irizq.com to find a Shariah-compliant fund to start with."
        ),
        "Savings Behavior": (
            "Set up an automated savings transfer for any fixed amount within the next 7 days. "
            "The amount matters less than the automation."
        ),
        "Financial Behavior": (
            "Write one page of investment rules this week - what you will buy, hold, and do "
            "in a market drop. Commit to it before the next market move."
        ),
        "Debt Position": (
            "List every debt by interest rate today and make one extra payment on the highest "
            "rate balance this month."
        ),
        "Cash Stability": (
            "Open a dedicated emergency fund account today and make the first transfer - even "
            "$50 starts the habit."
        ),
        "Retirement Planning": (
            "Open or increase your halal-compatible retirement contribution by any amount "
            "before the end of this month."
        ),
        "Tax Awareness": (
            "Review which tax-advantaged accounts you qualify for and open or fund at least "
            "one before the end of this month."
        ),
        "Financial Protection": (
            "Research one Takaful or Shariah-compliant protection option this month and compare "
            "it to your current coverage gap."
        ),
        "Risk Alignment": (
            "Write down your maximum acceptable drawdown and the action you will take in a 20% "
            "drop before the next market move."
        ),
    }
    return milestones.get(
        lowest,
        "Choose one gap from this report and complete one concrete action on it within the next 7 days.",
    )


def _page_verdict(
    styles: dict[str, ParagraphStyle],
    *,
    name: str,
    overall: int,
    grade: str,
    stage: str,
    scores: dict[str, float] | None = None,
) -> list[Any]:
    scores = scores or {}
    story: list[Any] = []
    story.extend(_header_band("Your Financial Readiness Verdict"))
    story.extend(_score_info_band(overall, grade, stage))
    verdict = STAGE_VERDICT.get(
        stage,
        "Closing the identified gaps will strengthen your financial position.",
    )
    story.append(
        Paragraph(
            _clean_text(
                f"{name}, your Financial Readiness Score of {overall}/100 places you in the "
                f"{_profile_short(stage)} profile. {verdict}"
            ),
            styles["body"],
        )
    )
    story.append(Paragraph("Primary Recommendation", styles["rec_h"]))
    story.append(
        Paragraph(
            _clean_text(
                STAGE_RECOMMENDATION.get(
                    stage,
                    "Close your top identified gaps before scaling investment contributions.",
                )
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "JazakumAllahu khayran for using InvestReady by iRizq.",
            ParagraphStyle(
                "IRThanksLine",
                parent=styles["teal_italic"],
                fontSize=10,
                alignment=TA_CENTER,
                spaceBefore=10,
                spaceAfter=8,
            ),
        )
    )

    milestone_h = ParagraphStyle(
        "IRMilestoneH",
        parent=styles["h2"],
        fontSize=12,
        textColor=TEAL,
        spaceBefore=4,
        spaceAfter=4,
    )
    story.append(Paragraph("Your Next Milestone", milestone_h))
    story.append(
        _dense_callout(
            "Focus Here First",
            _clean_text(_next_milestone_text(scores)),
            TEAL,
        )
    )

    story.append(
        Paragraph(
            "Track Your Progress",
            ParagraphStyle(
                "IRTrackH",
                parent=styles["h2"],
                fontSize=11,
                textColor=NAVY,
                spaceBefore=4,
                spaceAfter=4,
            ),
        )
    )
    story.append(
        Paragraph(
            _clean_text(
                "Financial readiness is not a one-time measurement. Retake this assessment in "
                "90 days to measure your improvement across all 9 categories. Small consistent "
                "actions compound into meaningful score changes over time."
            ),
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "stocks.irizq.com/investready",
            ParagraphStyle(
                "IRRetakeLink",
                parent=styles["teal"],
                fontSize=10,
                alignment=TA_CENTER,
                spaceBefore=4,
                spaceAfter=10,
            ),
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
    grade = _letter_grade(overall)
    stage = _normalize_stage(
        payload.get("financial_stage")
        or payload.get("investor_profile")
        or "Profile: Pre-Growth"
    )

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
            scores=scores,
        ),
        "Cover",
    )
    _safe_extend(
        story,
        lambda: _page_toc(
            styles,
            overall=overall,
            grade=grade,
            stage=stage,
            scores=scores,
        ),
        "Table of Contents",
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
        lambda: _page_real_life(styles, scores, flags, answers, overall),
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
            scores=scores,
        ),
        "Final Verdict",
    )
    _safe_extend(story, lambda: _back_cover(styles), "Back Cover")

    def _canvas_maker(*args: Any, **kwargs: Any) -> InvestReadyCanvas:
        return InvestReadyCanvas(*args, prepared_for=name, **kwargs)

    doc.build(story, canvasmaker=_canvas_maker)
    return buffer.getvalue()
