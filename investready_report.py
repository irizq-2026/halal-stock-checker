"""InvestReady premium PDF report generator (reportlab)."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
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

# iRizq brand colors
NAVY = colors.HexColor("#0d1f3c")
TEAL = colors.HexColor("#1ec8b8")
GREEN = colors.HexColor("#3d7a45")
SILVER = colors.HexColor("#f1f2f4")
WHITE = colors.HexColor("#ffffff")
TEXT = colors.HexColor("#374151")
AMBER = colors.HexColor("#f59e0b")
RED = colors.HexColor("#ef4444")
MUTED = colors.HexColor("#6b7280")

_ARABIC_FONT = "Helvetica"


def _register_fonts() -> str:
    global _ARABIC_FONT
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("InvestReadyArabic", str(path)))
                _ARABIC_FONT = "InvestReadyArabic"
                return _ARABIC_FONT
            except Exception:
                continue
    return _ARABIC_FONT


_register_fonts()

LOGO_PATH = Path(__file__).resolve().parent / "static" / "logo.png"
DISCLAIMER = (
    "Educational only. iRizq does not provide financial, legal, tax, or investment advice. "
    "Use this assessment as a learning tool and consult qualified professionals for personal guidance."
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
            fontSize=36,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=4,
            leading=40,
        ),
        "grade": ParagraphStyle(
            "IRGrade",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=6,
            leading=28,
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
            fontSize=18,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=0,
            leading=22,
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
            fontSize=22,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "bismillah_ar": ParagraphStyle(
            "IRBismillahAr",
            parent=base["BodyText"],
            fontName=_ARABIC_FONT,
            fontSize=11,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=2,
            leading=16,
        ),
        "bismillah_en": ParagraphStyle(
            "IRBismillahEn",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceAfter=0,
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
    }


def _score_color(score: float) -> colors.Color:
    if score >= 80:
        return TEAL
    if score >= 60:
        return GREEN
    return RED


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


def _strengths_and_risks(category_scores: dict[str, Any]) -> tuple[list[str], list[str], str]:
    ranked = sorted(
        ((str(k), float(v)) for k, v in category_scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    true_strengths = [(name, score) for name, score in ranked if score >= 70]
    use_relative = len(true_strengths) < 3
    strength_source = ranked[:3] if use_relative else true_strengths[:3]
    strength_label = "Relatively Stronger Area" if use_relative else "Strength"
    strengths = [f"{strength_label}: {name} ({int(score)}/100)" for name, score in strength_source]

    risks = [
        f"Needs attention: {name} ({int(score)}/100)"
        for name, score in sorted(
            ((str(k), float(v)) for k, v in category_scores.items() if float(v) < 60),
            key=lambda item: item[1],
        )[:3]
    ]
    return strengths, risks, strength_label


def _mistakes(answers: dict[str, Any], category_scores: dict[str, Any]) -> list[tuple[str, str]]:
    mistakes: list[tuple[str, str]] = []
    a = {str(k): v for k, v in (answers or {}).items()}

    # Q4 emergency months - score index 0/1 => under 3 months
    if int(a.get("q4", 4) or 0) <= 1:
        mistakes.append(
            (
                "Limited Emergency Buffer",
                "Your emergency savings appear below recommended levels. "
                "Why it matters: Without a cash buffer, unexpected expenses can force "
                "debt or selling investments at the wrong time. "
                "Potential consequences: Higher stress, expensive borrowing, and disrupted "
                "long-term plans. "
                "Steps: 1) Open a dedicated high-yield savings account. "
                "2) Automate a small weekly transfer. "
                "3) Target at least 3 months of essential expenses.",
            )
        )

    # Q7 high-interest debt (0-2) and Q10 investing experience (>0)
    if int(a.get("q7", 4) or 0) <= 2 and int(a.get("q10", 0) or 0) >= 1:
        mistakes.append(
            (
                "Investing While Carrying Expensive Debt",
                "Paying down high-interest debt typically offers a guaranteed "
                "return that is difficult to beat through investing. "
                "Why it matters: Interest compounds against you while markets are uncertain. "
                "Potential consequences: Slower net worth growth and ongoing financial stress. "
                "Steps: 1) List debts by interest rate. "
                "2) Prioritize balances above 10% APR. "
                "3) Keep investing only after a clear paydown plan is in place.",
            )
        )

    # Q13 concentration
    if int(a.get("q13", 4) or 0) <= 1:
        mistakes.append(
            (
                "Concentration Risk",
                "A large portion of your portfolio appears concentrated in one area. "
                "Why it matters: Single-stock or single-sector shocks can wipe out years of gains. "
                "Potential consequences: Higher volatility and larger drawdowns. "
                "Steps: 1) Measure your largest holding as a percent of net worth. "
                "2) Set a soft cap (for example under 25%). "
                "3) Diversify gradually into broad funds or additional sectors.",
            )
        )

    # Q18 insurance review
    if int(a.get("q18", 4) or 0) <= 1:
        mistakes.append(
            (
                "Outdated Insurance Coverage",
                "Life circumstances change. Coverage that fit years ago may leave gaps today. "
                "Why it matters: Insurance is a core risk-transfer tool for dependents and assets. "
                "Potential consequences: Under-insurance during illness, disability, or loss. "
                "Steps: 1) Schedule a coverage review this month. "
                "2) Confirm beneficiaries and deductibles. "
                "3) Align policies with current income and dependents.",
            )
        )

    # Q20 goals
    if int(a.get("q20", 4) or 0) <= 1:
        mistakes.append(
            (
                "Investing Without Defined Goals",
                "Without clear targets and timelines, it is difficult to choose appropriate "
                "investments. "
                "Why it matters: Goals drive asset allocation, risk level, and contribution size. "
                "Potential consequences: Random investing, panic selling, and missed milestones. "
                "Steps: 1) Write 1 near-term and 1 long-term goal. "
                "2) Add a dollar target and date. "
                "3) Match each goal to a suitable account and allocation.",
            )
        )

    if not mistakes:
        # Fallback using weakest categories
        ranked = sorted(category_scores.items(), key=lambda item: float(item[1]))
        for name, score in ranked[:3]:
            mistakes.append(
                (
                    f"Priority Gap: {name}",
                    f"Your {name} score is {int(float(score))}/100. "
                    "Why it matters: This area is currently limiting your overall readiness. "
                    "Potential consequences: Slower progress and higher avoidable risk. "
                    "Steps: 1) Review this category in your action plan. "
                    "2) Pick one habit to improve this week. "
                    "3) Reassess in 30 days.",
                )
            )
    return mistakes[:5]


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


# Exactly 3 habits per category for the educational section (PAGE 10-11).
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
    """Return exactly 3 non-empty habits for a category."""
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
    week: list[str] = []
    month: list[str] = []
    ninety: list[str] = []
    for idx, cat in enumerate(weak[:3]):
        items = catalog.get(cat, ["Review this category and choose one improvement habit"])
        if idx == 0:
            week.extend(items[:2])
        elif idx == 1:
            month.extend(items[:2])
        else:
            ninety.extend(items[:2])
    if not week:
        week = ["Complete a 7-day money audit", "Automate one savings transfer"]
    if not month:
        month = ["Build or top up emergency savings", "Review debt repayment order"]
    if not ninety:
        ninety = ["Document a written investment policy", "Rebalance and diversify gradually"]
    return {"week": week, "month": month, "ninety": ninety}


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
    strengths, risks, strength_label = _strengths_and_risks(category_scores)
    mistakes = _mistakes(answers, category_scores)
    weak_cats = [
        name_
        for name_, score in sorted(category_scores.items(), key=lambda item: float(item[1]))
        if float(score) < 70
    ]
    actions = _actions_for_categories(weak_cats or list(category_scores.keys())[:3])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title="InvestReady Financial Readiness Report",
        author="iRizq.com",
    )
    story: list[Any] = []

    # PAGE 1 - Executive Summary
    story.append(Paragraph("بِسْمِ اللهِ الرَّحْمٰنِ الرَّحِيْمِ", styles["bismillah_ar"]))
    story.append(Paragraph("In the name of Allah, the Most Gracious, the Most Merciful", styles["bismillah_en"]))
    story.append(Spacer(1, 12))
    story.append(_logo_flowable(1.15 * inch))
    story.append(Spacer(1, 16))
    story.extend(_header_band("InvestReady Financial Readiness Report"))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Prepared for <b>{name}</b>", styles["center"]))
    story.append(Spacer(1, 16))
    meta_bits = []
    if email:
        meta_bits.append(email)
    meta_bits.append(datetime.utcnow().strftime("Generated %B %d, %Y"))
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), styles["muted"]))
    story.append(Spacer(1, 4))

    # Score block: fixed 60pt allocation so large text cannot overlap neighbors
    score_block = Table(
        [
            [Paragraph("OVERALL SCORE", styles["score_label"])],
            [Paragraph(f"{overall} / 100", styles["score"])],
        ],
        colWidths=[7.0 * inch],
        rowHeights=[14, 46],
    )
    score_block.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(score_block)
    story.append(Paragraph(f"Grade: {grade}", styles["grade"]))
    story.append(Spacer(1, 4))
    profile_block = Table(
        [
            [Paragraph("YOUR PROFILE", styles["profile_label"])],
            [Paragraph(f"Investor Profile: {profile}", styles["profile"])],
        ],
        colWidths=[7.0 * inch],
        rowHeights=[12, 24],
    )
    profile_block.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(profile_block)
    # Clear separation after score/grade/profile before strengths
    story.append(Spacer(1, 20))

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
    strengths_heading = "Your Top Strengths" if strength_label == "Strength" else "Relatively Stronger Areas"
    story.append(Paragraph(f"<b>{strengths_heading}</b>", page1_h))
    if strengths:
        for item in strengths:
            story.append(Paragraph(f"<font color='#1ec8b8'>&#10003;</font> {item}", page1_item))
    else:
        story.append(Paragraph("No categories currently score as clear strengths.", page1_item))
    story.append(Spacer(1, 16))
    story.append(Paragraph("<b>Areas Needing Attention</b>", page1_h))
    if risks:
        for item in risks:
            story.append(Paragraph(f"<font color='#f59e0b'>!</font> {item}", page1_item))
    else:
        story.append(Paragraph("No categories currently fall below the attention threshold.", page1_item))
    story.append(Spacer(1, 16))
    summary = (
        f"{name}, your InvestReady score of {overall}/100 ({grade}) places you in the "
        f"{profile} profile. This report highlights where your foundation is solid and "
        f"where focused action over the next 7, 30, and 90 days can improve readiness. "
        f"Use it as an educational roadmap - not personalized investment advice."
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph(summary, styles["body"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 2 - Score Dashboard
    story.extend(_header_band("Your Score Breakdown"))
    rows = [[Paragraph("<b>Category</b>", styles["body_left"]), Paragraph("<b>Score</b>", styles["body_left"]), Paragraph("<b>Status</b>", styles["body_left"])]]
    for cat, score in category_scores.items():
        sc = float(score)
        status = "Strong" if sc >= 80 else ("Developing" if sc >= 60 else "Needs Attention")
        color = _score_color(sc)
        rows.append(
            [
                Paragraph(cat, styles["body_left"]),
                Paragraph(f"<font color='#{_color_hex(color)}'><b>{int(sc)}</b></font>", styles["body_left"]),
                Paragraph(status, styles["body_left"]),
            ]
        )
    table = Table(rows, colWidths=[3.6 * inch, 1.2 * inch, 2.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("BACKGROUND", (0, 1), (-1, -1), SILVER),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"<b>Overall Score: {overall}/100</b>", styles["h1"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 3-4 - Costly Mistakes
    story.extend(_header_band("Costly Mistakes You May Be Making"))
    story.append(
        Paragraph(
            "These warnings are generated from your assessment answers. They are educational "
            "prompts to help you prioritize - not accusations or personalized advice.",
            styles["body"],
        )
    )
    for title, body in mistakes:
        story.append(_callout(title, body, AMBER))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 5-6 - Personalized Insights
    story.extend(_header_band("Personalized Insights"))
    insights = [
        f"Your overall readiness score of {overall} suggests a {profile.lower()} posture toward risk and growth.",
        "Cash flow and emergency preparedness form the base of every resilient plan. Weakness here usually shows up as forced decisions later.",
        "Debt management quality often determines whether investing gains are kept or quietly eroded by interest.",
        "Investing readiness is less about picking winners and more about process: contributions, diversification, and behavior under stress.",
        "Retirement and tax awareness compound quietly. Small consistent improvements here can matter more than short-term market timing.",
        "Goal clarity turns vague intention into measurable progress. Written goals with dates improve follow-through.",
        "Behavioral discipline is the multiplier. The best allocation fails if fear or hype drives decisions.",
    ]
    if overall >= 80:
        insights.insert(1, "You already show strong fundamentals. Your edge now is consistency, refinement, and avoiding overconfidence.")
    elif overall >= 60:
        insights.insert(1, "You have a workable foundation with clear upgrade paths. Focus on the lowest two category scores first.")
    else:
        insights.insert(1, "Your results point to foundational gaps. Stabilize cash, debt, and emergency reserves before increasing market risk.")
    for paragraph in insights:
        story.append(Paragraph(paragraph, styles["body"]))
        story.append(HRFlowable(width="40%", thickness=2, color=TEAL, spaceBefore=2, spaceAfter=8, hAlign="LEFT"))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 7 - Investor Profile
    story.extend(_header_band("Your Investor Profile"))
    story.append(Paragraph("YOUR PROFILE", styles["profile_label"]))
    story.append(Paragraph(f"Investor Profile: {profile}", styles["profile"]))
    story.append(Spacer(1, 16))
    profile_copy = PROFILE_DESCRIPTIONS.get(
        profile,
        "You balance growth and stability with a measured approach through a diversified halal investment portfolio.",
    )
    story.append(Paragraph(profile_copy, styles["body"]))
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

    # PAGE 8-9 - Priority Action Plan
    story.extend(_header_band("Priority Action Plan"))
    for label, key, accent in (
        ("THIS WEEK", "week", TEAL),
        ("IN 30 DAYS", "month", GREEN),
        ("IN 90 DAYS", "ninety", NAVY),
    ):
        story.append(_callout(label, "<br/>".join(f"- {item}" for item in actions[key]), accent))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 10-11 - Educational Section
    story.extend(_header_band("Educational Guidance for Priority Categories"))
    edu_targets = weak_cats[:5] or list(category_scores.keys())[:3]
    for cat in edu_targets:
        story.append(Paragraph(cat, styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=2, color=TEAL, spaceAfter=6))
        story.append(
            Paragraph(
                f"<b>Why {cat} matters:</b> Strength in this area reduces avoidable risk and "
                f"improves long-term optionality.",
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "<b>Common misconception:</b> Waiting for perfect conditions. Progress usually "
                "comes from small repeatable habits, not perfect timing.",
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "<b>What improvement looks like:</b> Clear numbers, automated systems, and a "
                "written rule set you can follow under stress.",
                styles["body"],
            )
        )
        story.append(Paragraph("<b>3 habits to build:</b>", styles["body_left"]))
        habits = _habits_for_category(cat)
        for habit in habits:
            if habit:
                story.append(Paragraph(f"- {habit}", styles["body_left"]))
        story.append(Spacer(1, 6))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 12 - Future Scenarios
    story.extend(_header_band("Future Scenarios (Illustrative)"))
    story.append(
        Paragraph(
            "These scenarios are hypothetical illustrations only. They are not forecasts or promises of returns.",
            styles["muted"],
        )
    )
    story.append(
        _callout(
            "Steady Improver",
            "You raise savings automation, reduce expensive debt, and keep investing through volatility. "
            "Readiness compounds through consistency.",
            TEAL,
        )
    )
    story.append(
        _callout(
            "Status Quo Drift",
            "Habits stay the same. Short-term comfort remains, but gaps in emergency reserves, "
            "tax planning, or diversification quietly limit long-term options.",
            AMBER,
        )
    )
    story.append(
        _callout(
            "Shock Without Buffer",
            "An unexpected expense arrives before foundations are ready. Without cash reserves and "
            "insurance alignment, recovery takes longer and costs more.",
            RED,
        )
    )
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 13 - Checklist
    story.extend(_header_band("Financial Readiness Checklist"))
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
        story.append(Paragraph(f"<font color='#1ec8b8'>&#9744;</font> {item}", styles["body_left"]))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 14 - Grade and Next Steps
    story.extend(_header_band("Overall Grade and Next Steps"))
    story.append(Paragraph("OVERALL SCORE", styles["score_label"]))
    story.append(Paragraph(f"{overall} / 100", styles["score"]))
    story.append(Paragraph(f"Grade: {grade}", styles["grade"]))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            f"Your grade of {grade} reflects an overall score of {overall}/100. "
            f"Treat this as a snapshot of readiness, not a permanent label.",
            styles["body"],
        )
    )
    story.append(Paragraph("<b>Top 3 focus areas</b>", styles["h2"]))
    for cat in (weak_cats or list(category_scores.keys()))[:3]:
        story.append(Paragraph(f"- {cat}", styles["body_left"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Continue your journey:", styles["h2"]))
    story.append(Paragraph("iRizq.com &nbsp;|&nbsp; stocks.irizq.com", styles["teal"]))
    story.append(Paragraph(
        "May Allah bless your wealth, purify your earnings, and grant you barakah in your financial journey. Ameen.",
        styles["dua"],
    ))
    story.append(Paragraph(DISCLAIMER, styles["muted"]))
    story.append(PageBreak())

    # PAGE 15 - Back Cover
    cover = Table(
        [[
            [
                Spacer(1, 1.8 * inch),
                _logo_flowable(1.8 * inch),
                Spacer(1, 16),
                Paragraph("InvestReady", styles["white_title"]),
                HRFlowable(width="40%", thickness=3, color=TEAL, spaceBefore=4, spaceAfter=12),
                Paragraph("stocks.irizq.com", styles["white_center"]),
                Paragraph("Halal Wealth for Every Muslim", styles["white_center"]),
                Spacer(1, 0.35 * inch),
                Paragraph(
                    "Earn halal - invest consistently - stay diversified - think long-term - let time grow your rizq.",
                    styles["teal_italic_small"],
                ),
                Spacer(1, 0.9 * inch),
                Paragraph(DISCLAIMER, styles["white_center"]),
            ]
        ]],
        colWidths=[7.0 * inch],
        rowHeights=[9.2 * inch],
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 24),
                ("RIGHTPADDING", (0, 0), (-1, -1), 24),
            ]
        )
    )
    story.append(cover)

    doc.build(story)
    return buffer.getvalue()
