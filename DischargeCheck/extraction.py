"""extraction.py - turns an uploaded file into plain text.

Supported: PDF (typed or scanned), DOCX, TXT, JPG/JPEG, PNG.
Scanned pages and images are read with Tesseract OCR (pytesseract).
"""
import io
import os
import shutil
from dataclasses import dataclass, field

SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt", "jpg", "jpeg", "png"]

WINDOWS_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

TESSERACT_HELP = (
    "Tesseract OCR is not installed (or not on PATH). It is only needed for scanned PDFs "
    "and JPG/PNG images. Install it from https://github.com/UB-Mannheim/tesseract/wiki "
    "and restart the terminal. Typed PDF, DOCX and TXT files work without it."
)


class ExtractionError(Exception):
    """Raised when a file cannot be read. The message is safe to show to the user."""


@dataclass
class ExtractionResult:
    text: str
    method: str
    warnings: list = field(default_factory=list)


# ----------------------------------------------------------------------------
# OCR
# ----------------------------------------------------------------------------
def _prepare_tesseract(pytesseract):
    """Find tesseract.exe on Windows if it is installed but not on PATH."""
    if shutil.which("tesseract"):
        return
    for path in WINDOWS_TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return


def ocr_image(image):
    """Run OCR on a PIL image and return the text."""
    try:
        import pytesseract
    except ImportError:
        raise ExtractionError("pytesseract is not installed. Run: pip install pytesseract")
    _prepare_tesseract(pytesseract)
    try:
        gray = image.convert("L")
        if gray.width < 1500:  # small scans OCR better when enlarged
            factor = 1500 / float(gray.width)
            gray = gray.resize((int(gray.width * factor), int(gray.height * factor)))
        return pytesseract.image_to_string(gray)
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "TesseractNotFoundError":
            raise ExtractionError(TESSERACT_HELP)
        raise ExtractionError("OCR failed: %s" % exc)


# ----------------------------------------------------------------------------
# Readers
# ----------------------------------------------------------------------------
def _read_txt(data):
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ExtractionError("Could not decode the text file.")


def _read_pdf(data):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ExtractionError("PyMuPDF is not installed. Run: pip install pymupdf")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("Could not open the PDF (it may be corrupted): %s" % exc)

    pages, warnings, ocr_pages = [], [], 0
    try:
        if getattr(doc, "needs_pass", False):
            raise ExtractionError("The PDF is password protected.")
        for number, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if len(text) < 20:  # looks like a scanned page -> OCR it
                try:
                    from PIL import Image

                    pixmap = page.get_pixmap(dpi=200)
                    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                    text = ocr_image(image).strip()
                    ocr_pages += 1
                except ExtractionError as exc:
                    warnings.append("Page %d has no text layer and OCR was not possible: %s" % (number, exc))
                    text = ""
            pages.append(text)
    finally:
        doc.close()

    method = "PDF text"
    if ocr_pages:
        method = "PDF + OCR (%d scanned page%s)" % (ocr_pages, "" if ocr_pages == 1 else "s")
    return "\n\n".join(p for p in pages if p), method, warnings


def _read_docx(data):
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        raise ExtractionError("python-docx is not installed. Run: pip install python-docx")
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("Could not open the DOCX file (it may be corrupted): %s" % exc)

    lines = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(child, document).text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells = []
                for cell in row.cells:
                    value = " ".join(cell.text.split())
                    if not cells or cells[-1] != value:  # skip repeats from merged cells
                        cells.append(value)
                cells = [c for c in cells if c]
                if len(cells) == 2:
                    lines.append("%s: %s" % (cells[0], cells[1]))
                elif cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_image(data):
    try:
        from PIL import Image
    except ImportError:
        raise ExtractionError("Pillow is not installed. Run: pip install Pillow")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("Could not open the image: %s" % exc)
    return ocr_image(image)


# ----------------------------------------------------------------------------
# Public function
# ----------------------------------------------------------------------------
def extract_text(filename, data):
    """Return an ExtractionResult for an uploaded file or raise ExtractionError."""
    if not data:
        raise ExtractionError("The file is empty.")
    extension = os.path.splitext(filename)[1].lower().lstrip(".")
    if extension not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(
            "Unsupported file type '.%s'. Supported types: %s." % (extension, ", ".join(SUPPORTED_EXTENSIONS))
        )

    warnings = []
    if extension == "txt":
        text, method = _read_txt(data), "Plain text"
    elif extension == "pdf":
        text, method, warnings = _read_pdf(data)
    elif extension == "docx":
        text, method = _read_docx(data), "DOCX text"
    else:
        text, method = _read_image(data), "Image OCR"

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ExtractionError("No readable text was found in this file.")
    if method == "Image OCR" or "OCR" in method:
        warnings.append("Text was read by OCR and may contain recognition errors. Check the evidence shown.")
    return ExtractionResult(text=text, method=method, warnings=warnings)
