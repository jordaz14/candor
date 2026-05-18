"""SEC EDGAR fetcher using `edgartools`.

We pull 10-K and 10-Q filings for a single ticker over the past 5 years,
then extract the four sections the spec calls out:
    - Business Overview        (10-K Item 1)
    - Risk Factors             (10-K Item 1A)
    - Management's Discussion  (10-K Item 7 / 10-Q Item 2)
    - Financial Statements     (10-K Item 8 / 10-Q Item 1)

Each returned `ExtractedFiling` is consumed by ingest.py, which passes each
section's text into chunking.chunk_section() and then to the embedder.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from datetime import date, timedelta

from edgar import Company, set_identity


@dataclass
class ExtractedSection:
    name: str         # "Business Overview" | "Risk Factors" | "MD&A" | "Financial Statements"
    text: str         # cleaned section body


@dataclass
class ExtractedFiling:
    accession_no: str
    filing_type: str          # "10-K" | "10-Q"
    period_end: date | None
    filed_date: date | None
    edgar_url: str
    sections: list[ExtractedSection]


# edgartools requires identifying the requester via the SEC fair-access policy.
# Call set_identity() once before any Company/Filing API calls.
def _ensure_identity() -> None:
    ident = os.environ.get("SEC_USER_AGENT")
    if not ident:
        raise RuntimeError("SEC_USER_AGENT must be set in env (e.g. 'Jane Doe jane@example.com')")
    set_identity(ident)


# ---------------------------------------------------------------------------
# DECISION POINT — implement extract_sections() below.
#
# edgartools exposes 10-K / 10-Q filings via accessors like:
#     filing = company.get_filings(form="10-K").latest(1)[0]
#     tenk = filing.obj()        # returns a TenK object
#     tenk.business              # str | None
#     tenk.risk_factors          # str | None
#     tenk.management_discussion # str | None
#     tenk.financial_statements  # str | None    (note: this is largely tables/HTML)
#
# For 10-Q, the equivalent is `filing.obj()` returning a TenQ with similar
# accessors but different item numbering.
#
# Your job: take a filing object (already converted via .obj()) and return a
# list[ExtractedSection]. Decisions to make:
#
#   1. Section name normalization. 10-K calls it "Item 7 — MD&A", 10-Q calls
#      it "Item 2 — MD&A". Do you store them as the same `name` so the same
#      query filter works across filings? (Recommended: yes — pick canonical
#      names like "MD&A".)
#
#   2. Skip empty sections vs. emit empty ones. If a 10-Q omits Risk Factors
#      (common — they only update when material), do you skip silently or
#      emit ExtractedSection(name="Risk Factors", text="")?
#
#   3. Financial Statements is mostly tables. Embeddings of tabular HTML are
#      noisy and rarely useful for semantic search. Skip it from chunking?
#      Or keep it for completeness and accept the noise?
#
#   4. Text cleaning. edgartools returns mostly-clean text but you may see
#      "\n\n\n" runs, page numbers, or non-ASCII whitespace. How aggressively
#      to normalize? (Cheap win: collapse 3+ newlines to 2.)
# ---------------------------------------------------------------------------

# Canonical section names — keep filter queries consistent across 10-K and 10-Q.
class Section(str, Enum):
    BUSINESS = "Business Overview"
    RISK = "Risk Factors"
    MDA = "MD&A"
    FINANCIALS = "Financial Statements"

def get_section_text(section, filing_obj, filing_type) -> str:
    if filing_type not in ["10-K", "10-Q"]:
        raise ValueError(f"Unknown filing type: {filing_type}")

    is_tenk = filing_type == "10-K"

    match section:
        case Section.BUSINESS:
            return filing_obj.business if is_tenk else ""
        case Section.RISK:
            return filing_obj.risk_factors if is_tenk == "10-K" else filing_obj["Item 1A"]
        case Section.MDA:
            return filing_obj.management_discussion if is_tenk == "10-K" else filing_obj["Item 2"]
        case Section.FINANCIALS:
            return filing_obj.financial_statements if is_tenk == "10-K" else filing_obj["Item 1"]
        case _:
            raise ValueError(f"Unknown filing section: {section}")


def extract_sections(filing_obj, filing_type) -> list[ExtractedSection]:
    """Pull the four spec'd sections from an edgartools TenK or TenQ object."""
    return [ExtractedSection(name=s.value, text=get_section_text(s, filing_obj, filing_type )) for s in Section]


# ---------------------------------------------------------------------------
# Top-level driver: ingest.py calls this. Mechanical glue, no decisions here.
# ---------------------------------------------------------------------------

def fetch_filings(ticker: str, *, years: int = 5) -> list[ExtractedFiling]:
    """Return parsed 10-K and 10-Q filings for `ticker` over the last `years`."""
    _ensure_identity()
    company = Company(ticker)
    cutoff = date.today() - timedelta(days=years * 365)

    out: list[ExtractedFiling] = []
    for form in ("10-K", "10-Q"):
        for filing in company.get_filings(form=form):
            if filing.filing_date < cutoff:
                continue
            obj = filing.obj()
            sections = extract_sections(obj, form)
            out.append(
                ExtractedFiling(
                    accession_no=str(filing.accession_no),
                    filing_type=form,
                    period_end=getattr(filing, "period_of_report", None),
                    filed_date=filing.filing_date,
                    edgar_url=filing.filing_url,
                    sections=sections,
                )
            )
    return out
