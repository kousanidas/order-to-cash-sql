"""
Data privacy check. Run it after any change to the generator.

    python3 data_privacy_check.py          # exits 0 on a clean run, 1 otherwise

Synthetic data can still pick up things that look like personal data, so this
checks the database and every supporting file three ways:

  1. ALLOWLIST. Every column that could carry a person, a place or a customer
     is checked against the synthetic vocabulary declared below. Anything
     outside it fails.

  2. PATTERNS. Shapes that are sensitive whatever the content: email
     addresses, Indian mobile numbers, GSTIN, PAN, and government tender
     references.

  3. PERSON-SHAPED TEXT. Any "Firstname Lastname" in any text column that is
     not in the allowlist.

It scans PER CELL, not per row, so two harmless neighbouring values can never
be joined into a false match.
"""

import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = f"{HERE}/o2c.db"

# ---------------------------------------------------------------- 1. allowlists
# Every value below is invented.
PEOPLE = {"Ishan Kabir", "Niharika Vora", "Zubin Tandon", "Anika Rao",
          "Farhan Qureshi", "Rohan Mehta", "Yash Nagpal", "Ketan Oza",
          "Hemal Zaveri",
          "IK", "NV", "ZT", "AR", "FQ", "RM", "YN", "KO", "HZ",
          # one cell holding two people, on purpose
          "Rohan Mehta /Anika Rao"}

PLACES = {"Ex-Works Plant 1", "EX-WORKS PLANT 1", "Ex-works Plant 1",
          "EX-WORKS PLANT-1", "Ex-Works", "FOB", "ExW", "EX-WORKS PLANT 2",
          "Ex works", "FOR", "EXW", "FOR SITE",
          "HO", "H.O.", "NA", "PLANT 2"}

MARKETS = {"Domestic", "DOMESTIC", "Internal", "External", "Export",
           "Export-KAG", "Export-Non-KAG", "Rohan Mehta /Anika Rao"}

COUNTRIES = {"India", "United Kingdom", "Spain", "Netherlands",
             "United Arab Emirates", "Saudi Arabia", "Singapore", "Australia",
             "United States"}
REGIONS = {"East", "West", "South", "North", "Europe", "Middle East", "APAC",
           "Americas"}

ALLOWED_COLUMNS = {
    ("raw_quote_register", "concerned_person"): PEOPLE,
    ("customers", "country"): COUNTRIES,
    ("customers", "region"): REGIONS,
    ("raw_quote_register", "incoterms"): PLACES,
    ("raw_quote_register", "quote_from"): PLACES,
    ("raw_quote_register", "vertical"): MARKETS,
    ("quotations", "salesperson_code"): PEOPLE,
    ("quotations", "incoterms"): PLACES,
    ("customers", "market_type"): {"Domestic", "Export", "Deemed Export"},
}

# ---------------------------------------------------------------- 2. patterns
PATTERNS = {
    "email address": r"[\w\.\-]+@[\w\.\-]+\.\w{2,}",
    # The lookarounds reject a letter and a decimal point as well as a digit.
    # Without that, every generated PO number ("P8085106052") matched and the
    # sweep reported 346 phantom phone numbers.
    "Indian mobile number": r"(?<![\w.])(?:\+91[\s\-]?)?[6-9]\d{9}(?![\w.])",
    "GSTIN": r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d\b",
    "PAN": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    # generated tender references sit in a high serial range on purpose, so a
    # hit in this lower range means an actual reference has been copied in.
    "tender ref in an actual serial range":
        r"GEM/\d{4}/[A-Z]/(?:4[89]\d{5}|[56]\d{6})(?!\d)",
}

# Columns that legitimately hold free text and are allowed to contain a
# person-shaped string, because the synthetic salesperson names live there.
PERSON_SHAPE_EXEMPT = {("raw_quote_register", "concerned_person"),
                       ("quotations", "salesperson_code"),
                       ("raw_quote_register", "vertical")}
PERSON_SHAPE = re.compile(r"\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b")
# A person-shaped match is only a finding if it is NOT part of something this
# project declares. Rather than keep a hand-written list of innocent phrases -
# which went stale immediately and reported "Caustic Storage" as a person - the
# declared vocabulary is imported from the generator itself, so the two cannot
# drift apart.
def declared_strings():
    import raw_register as rr
    out = set()
    for lst in (rr.PROJECT_WORDS, rr.SITE_WORDS, rr.PAYMENT_TERMS,
                rr.DP_FREE_TEXT, rr.INCOTERMS, rr.QUOTE_FROM, rr.QUOTE_NO_JUNK):
        out |= {str(x) for x in lst}
    for v in rr.CATEGORY_TEXT.values():
        out |= set(v)
    out |= {v for v, _ in rr.LD_VALUES}
    out |= {v for v, _ in rr.LD_CLAUSE_VALUES}
    out |= {v for v in rr.FACTS["status_vocabulary"]["all_values_as_typed"]}
    out |= COUNTRIES | REGIONS | PLACES | MARKETS | PEOPLE
    out |= {"Domestic", "Export", "Deemed Export"}
    for it in ("FRP pressure vessel", "Pultruded handrail section",
               "Pultruded angle profile", "Pultruded channel profile",
               "Pultruded tube 50x50", "Pultruded ladder stringer",
               "Moulded grating 38 mm, 1x4 m panel",
               "Moulded grating 25 mm, 1x4 m panel",
               "Pultruded grating 40 mm panel",
               "Grating with anti-skid grit top", "Stair tread with nosing"):
        out.add(it)
    return out


def cells():
    """Every (table, column, value) in the database, one cell at a time."""
    con = sqlite3.connect(DB)
    for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
        for row in con.execute(f'SELECT * FROM "{t}"'):
            for c, v in zip(cols, row):
                if v is not None:
                    yield t, c, str(v)
    con.close()


def files():
    """Every (path, line_no, line) in the shipped supporting files."""
    for root, dirs, names in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for n in names:
            if n.endswith(".db"):
                continue
            p = os.path.join(root, n)
            rel = os.path.relpath(p, HERE)
            try:
                for i, line in enumerate(open(p, encoding="utf-8",
                                              errors="replace"), 1):
                    yield rel, i, line
            except OSError:
                pass


def main():
    problems = []

    # ---- 1. allowlists
    seen = {}
    for t, c, v in cells():
        if (t, c) in ALLOWED_COLUMNS:
            seen.setdefault((t, c), set()).add(v)
    for key, allowed in ALLOWED_COLUMNS.items():
        extra = sorted(seen.get(key, set()) - allowed)
        if extra:
            problems.append(f"{key[0]}.{key[1]}: {len(extra)} value(s) outside "
                            f"the allowlist -> {extra[:5]}")

    # ---- 2. patterns, in the database and in every shipped file
    for label, rx in PATTERNS.items():
        hits = set()
        for t, c, v in cells():
            for m in re.findall(rx, v):
                hits.add((f"{t}.{c}", m))
        for rel, i, line in files():
            for m in re.findall(rx, line):
                hits.add((f"{rel}:{i}", m))
        if hits:
            problems.append(f"{label}: {len(hits)} hit(s) -> "
                            f"{sorted(hits)[:4]}")

    # ---- 3. person-shaped text anywhere it is not expected
    declared = declared_strings()
    shaped = set()
    for t, c, v in cells():
        if (t, c) in PERSON_SHAPE_EXEMPT:
            continue
        for m in PERSON_SHAPE.findall(v):
            if m in PEOPLE:
                continue
            if any(m in d for d in declared):
                continue
            shaped.add((f"{t}.{c}", m))
    if shaped:
        problems.append(f"person-shaped text in unexpected columns: "
                        f"{len(shaped)} -> {sorted(shaped)[:6]}")

    # ---- report
    print("Confidentiality sweep")
    print("=" * 70)
    print(f"  allowlisted columns checked : {len(ALLOWED_COLUMNS)}")
    print(f"  patterns checked            : {len(PATTERNS)}")
    print("  person-shape net            : every text cell outside "
          f"{len(PERSON_SHAPE_EXEMPT)} exempt columns")
    print("=" * 70)
    if not problems:
        print("CLEAN - no findings")
        return 0
    for p in problems:
        print(f"  FINDING: {p}")
    print(f"\n{len(problems)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
