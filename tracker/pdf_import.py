import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO


DATE_TOKEN_RE = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{2,4}))?\b")
AMOUNT_TOKEN_RE = re.compile(r"(?<!\d)(?:-?\$?\(?\d[\d,]*\.\d{2}\)?)(?!\d)")


def _guess_category(title: str) -> str:
    text = title.lower()
    rules = [
        ("Housing", ("mortgage", "rent", "property")),
        ("Food", ("grocery", "restaurant", "cafe", "doordash", "uber eats")),
        ("Transport", ("uber", "lyft", "gas", "shell", "chevron", "fuel")),
        ("Utilities", ("electric", "water", "internet", "phone", "utility")),
        ("Insurance", ("insurance", "geico", "progressive")),
        ("Debt", ("loan", "payday", "interest", "credit card", "minimum payment")),
        ("Income", ("salary", "payroll", "paycheck", "deposit")),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "Uncategorized"


def _parse_decimal_amount(raw_value: str) -> Decimal:
    value = raw_value.replace("$", "").replace(",", "").strip()
    is_parentheses_negative = value.startswith("(") and value.endswith(")")
    value = value.replace("(", "").replace(")", "")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid amount: {raw_value}")
    if is_parentheses_negative and parsed > 0:
        parsed *= Decimal("-1")
    return parsed


def _parse_date_token(match: re.Match[str], reference_date: date) -> date:
    month = int(match.group("month"))
    day = int(match.group("day"))
    year_text = match.group("year")

    if year_text is not None:
        year = int(year_text)
        if year < 100:
            year += 2000
        return date(year, month, day)

    # For dates without year in statements, prefer the most recent non-future date.
    candidates: list[date] = []
    for year in (reference_date.year, reference_date.year - 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue

    non_future = [candidate for candidate in candidates if candidate <= reference_date]
    if non_future:
        return max(non_future)
    if candidates:
        return min(candidates)
    raise ValueError("Invalid date token.")


def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    extracted_parts: list[str] = []

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf_doc:
            for page in pdf_doc.pages:
                text = page.extract_text() or ""
                if text.strip():
                    extracted_parts.append(text)
    except ImportError:
        warnings.append("`pdfplumber` not installed; using pypdf fallback.")
    except Exception as exc:
        warnings.append(f"pdfplumber extraction issue: {exc}")

    if extracted_parts:
        return "\n".join(extracted_parts), warnings

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                extracted_parts.append(text)
    except ImportError:
        warnings.append("`pypdf` is not installed.")
    except Exception as exc:
        warnings.append(f"pypdf extraction issue: {exc}")

    if extracted_parts:
        return "\n".join(extracted_parts), warnings

    # Optional OCR fallback for scanned/image-only statements.
    try:
        from pdf2image import convert_from_bytes  # type: ignore
        import pytesseract  # type: ignore

        images = convert_from_bytes(pdf_bytes, dpi=250)
        for image in images:
            text = pytesseract.image_to_string(image) or ""
            if text.strip():
                extracted_parts.append(text)
        if extracted_parts:
            warnings.append("Imported using OCR fallback.")
    except ImportError:
        warnings.append(
            "OCR fallback unavailable. Install `pdf2image` and `pytesseract` to improve scanned PDF support."
        )
    except Exception as exc:
        warnings.append(f"OCR extraction issue: {exc}")

    return "\n".join(extracted_parts), warnings


def extract_transactions_from_pdf(
    pdf_bytes: bytes,
    reference_date: date | None = None,
    fallback_year: int | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    today = date.today()
    if reference_date is None:
        if fallback_year is not None:
            reference_date = date(fallback_year, today.month, today.day)
        else:
            reference_date = today

    text, warnings = _extract_pdf_text(pdf_bytes)
    if not text.strip():
        warnings.append(
            "No selectable text found in PDF. This is likely a scanned statement and may require local OCR setup."
        )
        return [], warnings

    rows: list[dict[str, str]] = []
    seen_signatures: set[tuple[str, str, str]] = set()

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue

        date_match = DATE_TOKEN_RE.search(line)
        if not date_match:
            continue
        if date_match.start() > 4:
            continue

        amount_matches = list(AMOUNT_TOKEN_RE.finditer(line))
        if not amount_matches:
            continue
        # When balance is present, amount is usually second-to-last token.
        chosen_amount_match = (
            amount_matches[-2] if len(amount_matches) >= 2 else amount_matches[-1]
        )

        try:
            tx_date = _parse_date_token(date_match, reference_date)
            signed_amount = _parse_decimal_amount(chosen_amount_match.group(0))
        except ValueError:
            continue

        description = line[date_match.end() : chosen_amount_match.start()].strip(" -")
        if len(description) < 2:
            continue

        transaction_type = "INCOME" if signed_amount > 0 else "EXPENSE"
        amount = abs(signed_amount)
        category = _guess_category(description)

        signature = (tx_date.isoformat(), description.lower(), f"{amount:.2f}")
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        rows.append(
            {
                "date": tx_date.isoformat(),
                "title": description[:255],
                "amount": f"{amount:.2f}",
                "category": category[:100],
                "transaction_type": transaction_type,
            }
        )

    if not rows:
        warnings.append(
            "No transactions were auto-detected. Try another statement PDF or install `pdfplumber`."
        )
    return rows, warnings
