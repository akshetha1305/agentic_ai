"""reports.py - builds CSV and text reports from analysis records."""
import io
import json

import pandas as pd

import agent
import validator


def summary_dataframe(results):
    """One row per document."""
    rows = []
    for rec in results:
        row = {
            "File": rec["file_name"],
            "Patient ID": rec["patient_id"],
            "Department": rec["department"],
            "Discharge date": rec["fields"].get("discharge_date", "").split("\n")[0],
            "Completeness %": rec["completeness"],
            "Result": validator.REVIEW_MESSAGE if rec["requires_review"] else "Checklist complete",
        }
        for key, item in rec["checklist"].items():
            row[item["label"]] = item["status"]
        row["Missing items"] = "; ".join(rec["missing"])
        row["Unclear items"] = "; ".join(rec["unclear"])
        row["Consistency flags"] = "; ".join(f["issue"] for f in rec["flags"])
        rows.append(row)
    return pd.DataFrame(rows)


def detail_dataframe(results):
    """One row per document per checklist category (includes evidence)."""
    rows = []
    for rec in results:
        for key, item in rec["checklist"].items():
            rows.append({
                "File": rec["file_name"],
                "Patient ID": rec["patient_id"],
                "Department": rec["department"],
                "Category": item["label"],
                "Status": item["status"],
                "Evidence from document": item["evidence"],
                "Note": item["note"],
            })
    return pd.DataFrame(rows)


def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def build_text_report(rec):
    """A plain-text completeness report for one document."""
    line = "=" * 70
    out = [
        line,
        "DISCHARGECHECK - DOCUMENTATION COMPLETENESS REPORT",
        line,
        "Document      : %s" % rec["file_name"],
        "Analysed at   : %s" % rec["analysed_at"],
        "Read by       : %s | Analysis: %s" % (rec["extraction_method"], rec["analysis_method"]),
        "Patient ID    : %s" % rec["patient_id"],
        "Department    : %s" % rec["department"],
        "Completeness : %s%%" % rec["completeness"],
        "Result        : %s" % (validator.REVIEW_MESSAGE if rec["requires_review"] else "Checklist complete"),
        "",
        "CHECKLIST",
        "-" * 70,
    ]
    for item in rec["checklist"].values():
        out.append("[%s] %s" % (item["status"].upper(), item["label"]))
        out.append("    Note    : %s" % item["note"])
        if item["evidence"]:
            out.append("    Evidence: %s" % item["evidence"])
    if rec["flags"]:
        out += ["", "CONSISTENCY FLAGS", "-" * 70]
        for flag in rec["flags"]:
            out.append("* %s" % flag["issue"])
            out.append("    Evidence: %s" % flag["evidence"])
    if rec["missing"] or rec["unclear"]:
        out += ["", "ITEMS FOR THE RESPONSIBLE CLINICIAN TO CORRECT", "-" * 70]
        for label in rec["missing"]:
            out.append("- MISSING: %s" % label)
        for label in rec["unclear"]:
            out.append("- UNCLEAR: %s" % label)
    if rec["warnings"]:
        out += ["", "PROCESSING NOTES", "-" * 70] + ["- %s" % w for w in rec["warnings"]]
    out += ["", line, validator.DISCLAIMER, line]
    return "\n".join(out)


def build_json_report(rec):
    return json.dumps(agent.to_json_structure(rec), indent=2, ensure_ascii=False)
