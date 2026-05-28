"""SQLAlchemy models for SEC-backed financial screening pipeline."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    cik: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    filings: Mapped[list["Filing"]] = relationship(back_populates="company")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("company_id", "accession_number", name="uq_filings_company_accession"),
        Index("ix_filings_company_type_date", "company_id", "filing_type", "filing_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    company: Mapped["Company"] = relationship(back_populates="filings")


class RawFinancialFact(Base):
    __tablename__ = "raw_financial_facts"
    __table_args__ = (
        Index("ix_raw_financial_facts_company_filing", "company_id", "filing_id"),
        Index("ix_raw_financial_facts_tag", "tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), nullable=False, index=True)
    taxonomy: Mapped[str] = mapped_column(String(32), nullable=False)
    tag: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frame: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class NormalizedFinancial(Base):
    __tablename__ = "normalized_financials"
    __table_args__ = (
        UniqueConstraint("company_id", "filing_id", name="uq_normalized_company_filing"),
        Index("ix_normalized_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), nullable=False, index=True)
    total_revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    interest_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    total_debt: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    cash_and_equivalents: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    shares_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    source_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class HalalScreenResult(Base):
    __tablename__ = "halal_screen_results"
    __table_args__ = (
        UniqueConstraint("company_id", "filing_id", name="uq_halal_result_company_filing"),
        Index("ix_halal_screen_results_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), nullable=False, index=True)
    debt_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    interest_income_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    cash_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    halal_status: Mapped[str] = mapped_column(String(64), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="sec_xbrl")
    source_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapped_tags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reasoning_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
