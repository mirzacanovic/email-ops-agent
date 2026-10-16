#!/usr/bin/env python3
"""Builds docs/case-study-one-pager.pdf: the case study condensed to one A4 page
for a prospect who will not read the full write-up.

    pip install reportlab
    python scripts/make_case_study_pdf.py

The content lives below, not in docs/case-study.md, because a one-pager is a
different document (shorter, no process detail). Keep the numbers in step with
the "Second run" table in docs/case-study.md: every figure here comes from it,
and nothing here claims more than it does (one run, same fixtures, small
held-out check). Standard PDF fonts are used, so avoid characters outside
Latin-1 (no arrows or fancy quotes) or they render as black boxes.
"""

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[1] / "docs" / "case-study-one-pager.pdf"
REPO = "github.com/mirzacanovic/email-ops-agent"

INK, MUTED, ACCENT, RULE = (colors.HexColor(c) for c in ("#1b1f24", "#5b6470", "#1a5fb4", "#d5d9de"))

base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.4, leading=11, textColor=INK, alignment=TA_LEFT)
title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=15.5, leading=18)
subtitle = ParagraphStyle("subtitle", parent=base, fontSize=9.2, leading=12, textColor=MUTED)
h = ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=9.4, leading=12, textColor=ACCENT, spaceBefore=6, spaceAfter=1.5)
bullet = ParagraphStyle("bullet", parent=base, leftIndent=9, bulletIndent=0, spaceAfter=1.2)
small = ParagraphStyle("small", parent=base, fontSize=7.4, leading=9.4, textColor=MUTED)
cell = ParagraphStyle("cell", parent=base, fontSize=7.9, leading=9.8)
cell_b = ParagraphStyle("cell_b", parent=cell, fontName="Helvetica-Bold")


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(text, bullet, bulletText="•") for text in items]


def results_table() -> Table:
    rows = [
        ("", "First run (5 Oct)", "Second run (15 Oct)"),
        ("Emails processed / executed", "6 / 5 of 5 approved", "6 / 6 of 6 approved"),
        ("Follow-ups updated, not duplicated", "2 of 2", "2 of 2"),
        ("Non-customer emails routed to a person", "1 of 2", "2 of 2"),
        ("Junk reaching the CRM", "0 (rejected at review)", "0 (never proposed)"),
        ("Plane issue title", "the sender's name", "the email's subject"),
        ("Lead description", "the word \"sales_inquiry\"", "a summary of the request"),
    ]
    data = [[Paragraph(c, cell_b if r == 0 or i == 0 else cell) for i, c in enumerate(row)] for r, row in enumerate(rows)]
    table = Table(data, colWidths=[62 * mm, 55 * mm, 55 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 1.6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=11 * mm,
        title="Email Ops Agent: case study (one page)", author="", subject="An email-to-action agent with a human in the loop",
    )
    s = [
        Paragraph("Email Ops Agent", title),
        Paragraph("An email-to-action agent where a person approves every change. Portfolio case study.", subtitle),
        Spacer(1, 3),

        Paragraph("The problem", h),
        Paragraph(
            "Shared inboxes run on people re-typing the same information into a CRM and a task tracker. It is slow and "
            "inconsistent, and the classic failure is the duplicate: a follow-up filed as a new issue because nobody "
            "remembered the first. An AI that \"handles email\" on its own is the thing a careful client will not accept: "
            "it writes to production systems unsupervised, cannot explain itself, and sends customer email to a third party.",
            base,
        ),

        Paragraph("What it does", h),
        Paragraph(
            "<b>email &gt; classify &gt; extract &gt; match existing records &gt; propose &gt; a person approves, edits or rejects "
            "&gt; execute via API &gt; audit log.</b> A sales inquiry becomes a Lead in EspoCRM, a support request a work item "
            "in Plane. A known sender or a follow-up becomes an update, not a duplicate. Anything that is not a customer "
            "message is escalated to a person. Nothing is written until someone approves, and every step is kept in an "
            "append-only audit trail.",
            base,
        ),

        Paragraph("Design choices that matter", h),
        *bullets([
            "<b>Approval is enforced in code.</b> The decision is recorded first; a rejected or unreviewed proposal never reaches the "
            "execution code. A reviewer can correct the proposed text first; the audit trail keeps both the model's version and the human's.",
            "<b>Runs on the client's own infrastructure.</b> Classification and extraction use a self-hosted open-weight model "
            "(Mistral 7B via Ollama), so email content stays on-prem. Swappable for Claude with one setting.",
            "<b>Narrow interfaces, not one big agent.</b> The model and each target system sit behind a small interface; adding "
            "Zammad or ERPNext means writing an adapter, not changing the pipeline. Each stage is logged and inspectable.",
            "<b>Matching fitted to each system.</b> CRM by exact email, then fuzzy company name. Plane has no search, so the "
            "agent tags each issue with the sender and matches follow-ups against that sender's issues only.",
        ]),

        Paragraph("Results from running it on real systems", h),
        Paragraph(
            "Six scripted emails in three acts, a real EspoCRM and a real Plane project, a person approving each proposal. "
            "The first run exposed problems; I fixed them and ran again.",
            base,
        ),
        Spacer(1, 2.5),
        results_table(),
        Spacer(1, 2.5),
        Paragraph(
            "<b>Read this honestly.</b> It is one run on the same six emails the fixes were written against, so it shows the "
            "specific failures are fixed, not an accuracy rate. Five fresh emails the prompts had not been tuned on were all "
            "classified as expected, but that is five. In the first run the model filed recruiter spam as a sales inquiry; a "
            "reviewer rejected it and nothing reached the CRM, which is the point of keeping a person in the loop. "
            "Self-reported model confidence is still not a reliable signal.",
            base,
        ),

        Paragraph("Built like a project that will be maintained", h),
        *bullets([
            "Tested (129 tests), type-checked and linted, with CI on every change. Schema changes go through migrations, "
            "with a test that fails if a model change has none.",
            "Login with hashed passwords and the reviewer recorded on every decision; protection against cross-site "
            "request forgery and page framing; a readiness check that reports whether the model is actually loaded.",
            "Findings from live runs fixed at the root: failed emails are retried instead of lost, a proposal cannot be "
            "decided twice, and slow polls run in the background with visible progress.",
        ]),

        Paragraph("What it does not do yet", h),
        Paragraph(
            "It reads from an email simulator, not a real inbox. It is slow on CPU (about 3 to 4 minutes per email), "
            "free-text extraction is the main open risk, login is HTTP Basic (needs TLS outside localhost, no lockout, no "
            "roles), and automatic execution without approval is deliberately out of scope until there is real accuracy data.",
            base,
        ),

        Paragraph("If this were a client engagement", h),
        Paragraph(
            "Swap the simulator for a sandboxed real inbox, add one or two of the client's own systems as adapters, and "
            "run approve-everything for a few weeks. That produces the accuracy data needed to decide, per action type, "
            "whether anything can safely skip review.",
            base,
        ),
        Spacer(1, 4),
        Paragraph(
            f"Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Ollama (Mistral 7B), EspoCRM, Plane, Docker Compose, "
            f"GitHub Actions. &nbsp;|&nbsp; Source and full write-up: {REPO}",
            small,
        ),
    ]
    doc.build(s)


if __name__ == "__main__":
    build()
    from pypdf import PdfReader

    pages = len(PdfReader(OUT).pages)
    print(f"wrote {OUT} ({pages} page{'s' if pages != 1 else ''})")
    sys.exit(0 if pages == 1 else 1)
