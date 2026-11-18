# DischargeCheck - Discharge Documentation Completeness Agent

> This tool checks documentation completeness only. It does not provide clinical advice or replace clinician review.

Upload synthetic or de-identified discharge summaries (PDF, DOCX, TXT, JPG, PNG; typed or scanned).
The app copies out the follow-up details, pending investigations, medication list (exactly as written),
medication changes, patient instructions and responsible clinician, checks them against a 7-item
hospital documentation checklist, and shows a per-document report plus a department dashboard.

It never interprets clinical content, suggests treatment, changes medication text or invents missing dates.

## Quick start (Windows PowerShell)

```powershell
# 1. Go to the project folder (adjust the path)
cd C:\path\to\DischargeCheck

# 2. Create and activate a virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1
#    If activation is blocked, run this once and try again:
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Install the dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Run the app (opens http://localhost:8501)
streamlit run app.py
```

Then open **Upload Documents** and click **Load sample documents**.

## Tesseract OCR (only for scanned PDFs and JPG/PNG images)

Typed PDF, DOCX and TXT files work without it. For scans:

```powershell
winget install UB-Mannheim.TesseractOCR
```
(or use the installer from https://github.com/UB-Mannheim/tesseract/wiki), then **close and reopen PowerShell**
and run the app again. The app also looks in `C:\Program Files\Tesseract-OCR\`, so PATH changes are not required.
Try it with `sample_data/scanned_example_orthopaedics.png`.

## Optional: LLM extraction

The app works fully without an API key (rule-based mode). To also use an LLM for documents without clear headings:

```powershell
pip install anthropic
$env:ANTHROPIC_API_KEY = "your-key-here"
streamlit run app.py
```
Tick **Use LLM extraction** in the sidebar. Safety design: every value returned by the LLM must appear word-for-word
in the document, otherwise it is discarded; if the API fails, the rule-based result is used.

## Project structure

```
DischargeCheck/
  app.py            Streamlit interface (5 pages)
  extraction.py     PDF / DOCX / TXT / image -> text (PyMuPDF, python-docx, Tesseract OCR)
  agent.py          Field extraction (rule-based + optional LLM) and analysis record
  validator.py      Checklist, statuses, evidence, consistency flags, completeness score
  dashboard.py      Statistics (pandas) and charts (Plotly)
  reports.py        CSV and individual TXT/JSON reports
  sample_data/      3 synthetic discharge summaries + 1 scanned example image
  .streamlit/config.toml   Blue/white/grey theme
  requirements.txt
```

## How it works

1. **Read** the file to text (OCR for scans).
2. **Extract** by finding headings such as `Follow-up:`, `Pending Investigations:`, `Discharge Medications:`.
3. **Validate** in plain code (no AI judgement): each of the 7 checklist items becomes
   **Present**, **Missing**, **Unclear** or **Not applicable**, with the supporting text as evidence.
4. **Report**: completeness % = (Present + Not applicable) / 7. Anything Missing/Unclear/inconsistent shows
   **"Requires clinician review"**.

| Status | Meaning |
|---|---|
| Present | Documented (a follow-up counts only if it has a specific date) |
| Missing | Nothing about it in the document |
| Unclear | Something is written but is vague, empty, time-period only, or only mentioned in passing |
| Not applicable | The document explicitly says none / not applicable |

Consistency flags (documentation only): discharge date before admission date, follow-up date before discharge date,
"none" marked for pending tests or medication changes while other text mentions them.

## Sample documents

| File | Department | Expected result |
|---|---|---|
| 01_general_medicine_discharge.txt | General Medicine | 100% - all items documented |
| 02_cardiology_discharge.txt | Cardiology | 71% - follow-up and medication changes Missing |
| 03_orthopaedics_discharge.txt | Orthopaedics | 71% - pending investigations Missing, patient instructions Unclear |

## Limitations

- Rule-based extraction relies on headings; unusual layouts may show as Missing/Unclear (use the LLM option or edit the heading lists in `agent.py`).
- OCR quality depends on scan quality; the app shows the text it read so you can verify evidence.
- Dates are read day-first (31/12/2025); ambiguous formats like 03/04/2025 are treated as 3 April.
- Results are kept in memory only and reset when the browser session ends.

## Troubleshooting

| Problem | Fix |
|---|---|
| `streamlit` not recognised | Activate the venv (`.\.venv\Scripts\Activate.ps1`) or use `python -m streamlit run app.py` |
| "Tesseract OCR is not installed" | Install Tesseract (above), reopen PowerShell |
| Port already in use | `streamlit run app.py --server.port 8502` |
| PyMuPDF install fails | `python -m pip install --upgrade pip` then reinstall; use Python 3.9-3.13 |
