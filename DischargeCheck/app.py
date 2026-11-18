"""app.py - DischargeCheck Streamlit interface.

Run with:  streamlit run app.py
"""
import html
import os
from pathlib import Path

import streamlit as st

import agent
import dashboard
import extraction
import reports
import validator

APP_DIR = Path(__file__).parent
SAMPLE_DIR = APP_DIR / "sample_data"
PAGES = ["Dashboard", "Upload Documents", "Document Analysis", "Completeness Report", "Reports"]

st.set_page_config(page_title="DischargeCheck", page_icon="\U0001FA7A", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; max-width: 1250px;}
    .dc-header {background: linear-gradient(90deg, #1E6FD9 0%, #4A90E2 100%); color: white;
                padding: 18px 24px; border-radius: 12px; margin-bottom: 14px;}
    .dc-header h1 {color: white; margin: 0; font-size: 1.9rem;}
    .dc-header p {color: #E8F1FD; margin: 4px 0 0 0;}
    [data-testid="stMetric"] {background: #F3F6FA; border: 1px solid #DCE4EF; border-radius: 10px; padding: 12px 16px;}
    .dc-badge {display: inline-block; padding: 3px 12px; border-radius: 12px; font-weight: 600; font-size: 0.85rem;}
    .dc-Present {background: #DDF3E4; color: #1B7F3B;}
    .dc-Missing {background: #FBE0DA; color: #B3361A;}
    .dc-Unclear {background: #FDEFCF; color: #9A6200;}
    .dc-NotApplicable {background: #E3E8EF; color: #4A5568;}
    .dc-evidence {background: #F3F6FA; border-left: 4px solid #1E6FD9; padding: 6px 10px; border-radius: 4px;
                  font-size: 0.9rem; white-space: pre-wrap;}
    .dc-review {background: #FDEFCF; border: 1px solid #F5C469; color: #7A4B00; padding: 10px 14px;
                border-radius: 8px; font-weight: 600;}
    .dc-ok {background: #DDF3E4; border: 1px solid #9BD6AF; color: #1B7F3B; padding: 10px 14px;
            border-radius: 8px; font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# State helpers
# ----------------------------------------------------------------------------
def init_state():
    st.session_state.setdefault("results", {})       # file name -> analysis record
    st.session_state.setdefault("status_log", [])    # list of {"File", "Status", "Detail"}


def results_list():
    return list(st.session_state["results"].values())


def process_file(name, data, settings):
    """Read and analyse one file. Never raises; failures go into the status log."""
    try:
        read = extraction.extract_text(name, data)
        record = agent.analyse_document(
            name, read.text,
            extraction_method=read.method,
            extraction_warnings=read.warnings,
            use_llm=settings["use_llm"], api_key=settings["api_key"], model=settings["model"],
        )
        st.session_state["results"][name] = record
        detail = "%s | %s | %s%% complete" % (read.method, record["analysis_method"], record["completeness"])
        st.session_state["status_log"].append({"File": name, "Status": "Analysed", "Detail": detail})
    except extraction.ExtractionError as exc:
        st.session_state["status_log"].append({"File": name, "Status": "Failed", "Detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - keep the app alive whatever happens
        st.session_state["status_log"].append(
            {"File": name, "Status": "Failed", "Detail": "Unexpected error: %s" % exc})


def run_batch(items, settings):
    """items: list of (name, bytes). Shows a progress bar while processing."""
    progress = st.progress(0.0, text="Starting...")
    for index, (name, data) in enumerate(items, start=1):
        progress.progress((index - 1) / len(items), text="Processing %s (%d of %d)" % (name, index, len(items)))
        process_file(name, data, settings)
    progress.progress(1.0, text="Done")


def badge(status):
    css = "dc-" + status.replace(" ", "")
    return '<span class="dc-badge %s">%s</span>' % (css, html.escape(status))


def evidence_box(text):
    if not text:
        return '<div class="dc-evidence" style="border-left-color:#B0B8C4;">No supporting text in the document.</div>'
    return '<div class="dc-evidence">%s</div>' % html.escape(text)


def need_results():
    if not st.session_state["results"]:
        st.info("No documents analysed yet. Go to **Upload Documents** and analyse a file or load the sample documents.")
        return False
    return True


def pick_document(key):
    names = list(st.session_state["results"].keys())
    return st.session_state["results"][st.selectbox("Choose a document", names, key=key)]


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_dashboard():
    st.subheader("Dashboard")
    if not need_results():
        return
    results = results_list()
    m = dashboard.summary_metrics(results)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents analysed", m["total"])
    c2.metric("Complete documents", m["complete"])
    c3.metric("Requiring clinician review", m["needs_review"])
    c4.metric("Average completeness", "%s%%" % m["average"])

    left, right = st.columns(2)
    with left:
        st.plotly_chart(dashboard.pie_figure(results))
    with right:
        bar = dashboard.missing_bar_figure(results)
        if bar is None:
            st.success("No missing or unclear categories in the analysed documents.")
        else:
            st.plotly_chart(bar)

    st.markdown("##### Department-wise statistics")
    dept_left, dept_right = st.columns([1, 1])
    with dept_left:
        st.dataframe(dashboard.department_table(results), hide_index=True)
    with dept_right:
        dept_bar = dashboard.department_bar_figure(results)
        if dept_bar is not None:
            st.plotly_chart(dept_bar)

    st.markdown("##### Documents")
    st.dataframe(reports.summary_dataframe(results)[
        ["File", "Patient ID", "Department", "Completeness %", "Result", "Missing items", "Unclear items"]],
        hide_index=True)


def page_upload(settings):
    st.subheader("Upload Documents")
    st.write("Upload synthetic or de-identified discharge documents (PDF, DOCX, TXT, JPG, PNG). "
             "Typed and scanned documents are both supported.")

    uploaded = st.file_uploader(
        "Choose one or more documents", type=extraction.SUPPORTED_EXTENSIONS, accept_multiple_files=True)

    b1, b2, b3 = st.columns([1, 1, 1])
    analyse = b1.button("Analyse uploaded documents", type="primary", disabled=not uploaded)
    load_samples = b2.button("Load sample documents")
    clear = b3.button("Clear all results")

    if clear:
        st.session_state["results"] = {}
        st.session_state["status_log"] = []
        st.success("All results cleared.")

    if analyse and uploaded:
        st.session_state["status_log"] = []
        run_batch([(f.name, f.getvalue()) for f in uploaded], settings)

    if load_samples:
        st.session_state["status_log"] = []
        files = sorted(SAMPLE_DIR.glob("*.txt"))
        if not files:
            st.error("The sample_data folder has no sample documents.")
        else:
            run_batch([(p.name, p.read_bytes()) for p in files], settings)

    if st.session_state["status_log"]:
        st.markdown("##### Processing status")
        st.dataframe(st.session_state["status_log"], hide_index=True)
        failed = [row for row in st.session_state["status_log"] if row["Status"] == "Failed"]
        done = len(st.session_state["status_log"]) - len(failed)
        if done:
            st.success("%d document(s) analysed. Open **Dashboard** or **Completeness Report** in the sidebar." % done)
        if failed:
            st.warning("%d file(s) could not be processed. See the status table for the reason." % len(failed))


def page_analysis():
    st.subheader("Document Analysis")
    st.caption("Text below is copied from the document. Nothing is added, corrected or interpreted.")
    if not need_results():
        return
    rec = pick_document("analysis_doc")
    fields = rec["fields"]

    a, b, c = st.columns(3)
    a.metric("Patient ID", rec["patient_id"])
    b.metric("Department", rec["department"])
    c.metric("Discharge date", fields["discharge_date"].split("\n")[0] or "Not documented")

    for warning in rec["warnings"]:
        st.warning(warning)

    sections = [
        ("follow_up", "Follow-up appointment details"),
        ("pending_investigations", "Pending investigations"),
        ("medications_as_written", "Medication list (exactly as written)"),
        ("medication_changes", "Medication changes"),
        ("patient_instructions", "Patient instructions"),
        ("responsible_clinician", "Responsible clinician"),
    ]
    for key, title in sections:
        st.markdown("**%s**" % title)
        if fields[key]:
            st.code(fields[key], language=None)
        else:
            st.markdown('<div class="dc-evidence" style="border-left-color:#B0B8C4;">Not documented</div>',
                        unsafe_allow_html=True)

    with st.expander("View full text read from the document"):
        st.text(rec["text"])
    st.caption("Read by: %s | Analysis: %s" % (rec["extraction_method"], rec["analysis_method"]))


def page_report():
    st.subheader("Completeness Report")
    if not need_results():
        return
    rec = pick_document("report_doc")

    top_left, top_right = st.columns([1, 2])
    with top_left:
        st.metric("Completeness", "%s%%" % rec["completeness"])
        st.progress(rec["completeness"] / 100.0)
    with top_right:
        st.markdown("**%s** | %s | %s" % (rec["file_name"], rec["patient_id"], rec["department"]))
        if rec["requires_review"]:
            st.markdown('<div class="dc-review">%s</div>' % validator.REVIEW_MESSAGE, unsafe_allow_html=True)
        else:
            st.markdown('<div class="dc-ok">All checklist items are documented.</div>', unsafe_allow_html=True)
        if rec["missing"]:
            st.markdown("**Missing:** " + "; ".join(rec["missing"]))
        if rec["unclear"]:
            st.markdown("**Unclear:** " + "; ".join(rec["unclear"]))

    st.markdown("##### Checklist")
    for item in rec["checklist"].values():
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown("**%s**" % item["label"])
            right.markdown(badge(item["status"]), unsafe_allow_html=True)
            st.caption(item["note"])
            st.markdown(evidence_box(item["evidence"]), unsafe_allow_html=True)

    if rec["flags"]:
        st.markdown("##### Consistency flags")
        for flag in rec["flags"]:
            st.warning(flag["issue"])
            st.markdown(evidence_box(flag["evidence"]), unsafe_allow_html=True)

    if rec["missing"] or rec["unclear"] or rec["flags"]:
        st.markdown("##### Items for the responsible clinician to correct")
        for label in rec["missing"]:
            st.markdown("- **Missing:** %s" % label)
        for label in rec["unclear"]:
            st.markdown("- **Unclear:** %s" % label)
        for flag in rec["flags"]:
            st.markdown("- **Inconsistent:** %s" % flag["issue"])


def page_reports():
    st.subheader("Reports")
    if not need_results():
        return
    results = results_list()
    summary = reports.summary_dataframe(results)
    detail = reports.detail_dataframe(results)

    st.markdown("##### Results for every analysed document")
    st.dataframe(summary, hide_index=True)

    d1, d2 = st.columns(2)
    d1.download_button("Download summary CSV", reports.to_csv_bytes(summary),
                       file_name="dischargecheck_summary.csv", mime="text/csv")
    d2.download_button("Download detailed CSV (with evidence)", reports.to_csv_bytes(detail),
                       file_name="dischargecheck_detailed.csv", mime="text/csv")

    st.markdown("##### Individual report")
    rec = pick_document("reports_doc")
    base = Path(rec["file_name"]).stem
    text_report = reports.build_text_report(rec)
    st.text(text_report)
    e1, e2 = st.columns(2)
    e1.download_button("Download this report (TXT)", text_report.encode("utf-8"),
                       file_name="%s_report.txt" % base, mime="text/plain")
    e2.download_button("Download this report (JSON)", reports.build_json_report(rec).encode("utf-8"),
                       file_name="%s_report.json" % base, mime="application/json")


# ----------------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------------
def main():
    init_state()

    st.markdown(
        '<div class="dc-header"><h1>\U0001FA7A DischargeCheck</h1>'
        "<p>Discharge documentation completeness agent</p></div>",
        unsafe_allow_html=True,
    )
    st.info(validator.DISCLAIMER)

    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio("Go to", PAGES, label_visibility="collapsed")
        st.markdown("---")
        st.markdown("### Analysis mode")
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        use_llm = st.checkbox("Use LLM extraction (optional)", value=False,
                              help="Needs the 'anthropic' package and an API key. The app works without it.")
        api_key = env_key
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        if use_llm:
            api_key = st.text_input("Anthropic API key", value=env_key, type="password")
            model = st.text_input("Model", value=model)
            if not api_key:
                st.caption("No key entered - rule-based extraction will be used.")
        else:
            st.caption("Rule-based extraction (no API key needed).")
        st.markdown("---")
        st.caption("Use synthetic or de-identified documents only.")
        st.caption("Documents analysed: %d" % len(st.session_state["results"]))

    settings = {"use_llm": use_llm, "api_key": api_key, "model": model}

    if page == "Dashboard":
        page_dashboard()
    elif page == "Upload Documents":
        page_upload(settings)
    elif page == "Document Analysis":
        page_analysis()
    elif page == "Completeness Report":
        page_report()
    else:
        page_reports()

    st.markdown("---")
    st.caption(validator.DISCLAIMER)


main()
