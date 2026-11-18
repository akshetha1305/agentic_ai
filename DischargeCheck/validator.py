"""validator.py - compares extracted fields with the documentation checklist.

IMPORTANT: this module only checks whether something is DOCUMENTED. It never judges
whether the content is clinically correct, appropriate or required.

Statuses: Present, Missing, Unclear, Not applicable.
"""
import re
from datetime import date

PRESENT = "Present"
MISSING = "Missing"
UNCLEAR = "Unclear"
NOT_APPLICABLE = "Not applicable"

# (checklist key, field key in the extraction, label shown to the user)
CHECKLIST = [
    ("discharge_date", "discharge_date", "Discharge date documented"),
    ("follow_up", "follow_up", "Follow-up appointment/date documented"),
    ("pending_investigations", "pending_investigations",
     "Pending investigations/results documented or explicitly marked as none"),
    ("medications", "medications_as_written", "Medication list documented"),
    ("medication_changes", "medication_changes",
     "Medication changes documented or explicitly marked as none/not applicable"),
    ("patient_instructions", "patient_instructions", "Patient instructions documented"),
    ("responsible_clinician", "responsible_clinician", "Responsible clinician details documented"),
]
CHECKLIST_LABELS = {key: label for key, _, label in CHECKLIST}

REVIEW_MESSAGE = "Requires clinician review"
DISCLAIMER = (
    "This tool checks documentation completeness only. "
    "It does not provide clinical advice or replace clinician review."
)

# ----------------------------------------------------------------------------
# Dates
# ----------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")),
    ("num", re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(" + _MONTH_RE + r")[a-z]*[\s,.\-]+(\d{4})\b", re.I)),
    ("mdy", re.compile(r"\b(" + _MONTH_RE + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
]


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text):
    """Return a list of valid dates found in text, in order of appearance."""
    found = []
    for kind, pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            a, b, c = match.groups()
            parsed = None
            if kind == "iso":
                parsed = _safe_date(int(a), int(b), int(c))
            elif kind == "num":
                year = int(c) + (2000 if len(c) == 2 else 0)
                parsed = _safe_date(year, int(b), int(a)) or _safe_date(year, int(a), int(b))
            elif kind == "dmy":
                parsed = _safe_date(int(c), _MONTHS[b[:3].lower()], int(a))
            elif kind == "mdy":
                parsed = _safe_date(int(c), _MONTHS[a[:3].lower()], int(b))
            if parsed:
                found.append((match.start(), parsed))
    found.sort(key=lambda item: item[0])
    return [d for _, d in found]


# ----------------------------------------------------------------------------
# Text patterns used by the checks (wording only - no clinical meaning)
# ----------------------------------------------------------------------------
VAGUE_RE = re.compile(
    r"(?:\b(?:tbc|tbd|to be (?:confirmed|decided|arranged|determined|advised|scheduled|informed)|"
    r"as (?:advised|directed|needed|required|instructed|discussed|per (?:advice|instructions?|plan|prescription|chart|notes))|"
    r"if needed|when needed|see (?:notes|above|chart|file|prescription)|refer (?:to )?(?:notes|chart|file|prescription)|"
    r"will be informed|later|soon|usual|routine|general advice|take care|not decided|"
    r"not (?:yet )?(?:booked|scheduled|arranged|decided))\b|\?)",
    re.I,
)
TIMEFRAME_RE = re.compile(r"\b(?:in|after|within)\s+\d+|\b\d+\s*(?:day|week|month)s?\b|\bnext\s+(?:week|month)\b", re.I)

_GENERIC_NONE = {"none", "nil", "na", "n/a", "n a", "not applicable", "nothing", "nil known"}
_NONE_PATTERNS = {
    "pending_investigations": [
        r"no (?:\w+ ){0,3}pending(?: \w+){0,4}", r"nothing pending", r"none pending", r"nil pending",
        r"no (?:\w+ ){0,3}outstanding(?: \w+){0,3}",
        r"all (?:\w+ ){0,4}(?:reviewed|received|available|completed|back)(?: \w+){0,4}",
        r"none (?:at|on) (?:discharge|this time)",
    ],
    "medication_changes": [
        r"no (?:\w+ ){0,3}changes?(?: \w+){0,5}", r"nil changes?", r"unchanged(?: \w+){0,5}",
        r"(?:\w+ ){0,3}medications? (?:\w+ ){0,2}unchanged", r"no new medications?(?: \w+){0,3}",
    ],
    "follow_up": [
        r"no (?:further )?follow ?up(?: (?:is )?(?:required|needed|necessary|planned|advised))?",
        r"follow ?up (?:is )?not (?:required|needed|necessary)", r"not required",
    ],
    "medications": [r"no (?:\w+ ){0,2}medications?(?: \w+){0,4}", r"no (?:\w+ ){0,2}(?:medicines?|drugs?)(?: \w+){0,3}"],
    "patient_instructions": [],
    "discharge_date": [],
    "responsible_clinician": [],
}

PENDING_MENTION_RE = re.compile(
    r"\b(?:pending|awaited|awaiting|yet to be (?:received|reported|available)|"
    r"results? (?:to follow|not yet|outstanding)|reports? to follow)\b", re.I)
_CHANGE_VERBS = r"(?:increased|decreased|reduced|changed|stopped|discontinued|withheld|started|commenced|switched|adjusted)"
_DRUG_WORDS = r"(?:dose|dosage|tablet|medication|medicine|drug)s?"
MEDCHANGE_MENTION_RE = re.compile(
    r"\b" + _DRUG_WORDS + r"\b.{0,40}\b" + _CHANGE_VERBS + r"\b|\b" + _CHANGE_VERBS +
    r"\b.{0,40}\b" + _DRUG_WORDS + r"\b|\bnewly (?:started|added)\b|\bnew medication\b", re.I)

_TITLE_NAME_RE = re.compile(r"\b(?:Dr|Prof|Mr|Mrs|Ms|Miss)\.?\s+[A-Z][A-Za-z'\-]+")
_ROLE_WORDS = {
    "consultant", "doctor", "physician", "registrar", "resident", "duty", "ward", "team", "senior",
    "junior", "house", "officer", "surgeon", "cardiologist", "department", "on", "call", "signed", "by",
    "discharging", "clinician", "attending", "medical", "reg", "no",
}


def _normalise_for_none(value):
    cleaned = re.sub(r"[^a-z0-9/ ]", " ", (value or "").lower())
    return " ".join(cleaned.split())


def is_explicit_none(value, field_key):
    """True if the text explicitly says 'none / nil / not applicable' for this field."""
    norm = _normalise_for_none(value)
    if not norm:
        return False
    if norm in _GENERIC_NONE:
        return True
    return any(re.fullmatch(p, norm) for p in _NONE_PATTERNS.get(field_key, []))


def _words(value):
    return re.findall(r"[A-Za-z0-9]+", value or "")


def _has_name(value):
    if _TITLE_NAME_RE.search(value or ""):
        return True
    remaining = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", value or "") if w.lower() not in _ROLE_WORDS]
    capitalised = [w for w in remaining if w[0].isupper() and len(w) > 2]
    return len(capitalised) >= 2


def snippet(value, limit=300):
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


# ----------------------------------------------------------------------------
# One check per checklist item. Each returns (status, evidence, note).
# ----------------------------------------------------------------------------
def _check(key, value, is_empty, narrative_hit, clinician_mention):
    value = (value or "").strip()

    if is_empty and not value:
        return UNCLEAR, "", "The heading is present but nothing is written under it."

    if key == "discharge_date":
        if not value:
            return MISSING, "", "No discharge date was found in the document."
        if find_dates(value):
            return PRESENT, snippet(value), "A date is documented."
        return UNCLEAR, snippet(value), "Text is present but no readable date was found."

    if key == "follow_up":
        if not value:
            return MISSING, "", "No follow-up heading or follow-up wording was found."
        if is_explicit_none(value, key):
            return NOT_APPLICABLE, snippet(value), "The document explicitly states no follow-up."
        if find_dates(value):
            return PRESENT, snippet(value), "A follow-up date is documented."
        if TIMEFRAME_RE.search(value):
            return UNCLEAR, snippet(value), "Only a time period is given (no specific date)."
        return UNCLEAR, snippet(value), "Follow-up wording is present but no specific date was found."

    if key == "pending_investigations":
        if not value:
            if narrative_hit:
                return UNCLEAR, snippet(narrative_hit), (
                    "Wording elsewhere mentions pending/awaited results, but there is no explicit "
                    "pending-investigations statement.")
            return MISSING, "", "No pending-investigations statement (including 'none') was found."
        if is_explicit_none(value, key):
            return NOT_APPLICABLE, snippet(value), "Explicitly marked as none."
        words = _words(value)
        if len(words) < 4 or (VAGUE_RE.search(value) and len(words) < 8):
            return UNCLEAR, snippet(value), "The entry is too brief or non-specific to show which items are pending."
        return PRESENT, snippet(value), "Pending items are documented."

    if key == "medications":
        if not value:
            return MISSING, "", "No medication list was found."
        if is_explicit_none(value, key):
            return NOT_APPLICABLE, snippet(value), "Explicitly marked as no medications."
        words = _words(value)
        if len(words) < 2 or (VAGUE_RE.search(value) and len(words) < 8):
            return UNCLEAR, snippet(value), "The medication entry only refers elsewhere or is too brief to list medicines."
        return PRESENT, snippet(value), "A medication list is documented."

    if key == "medication_changes":
        if not value:
            if narrative_hit:
                return UNCLEAR, snippet(narrative_hit), (
                    "Wording elsewhere may refer to a medication change, but there is no explicit "
                    "medication-changes statement.")
            return MISSING, "", "No medication-changes statement (including 'none') was found."
        if is_explicit_none(value, key):
            return NOT_APPLICABLE, snippet(value), "Explicitly marked as none / unchanged."
        words = _words(value)
        if len(words) < 3 or (VAGUE_RE.search(value) and len(words) < 8):
            return UNCLEAR, snippet(value), "The entry is too brief or non-specific to show what changed."
        return PRESENT, snippet(value), "Medication changes are documented."

    if key == "patient_instructions":
        if not value:
            return MISSING, "", "No patient instructions were found."
        if is_explicit_none(value, key):
            return NOT_APPLICABLE, snippet(value), "Explicitly marked as none."
        words = _words(value)
        if len(words) < 5 or (VAGUE_RE.search(value) and len(words) < 25):
            return UNCLEAR, snippet(value), "Instructions are present but are general or non-specific."
        return PRESENT, snippet(value), "Patient instructions are documented."

    if key == "responsible_clinician":
        if not value:
            if clinician_mention:
                return UNCLEAR, snippet(clinician_mention), (
                    "A doctor's name appears in the text, but it is not labelled as the responsible clinician.")
            return MISSING, "", "No responsible clinician details were found."
        if _has_name(value):
            return PRESENT, snippet(value), "A named clinician is documented."
        return UNCLEAR, snippet(value), "A role is given but no clinician name was found."

    return MISSING, "", "Unknown checklist item."


# ----------------------------------------------------------------------------
# Public function
# ----------------------------------------------------------------------------
def validate(extraction):
    """Build the checklist result from an extraction dict (see agent.py).

    Returns a dict with: checklist, flags, completeness, missing, unclear,
    requires_review, counts.
    """
    fields = extraction.get("fields", {})
    empty_fields = set(extraction.get("empty_fields", []))
    hits = extraction.get("narrative_hits", {})
    sources = extraction.get("sources", {})

    checklist = {}
    for key, field_key, label in CHECKLIST:
        status, evidence, note = _check(
            key,
            fields.get(field_key, ""),
            field_key in empty_fields,
            hits.get("pending", "") if key == "pending_investigations" else hits.get("medication_change", ""),
            hits.get("clinician_mention", ""),
        )
        if sources.get(field_key) == "keyword" and status in (PRESENT, UNCLEAR):
            note += " (Found in free text, not under a heading.)"
        checklist[key] = {"label": label, "status": status, "evidence": evidence, "note": note}

    flags = _consistency_flags(extraction, checklist)

    ok = sum(1 for item in checklist.values() if item["status"] in (PRESENT, NOT_APPLICABLE))
    completeness = round(100.0 * ok / len(CHECKLIST))
    missing = [i["label"] for i in checklist.values() if i["status"] == MISSING]
    unclear = [i["label"] for i in checklist.values() if i["status"] == UNCLEAR]
    return {
        "checklist": checklist,
        "flags": flags,
        "completeness": completeness,
        "missing": missing,
        "unclear": unclear,
        "requires_review": bool(missing or unclear or flags),
    }


def _consistency_flags(extraction, checklist):
    """Wording/date consistency checks. These never judge clinical content."""
    fields = extraction.get("fields", {})
    hits = extraction.get("narrative_hits", {})
    flags = []

    discharge = (find_dates(fields.get("discharge_date", "")) or [None])[0]
    admission = (find_dates(fields.get("admission_date", "")) or [None])[0]
    follow_dates = find_dates(fields.get("follow_up", ""))

    if discharge and admission and discharge < admission:
        flags.append({
            "issue": "The discharge date is earlier than the admission date. Please verify the dates.",
            "evidence": snippet("Admission: %s | Discharge: %s" % (fields.get("admission_date", ""), fields.get("discharge_date", ""))),
        })
    if discharge and follow_dates and follow_dates[0] < discharge:
        flags.append({
            "issue": "The follow-up date is earlier than the discharge date. Please verify the dates.",
            "evidence": snippet(fields.get("follow_up", "")),
        })
    if checklist["medication_changes"]["status"] == NOT_APPLICABLE and hits.get("medication_change"):
        flags.append({
            "issue": "Medication changes are marked as none, but other wording in the document may refer to a change.",
            "evidence": snippet(hits["medication_change"]),
        })
    if checklist["pending_investigations"]["status"] == NOT_APPLICABLE and hits.get("pending"):
        flags.append({
            "issue": "Pending investigations are marked as none, but other wording in the document mentions pending/awaited results.",
            "evidence": snippet(hits["pending"]),
        })
    return flags
