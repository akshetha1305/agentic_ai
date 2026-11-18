"""agent.py - reads discharge text and produces a structured analysis.

Two extraction modes:
  1. Rule-based (default, no API key needed): finds headings such as
     "Follow-up:", "Discharge Medications:", "Patient Instructions:" and copies the text under them.
  2. Optional LLM (Anthropic API): helps with documents that have no clear headings.
     Every value the LLM returns must be found word-for-word in the document,
     otherwise it is ignored. If anything goes wrong, the rule-based result is used.

The agent only COPIES text out of the document. It never writes clinical content,
never fills in missing items and never changes medication text.
"""
import json
import re
from datetime import datetime

import validator

FIELD_KEYS = [
    "patient_id", "department", "admission_date", "discharge_date", "follow_up",
    "pending_investigations", "medications_as_written", "medication_changes",
    "patient_instructions", "responsible_clinician",
]

FIELD_LABELS = {
    "patient_id": "Patient ID",
    "department": "Department",
    "admission_date": "Admission date",
    "discharge_date": "Discharge date",
    "follow_up": "Follow-up appointment",
    "pending_investigations": "Pending investigations",
    "medications_as_written": "Medication list (as written)",
    "medication_changes": "Medication changes",
    "patient_instructions": "Patient instructions",
    "responsible_clinician": "Responsible clinician",
}

# Heading words that belong to each field. Headings that map to None only end a section.
HEADING_ALIASES = {
    "patient_id": ["patient id", "patient no", "uhid", "mrn", "ip no", "hospital number"],
    "department": ["department", "specialty", "speciality", "unit", "service"],
    "admission_date": ["admission date", "date of admission", "admitted on", "doa"],
    "discharge_date": ["discharge date", "date of discharge", "discharged on", "dod"],
    "follow_up": ["follow-up appointment", "follow-up", "follow up", "followup", "follow-up plan",
                  "follow-up details", "next appointment", "review"],
    "pending_investigations": ["pending investigations", "pending investigation", "pending tests",
                               "pending results", "investigations pending", "results pending",
                               "pending reports", "tests pending"],
    "medications_as_written": ["discharge medications", "discharge medication", "medications on discharge",
                               "medication on discharge", "medication list", "medications", "medicines",
                               "drugs on discharge", "treatment on discharge", "medicines on discharge"],
    "medication_changes": ["medication changes", "medication changes at discharge", "changes to medication",
                           "changes in medication", "changes to medications", "medicine changes",
                           "medication changes during admission"],
    "patient_instructions": ["patient instructions", "discharge instructions", "instructions to patient",
                             "instructions for patient", "advice on discharge", "patient advice",
                             "advice to patient", "instructions", "advice"],
    "responsible_clinician": ["responsible clinician", "discharging clinician", "discharging doctor",
                              "consultant in charge", "treating doctor", "treating consultant", "consultant",
                              "attending physician", "attending", "signed by", "prepared by", "doctor"],
    None: ["patient name", "name", "age", "sex", "gender", "age/sex", "diagnosis", "final diagnosis",
           "primary diagnosis", "provisional diagnosis", "presenting complaint", "presenting complaints",
           "chief complaint", "history", "hospital course", "course in hospital", "clinical summary",
           "summary", "investigations", "procedure", "procedures", "procedure performed",
           "condition at discharge", "condition on discharge", "allergies", "discharge summary",
           "hospital", "date", "signature", "operation", "surgery"],
}


def _squash(text):
    """lower-case and remove everything except letters/digits, so 'Follow-Up' == 'follow up'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


_ALIAS_TO_KEY = {}
_ALIAS_PATTERNS = []
for _key, _aliases in HEADING_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_KEY[_squash(_alias)] = _key
        _parts = [re.escape(p) for p in re.findall(r"[A-Za-z0-9]+", _alias)]
        _ALIAS_PATTERNS.append((len(_alias), r"[\s_\-/]*".join(_parts)))
_ALIAS_PATTERNS.sort(reverse=True)
_HEADING_RE = re.compile(
    r"^(?P<h>" + "|".join(p for _, p in _ALIAS_PATTERNS) + r")\s*(?:[:;]\s*(?P<rest>.*))?$", re.I)

FOLLOWUP_MENTION_RE = re.compile(
    r"\b(?:follow[\s\-]?up|review (?:on|in|at)|next appointment|appointment (?:on|with|at)|opd (?:visit|on|review))\b", re.I)
DOCTOR_MENTION_RE = re.compile(r"\bDr\.?\s+[A-Z][A-Za-z'\-]+")
PATIENT_ID_RE = re.compile(r"\b(?:SYN|PT|UHID|MRN|IP|OP)[\-\s:#]?\d{3,}\b", re.I)
DEPARTMENT_NAMES = [
    "General Medicine", "Cardiology", "Orthopaedics", "Orthopedics", "Neurology", "General Surgery",
    "Paediatrics", "Pediatrics", "Obstetrics", "Gynaecology", "Oncology", "Nephrology", "Gastroenterology",
    "Pulmonology", "Respiratory Medicine", "Urology", "ENT", "Ophthalmology", "Psychiatry", "Dermatology",
    "Emergency Medicine", "Surgery", "Medicine",
]
PRIVACY_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b(?:\+?\d{1,3}[\s-]?)?\d{10}\b")


# ----------------------------------------------------------------------------
# Rule-based extraction
# ----------------------------------------------------------------------------
def parse_sections(text):
    """Split the document into sections. Returns a list of {'key', 'lines'}.

    The first section (key None) holds anything before the first heading.
    """
    current = {"key": None, "lines": [], "has_heading": False}
    sections = [current]
    for raw in text.splitlines():
        cleaned = re.sub(r"[*#]+", "", raw).strip()
        cleaned = re.sub(r"^(?:\d+[.)]|[-\u2022>])\s+", "", cleaned)
        match = _HEADING_RE.match(cleaned) if cleaned else None
        if match:
            key = _ALIAS_TO_KEY.get(_squash(match.group("h")))
            current = {"key": key, "lines": [], "has_heading": True}
            sections.append(current)
            rest = (match.group("rest") or "").strip()
            if rest:
                current["lines"].append(rest)
        else:
            current["lines"].append(raw.rstrip())
    return sections


def _first_match(lines, pattern):
    for line in lines:
        if pattern.search(line):
            return line.strip()
    return ""


def extract_with_rules(text):
    """Copy the text under each recognised heading. Returns an extraction dict."""
    sections = parse_sections(text)
    fields = {key: "" for key in FIELD_KEYS}
    sources = {}
    empty_fields = []

    for key in FIELD_KEYS:
        matching = [s for s in sections if s["key"] == key and s["has_heading"]]
        if not matching:
            continue
        value = "\n".join("\n".join(s["lines"]).strip() for s in matching).strip()
        fields[key] = value
        sources[key] = "heading"
        if not value:
            empty_fields.append(key)

    # Lines that are NOT under a recognised heading (hospital course, diagnosis, preamble ...)
    narrative = [line for s in sections if s["key"] is None for line in s["lines"] if line.strip()]

    # Light keyword fallbacks, only when there was no heading at all
    if not fields["patient_id"]:
        match = PATIENT_ID_RE.search(text)
        if match:
            fields["patient_id"], sources["patient_id"] = match.group(0), "keyword"
    if not fields["department"] and "department" not in empty_fields:
        for name in DEPARTMENT_NAMES:
            match = re.search(r"\b" + re.escape(name) + r"\b", text, re.I)
            if match:
                fields["department"], sources["department"] = match.group(0), "keyword"
                break
    if not fields["discharge_date"] and "discharge_date" not in empty_fields:
        for line in narrative:
            if re.search(r"discharg", line, re.I) and validator.find_dates(line):
                fields["discharge_date"], sources["discharge_date"] = line.strip(), "keyword"
                break
    if not fields["follow_up"] and "follow_up" not in empty_fields:
        mentions = [l.strip() for l in narrative if FOLLOWUP_MENTION_RE.search(l)][:2]
        if mentions:
            fields["follow_up"], sources["follow_up"] = "\n".join(mentions), "keyword"

    hits = {
        "pending": _first_match(narrative, validator.PENDING_MENTION_RE),
        "medication_change": _first_match(narrative, validator.MEDCHANGE_MENTION_RE),
        "clinician_mention": _first_match(narrative, DOCTOR_MENTION_RE),
    }
    return {
        "fields": fields,
        "sources": sources,
        "empty_fields": empty_fields,
        "narrative_hits": hits,
        "method": "Rule-based",
        "warnings": [],
    }


# ----------------------------------------------------------------------------
# Optional LLM extraction (Anthropic). Never required.
# ----------------------------------------------------------------------------
LLM_SYSTEM_PROMPT = """You are a text-extraction tool for hospital discharge summaries.
Your ONLY job is to COPY text from the document into JSON fields.

Strict rules:
- Copy text exactly as written in the document. Do not rephrase, correct, translate, summarise or tidy it.
- Copy medication text exactly as written: names, doses, frequencies, line breaks.
- If an item is not written in the document, return an empty string "". Never guess or invent.
- Never create or suggest follow-up dates, tests, medications, doses, diagnoses or advice.
- Do not interpret laboratory results or any clinical content.
- If the document explicitly says something like "None" or "Not applicable", copy that wording.

Return ONLY a JSON object with these string keys:
patient_id, department, admission_date, discharge_date, follow_up, pending_investigations,
medications_as_written, medication_changes, patient_instructions, responsible_clinician"""


def _norm(text):
    return " ".join((text or "").lower().split())


def _json_from_reply(raw):
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("The model reply did not contain a JSON object.")
    return json.loads(raw[start:end + 1])


def _keep_verbatim(value, text_norm):
    """Return only the part of the LLM value that appears word-for-word in the document."""
    if not isinstance(value, str) or not value.strip():
        return ""
    if _norm(value) in text_norm:
        return value.strip()
    kept = [line for line in value.splitlines() if line.strip() and _norm(line) in text_norm]
    return "\n".join(kept).strip()


def extract_with_llm(text, api_key, model):
    """Ask the LLM for the fields. Returns a dict of verified (verbatim) values."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("The 'anthropic' package is not installed (pip install anthropic).")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=2500,
        system=LLM_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "DISCHARGE DOCUMENT:\n\n" + text[:30000]}],
    )
    raw = "".join(getattr(block, "text", "") for block in message.content)
    data = _json_from_reply(raw)
    text_norm = _norm(text)
    verified, rejected = {}, []
    for key in FIELD_KEYS:
        value = _keep_verbatim(data.get(key, ""), text_norm)
        if not value and isinstance(data.get(key), str) and data.get(key).strip():
            rejected.append(FIELD_LABELS[key])
        verified[key] = value
    return verified, rejected


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def analyse_document(file_name, text, extraction_method="", extraction_warnings=None,
                     use_llm=False, api_key="", model="claude-sonnet-5-5"):
    """Analyse one document and return a result record (a plain dict)."""
    extraction = extract_with_rules(text)
    warnings = list(extraction_warnings or [])

    if use_llm and api_key:
        try:
            verified, rejected = extract_with_llm(text, api_key, model)
            for key, value in verified.items():
                if value:
                    extraction["fields"][key] = value
                    extraction["sources"][key] = "llm"
                    if key in extraction["empty_fields"]:
                        extraction["empty_fields"].remove(key)
            extraction["method"] = "LLM + rules"
            if rejected:
                warnings.append(
                    "LLM text that could not be matched word-for-word to the document was ignored for: "
                    + ", ".join(rejected) + ".")
        except Exception as exc:  # noqa: BLE001 - any API/parse problem -> use rules only
            warnings.append("LLM extraction failed, so rule-based extraction was used instead (%s)." % exc)

    if PRIVACY_RE.search(text):
        warnings.append(
            "The text contains something that looks like a phone number or e-mail address. "
            "Use synthetic or de-identified documents only.")

    result = validator.validate(extraction)
    fields = extraction["fields"]
    return {
        "file_name": file_name,
        "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "extraction_method": extraction_method,
        "analysis_method": extraction["method"],
        "patient_id": fields["patient_id"] or "Not found",
        "department": (fields["department"].splitlines() or ["Unknown"])[0].strip() or "Unknown",
        "fields": fields,
        "sources": extraction["sources"],
        "checklist": result["checklist"],
        "flags": result["flags"],
        "completeness": result["completeness"],
        "missing": result["missing"],
        "unclear": result["unclear"],
        "requires_review": result["requires_review"],
        "warnings": warnings,
        "text": text,
    }


def to_json_structure(record):
    """The JSON layout described in the project brief (fields + checklist statuses)."""
    fields = record["fields"]
    return {
        "patient_id": record["patient_id"],
        "department": record["department"],
        "discharge_date": fields["discharge_date"],
        "follow_up": fields["follow_up"],
        "pending_investigations": fields["pending_investigations"],
        "medications_as_written": fields["medications_as_written"],
        "medication_changes": fields["medication_changes"],
        "patient_instructions": fields["patient_instructions"],
        "responsible_clinician": fields["responsible_clinician"],
        "checklist": {key: item["status"] for key, item in record["checklist"].items()},
        "completeness_percent": record["completeness"],
        "requires_clinician_review": record["requires_review"],
    }
