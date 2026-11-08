"""Tests for the strict required-years extractor (`_extract_years`).

Covers the development cases (copied from the 2026-11-06 probe, so this file does not
import from archive/), the 80 old blind-set entries, the failures and false matches named
in docs/tasks/2026-11-06-required-years-search-jobs-design.md sections 3, 17 and 18, and
a flattened form of every full advert.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.job_hunt_parsing import _extract_years

HOLDOUT_PATH = Path(__file__).parent / "fixtures" / "required_years_holdout.json"
HOLDOUT = json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))

# Synthetic development cases: (text, min, max). They tuned the rules, so they are not an honest rate.
_DEV_CASES = [
    # Real requirements
    ("You will have 5 years of experience in business analysis.", 5, None),
    ("Minimum 3 years' experience as a Business Analyst.", 3, None),
    ("3-5 years of experience in a similar role.", 3, 5),
    ("3 to 5 years' experience in IT delivery.", 3, 5),
    ("5+ years experience with stakeholder management.", 5, None),
    ("At least 7 years experience delivering IT projects.", 7, None),
    ("Proven track record with 10+ years in IT project management.", 10, None),
    ("Five years' experience in financial services.", 5, None),
    ("5+ yrs experience in Agile teams.", 5, None),
    ("5+years experience in Agile teams.", 5, None),
    ("2 years’ experience in a data role.", 2, None),
    ("Experience: 8 years minimum.", 8, None),
    ("Requires a minimum of 4 years working as a Senior BA.", 4, None),
    ("Experience of at least 6 years in agile delivery.", 6, None),
    ("5–7 years experience in insurance.", 5, 7),
    ("Between 3 and 5 years of relevant experience.", 3, 5),
    ("Over 8 years of commercial experience required.", 8, None),
    ("You must have 2+ years hands-on experience with Python.", 2, None),
    ("We are looking for someone with 4 years experience.", 4, None),
    ("Essential: 5+ years BA experience. Desirable: 10 years in banking.", 5, None),
    ("3 years SQL experience and 5 years business analysis experience.", 5, None),
    # Traps with no requirement
    ("Established over 30 years ago, we are a leading supplier.", None, None),
    ("We have been trading for 25 years.", None, None),
    ("With over 40 years of experience in the sector, our consultancy leads the market.", None, None),
    ("You must be at least 18 years old.", None, None),
    ("This is a 2 years fixed term contract.", None, None),
    ("Our company has 15 years of history.", None, None),
    ("Pension increases after 5 years of service.", None, None),
    ("Long service award at 10 years.", None, None),
    ("Data is retained for 7 years.", None, None),
    ("A 5 year transformation programme.", None, None),
    ("Our team of 20 has 100 years of combined experience.", None, None),
    ("Within 2 years you could progress to Head of Change.", None, None),
    ("Over the past 3 years the team has doubled.", None, None),
    ("Candidates must have lived in the UK for 5 years to gain SC clearance.", None, None),
    ("SC clearance requires 5 years of UK residency.", None, None),
    ("Our consultants average 12 years of experience.", None, None),
    ("Graduate scheme: no experience needed, 2 years training programme.", None, None),
    ("Ideally 10 years experience in banking would be nice to have.", None, None),
    ("Several years of experience in a similar role.", None, None),
]


# (text, expected lower bound): failures and false matches named in the design, sections 3, 17, 18.
NAMED_CASES = [
    # Section 3: known false matches and misses
    ("With over 18 years' experience in the recruitment industry, Acme Recruitment is proud to offer this role.", None),
    ("Essential SQL skills Desirable 18 years' experience in banking", None),
    ("Strong SQL5+ years experience", 5),
    ("You will bring ten or more years of experience in IT service management.", 10),
    ("At least seven (7) years' experience in a business analysis role.", 7),
    ("Applicants must be 18 years or older and have 2-3 years' experience in retail.", 2),
    ("18 years or older and have 2-3 years' experience", 2),
    ("5+ years' experience as a business analyst, ideally on digital projects", 5),
    ("This is a 4 year degree apprenticeship in software engineering.", None),
    ("4 year degree apprenticeship in software", None),
    ("Thirteen years' experience in infrastructure.", 13),
    ("Fourteen years' experience in infrastructure.", 14),
    ("Sixteen years' experience in infrastructure.", 16),
    ("Seventeen years' experience in infrastructure.", 17),
    ("Eighteen years' experience in infrastructure.", 18),
    ("Nineteen years' experience in infrastructure.", 19),
    # Section 17 and 18: real-text cases
    ("up to 1 year possibly longer", None),
    ("more than 300 years old", None),
    ("at least 5-10 years' experience", 5),
    ("backed by more than 35 years of industry experience", None),
    ("Do you have 5+ years of commercial experience in industry?", 5),
    ("career break of 12+ months", None),
    # Rule 5: cap at 20
    ("25 years' experience in banking", None),
    ("15-25 years' experience in banking", 15),
    ("20 years' experience in banking", 20),
    # Rule 6: highest lower bound, ranges, zero
    ("3 years SQL experience and 5 years business analysis experience.", 5),
    ("0-2 years' experience in a support role.", 0.0),
    ("Between 3 and 5 years of relevant experience.", 3),
    ("3 to 5 years' experience in IT delivery.", 3),
    ("3–5 years' experience in IT delivery.", 3),
    # Rule 7: spellings
    ("5 plus years experience in testing.", 5),
    ("5 or more years experience in testing.", 5),
    ("5 years or more of experience in testing.", 5),
    ("5 yrs experience in testing.", 5),
    ("5 yr experience in testing.", 5),
    ("2 years' experience in a data role.", 2),
    ("2 years\u2019 experience in a data role.", 2),
    ("5+years experience in testing.", 5),
    # Rule 8: months and vague phrases
    ("18 months' experience in a support role.", None),
    ("Several years of experience in a similar role.", None),
    ("Extensive experience in project delivery is essential.", None),
    # Rule 4: desirable-only
    ("10 years of experience in banking is desirable.", None),
    ("10 years of experience in banking would be preferred.", None),
    ("Desirable: 10 years of experience in banking.", None),
    # Rule 3: boasts need a candidate cue
    ("We have 20 years of experience helping retailers.", None),
    ("We need someone with 4 years of experience in testing.", 4),
    # Separators: </li> and <br> split items, stored text is untouched
    ("<ul><li>Essential: 5 years experience in testing</li><li>Desirable: 10 years in banking</li></ul>", 5),
    ("Desirable<br>10 years experience in banking<br>Essential<br>3 years experience in testing", 3),
    ("Desirable:\n- 10 years experience in banking\n\nAbout you\n- 4 years experience in testing", 4),
    # Edge input
    ("", None),
    ("No numbers here.", None),
]


@pytest.mark.parametrize(("text", "expected", "_max"), _DEV_CASES, ids=lambda v: str(v)[:40])
def test_dev_case(text, expected, _max):
    assert _extract_years(text) == expected


@pytest.mark.parametrize(("text", "expected"), NAMED_CASES, ids=lambda v: str(v)[:40])
def test_named_case(text, expected):
    assert _extract_years(text) == expected


@pytest.mark.parametrize("entry", HOLDOUT, ids=[entry["id"] for entry in HOLDOUT])
def test_holdout_as_written(entry):
    assert _extract_years(entry["text"]) == entry["min"]


@pytest.mark.parametrize(
    "entry", [e for e in HOLDOUT if e["group"] == "full_advert"], ids=lambda e: e["id"]
)
def test_holdout_full_advert_flattened(entry):
    assert _extract_years(" ".join(entry["text"].split())) == entry["min"]


def test_holdout_has_80_entries():
    assert len(HOLDOUT) == 80


def test_returns_float_or_none():
    assert isinstance(_extract_years("5 years' experience in testing."), float)
    assert _extract_years("0-2 years' experience in testing.") == 0.0
    assert _extract_years("0-2 years' experience in testing.") is not None
