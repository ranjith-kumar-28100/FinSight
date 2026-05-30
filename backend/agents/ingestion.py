"""Ingestion Agent — parses bank/wallet statements into canonical schema.

Handles:
- HDFC bank statements (XLS/XLSX)
- Paytm wallet exports (XLSX)
- GPay transaction exports (PDF)

File upload security:
- Extension allow-list validation
- File size limit enforcement
- UUID rename for storage
- Files stored outside web root
"""

import logging
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.models.transaction import (
    Provenance,
    Transaction,
    TransactionDirection,
    TransactionSource,
)

logger = logging.getLogger(__name__)

# Allowed file extensions (allow-list)
ALLOWED_EXTENSIONS = frozenset({".csv", ".xls", ".xlsx", ".pdf"})
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_upload(file_path: Path) -> None:
    """Validate an uploaded file against security constraints.

    Raises ValueError for invalid files.
    """
    # Check extension against allow-list
    ext = file_path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type '{ext}' is not allowed. "
            f"Accepted types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Check file size
    size = file_path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size ({size / 1024 / 1024:.1f} MB) exceeds "
            f"limit ({MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f} MB)."
        )

    if size == 0:
        raise ValueError("File is empty.")


def save_upload(file_bytes: bytes, original_name: str, upload_dir: Path) -> Path:
    """Save uploaded file with a UUID filename for security.

    Returns the path to the saved file.
    """
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type '{ext}' is not allowed.")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError("File exceeds size limit.")

    # UUID filename to prevent path traversal and info leakage
    safe_name = f"{uuid.uuid4()}{ext}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / safe_name

    dest.write_bytes(file_bytes)
    logger.info("Saved upload as '%s' (%d bytes).", safe_name, len(file_bytes))
    return dest


# ---------------------------------------------------------------------------
# HDFC Bank Statement Parser
# ---------------------------------------------------------------------------

def _parse_decimal(value) -> Optional[Decimal]:
    """Safely parse a value to Decimal, returning None for empty/invalid."""
    if pd.isna(value) or value == "" or value is None:
        return None
    try:
        # Remove commas and whitespace from formatted numbers
        cleaned = str(value).replace(",", "").strip()
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _norm_ref(value) -> str:
    """Normalise a UPI reference (RRN) to a bare digit string for cross-source joins.

    The same payment carries the same 12-digit NPCI RRN in every export, but
    formatted differently per source:
      - HDFC  Chq./Ref.No. : "0000600199803992"  (zero-padded to 16)
      - Paytm UPI Ref No.   : 600199803992        (bare, sometimes float)
      - GPay  UPITransactionID: 600199803992      (bare)
    Stripping non-digits and leading zeros makes all three comparable.
    Returns "" for empty/all-zero refs (non-UPI rows like NACH/EMI).
    """
    if value is None:
        return ""
    # pandas may surface an integer ref as a float ("614760095294.0") or NaN.
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        value = format(int(value), "d")
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return re.sub(r"\D", "", s).lstrip("0")


_VPA_RE = re.compile(r"([\w.\-]+@[a-z]+)", re.IGNORECASE)

# Paytm "Transaction Details" verbs to strip when deriving the merchant name.
_PAYTM_VERB_RE = re.compile(
    r"^(?:paid to|money sent to|received from|money received from|"
    r"recharge of|bill payment of|payment to|added to)\s+",
    re.IGNORECASE,
)
# Wallet counterparty handles read "<vpa> on <App>" (PhonePe / Google Pay / Paytm…).
_ON_APP_RE = re.compile(r"\s+on\s+([A-Za-z][A-Za-z ]+?)\s*$")


def _split_handle(other_details: str) -> tuple[Optional[str], Optional[str]]:
    """Split Paytm 'Other Transaction Details' into (vpa, counterparty_app).

    e.g. 'q428790842@ybl on PhonePe' -> ('q428790842@ybl', 'PhonePe')
         '9842506824@okbizaxis'      -> ('9842506824@okbizaxis', None)
    """
    if not other_details:
        return None, None
    text = other_details.strip()
    app = None
    m = _ON_APP_RE.search(text)
    if m:
        app = m.group(1).strip()
        text = text[: m.start()].strip()
    return (text or None), app


def _clean_merchant(details: str) -> str:
    """Strip the leading action verb from a wallet 'paid to / money sent to' label."""
    if not details:
        return ""
    return _PAYTM_VERB_RE.sub("", details.strip()).strip()


def _clean_tag(tag: str) -> Optional[str]:
    """Reduce a Paytm tag like '#\U0001f957 Food' to plain text 'Food'."""
    if not tag or str(tag).strip().lower() == "nan":
        return None
    # Drop '#', emoji and other non-word symbols, keep letters/digits/spaces.
    cleaned = re.sub(r"[^\w &/]", " ", str(tag)).strip()
    return cleaned or None


def _extract_vpa(text: str) -> Optional[str]:
    """Pull the first UPI VPA (e.g. 'zepto.payu@axisbank') out of free text."""
    if not text:
        return None
    m = _VPA_RE.search(text)
    return m.group(1) if m else None


def _parse_date(value, formats: Optional[list[str]] = None) -> Optional[date]:
    """Try multiple date formats to parse a date value."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, (datetime, date)):
        return value if isinstance(value, date) else value.date()

    date_str = str(value).strip()
    if not date_str:
        return None

    if formats is None:
        formats = [
            "%d/%m/%y", "%d/%m/%Y",
            "%d-%m-%y", "%d-%m-%Y",
            "%Y-%m-%d", "%m/%d/%Y",
            "%d %b %Y", "%d %B %Y",
            "%d/%m/%Y %H:%M:%S",
        ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    logger.warning("Could not parse date: '%s'", date_str)
    return None


def _extract_counterparty(narration: str) -> str:
    """Extract counterparty from HDFC narration text.

    Handles UPI VPAs, NEFT beneficiaries, IMPS, etc.
    """
    if not narration:
        return ""

    narration_upper = narration.upper()

    # UPI: extract VPA or merchant name
    upi_match = re.search(
        r'UPI[-/]?(?:.*?[-/])?([\w.]+@[\w]+)', narration, re.IGNORECASE)
    if upi_match:
        return upi_match.group(1)

    # UPI with name pattern: UPI-NAME-VPA-...
    upi_name_match = re.search(
        r'UPI[-/]([^-/]+)[-/]', narration, re.IGNORECASE)
    if upi_name_match:
        name = upi_name_match.group(1).strip()
        if len(name) > 2 and not name.isdigit():
            return name

    # NEFT: extract beneficiary
    if "NEFT" in narration_upper:
        neft_match = re.search(
            r'NEFT[-/\s]*(?:CR|DR)?[-/\s]*(?:\d+[-/\s]*)?(.+?)(?:[-/]\d|$)', narration, re.IGNORECASE)
        if neft_match:
            return neft_match.group(1).strip()

    # IMPS: extract name
    if "IMPS" in narration_upper:
        imps_match = re.search(
            r'IMPS[-/\s]*(?:\d+[-/\s]*)?(.+?)(?:[-/]\d|$)', narration, re.IGNORECASE)
        if imps_match:
            return imps_match.group(1).strip()

    # ATM
    if "ATM" in narration_upper:
        atm_match = re.search(
            r'ATM[-/\s]*(.+?)(?:[-/]\d|$)', narration, re.IGNORECASE)
        if atm_match:
            return "ATM - " + atm_match.group(1).strip()
        return "ATM"

    # BIL/BILL payment
    if "BIL" in narration_upper or "BILL" in narration_upper:
        bill_match = re.search(
            r'(?:BIL|BILL)[-/\s]*(.+?)(?:[-/]\d|$)', narration, re.IGNORECASE)
        if bill_match:
            return bill_match.group(1).strip()

    # Default: return first meaningful segment
    parts = re.split(r'[-/]', narration)
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) > 2 and not cleaned.isdigit():
            return cleaned

    return narration[:50]


def parse_hdfc(file_path: Path) -> list[Transaction]:
    """Parse HDFC bank statement (XLS/XLSX) into canonical transactions.

    HDFC NetBanking exports have ~20 metadata rows before the actual column
    header ("Date", "Narration", ...). We detect that row and skip to it.
    """
    logger.info("Parsing HDFC statement: %s", file_path.name)

    ext = file_path.suffix.lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"

    # Step 1: read without assuming any header to find where data actually starts
    df_raw = pd.read_excel(file_path, engine=engine, header=None)
    header_rows = df_raw.index[
        df_raw.iloc[:, 0].astype(str).str.strip().str.lower() == "date"
    ].tolist()
    if not header_rows:
        logger.error("Could not find 'Date' header row in HDFC statement.")
        return []
    header_row_idx = header_rows[0]

    # Step 2: re-read with the correct header row
    df = pd.read_excel(file_path, engine=engine,
                       skiprows=header_row_idx, header=0)

    # Normalise column names: strip whitespace, lowercase
    df.columns = [str(c).strip().lower().replace("  ", " ")
                  for c in df.columns]

    logger.info("HDFC columns found: %s", list(df.columns))

    # Map known HDFC column names
    col_map = _map_hdfc_columns(df.columns.tolist())

    transactions = []
    for idx, row in df.iterrows():
        try:
            txn_date = _parse_date(row.get(col_map.get("date", ""), None))
            if txn_date is None:
                continue

            narration = str(row.get(col_map.get("narration", ""), "")).strip()
            if not narration or narration == "nan":
                continue

            debit = _parse_decimal(row.get(col_map.get("debit", ""), None))
            credit = _parse_decimal(row.get(col_map.get("credit", ""), None))

            if debit and debit > 0:
                amount = debit
                direction = TransactionDirection.DEBIT
            elif credit and credit > 0:
                amount = credit
                direction = TransactionDirection.CREDIT
            else:
                continue

            ref = str(row.get(col_map.get("ref", ""), "")).strip()
            if ref == "nan":
                ref = ""

            counterparty = _extract_counterparty(narration)

            txn = Transaction(
                source=TransactionSource.BANK,
                source_ref=_norm_ref(ref),  # normalised RRN — the cross-source join key
                date=txn_date,
                amount=amount,
                direction=direction,
                raw_description=narration,
                counterparty=counterparty,
                upi_id=_extract_vpa(narration),
                provenance=Provenance(
                    source_file=file_path.name,
                    row_index=int(idx),
                ),
            )
            transactions.append(txn)
        except Exception:
            logger.warning("Skipping HDFC row %d due to parsing error.", idx)
            continue

    logger.info("Parsed %d transactions from HDFC statement.",
                len(transactions))
    return transactions


def _map_hdfc_columns(columns: list[str]) -> dict[str, str]:
    """Map HDFC column names to canonical names.

    Handles variations in HDFC export formats.
    """
    mapping: dict[str, str] = {}

    for col in columns:
        col_lower = col.lower().strip()
        if "date" in col_lower and "value" not in col_lower:
            mapping["date"] = col
        elif "narration" in col_lower or "description" in col_lower or "particulars" in col_lower:
            mapping["narration"] = col
        elif "debit" in col_lower or "withdrawal" in col_lower:
            mapping["debit"] = col
        elif "credit" in col_lower or "deposit" in col_lower:
            mapping["credit"] = col
        elif "chq" in col_lower or "ref" in col_lower or "reference" in col_lower:
            mapping["ref"] = col
        elif "closing" in col_lower or "balance" in col_lower:
            mapping["balance"] = col

    logger.info("HDFC column mapping: %s", mapping)
    return mapping


# ---------------------------------------------------------------------------
# Paytm Statement Parser
# ---------------------------------------------------------------------------

def parse_paytm(file_path: Path) -> list[Transaction]:
    """Parse Paytm passbook export (XLSX) into canonical transactions.

    Paytm exports typically contain multiple sheets. The actual transaction
    data lives in a sheet named "Passbook Payment History" (or similar).
    The first sheet is usually a summary.

    Expected columns in the transaction sheet:
    Date, Time, Transaction Details, Other Transaction Details (UPI ID or A/c No),
    Your Account, Amount, UPI Ref No., Order ID, Remarks, Tags, Comment
    """
    logger.info("Parsing Paytm statement: %s", file_path.name)

    # Step 1: Find the correct sheet containing transaction data
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    sheet_names = xl.sheet_names
    logger.info("Paytm workbook sheets: %s", sheet_names)

    target_sheet = None
    # Look for sheets with transaction-related names
    for name in sheet_names:
        name_lower = name.lower()
        if "passbook" in name_lower or "payment history" in name_lower or "transaction" in name_lower:
            target_sheet = name
            break

    # If no named match, try each sheet and pick the first one with date-like data
    if target_sheet is None:
        for name in sheet_names:
            df_probe = pd.read_excel(xl, sheet_name=name, header=None, nrows=50)
            for _, row in df_probe.iterrows():
                for cell in row:
                    val = str(cell).strip().lower()
                    if val == "date" or re.match(r'\d{1,2}[/-]\d', val) or re.match(r'\d{4}-\d{2}', val):
                        target_sheet = name
                        break
                if target_sheet:
                    break
            if target_sheet:
                break

    if target_sheet is None:
        logger.info(
            "Paytm file appears to be a summary-only export (no transaction sheet found). "
            "Paytm UPI transactions may be captured in the bank statement instead. Skipping."
        )
        return []

    logger.info("Using Paytm sheet: '%s'", target_sheet)

    # Step 2: Read the target sheet with header detection
    df_raw = pd.read_excel(xl, sheet_name=target_sheet, header=None)

    # Find the header row — look for a row containing "Date" and "Amount"
    header_row_idx = 0
    for i, row in df_raw.iterrows():
        row_values = [str(v).strip().lower() for v in row if pd.notna(v)]
        if "date" in row_values and "amount" in row_values:
            header_row_idx = int(i)
            break

    # Re-read with the correct header row
    df = pd.read_excel(xl, sheet_name=target_sheet,
                       skiprows=header_row_idx, header=0)

    # Normalise column names
    df.columns = [str(c).strip().lower().replace("  ", " ")
                  for c in df.columns]

    logger.info("Paytm columns found: %s", list(df.columns))

    col_map = _map_paytm_columns(df.columns.tolist())

    transactions = []
    for idx, row in df.iterrows():
        try:
            txn_date = _parse_date(row.get(col_map.get("date", ""), None))
            if txn_date is None:
                continue

            activity = str(row.get(col_map.get("activity", ""), "")).strip()
            comment = str(row.get(col_map.get("comment", ""), "")).strip()
            if comment == "nan":
                comment = ""

            description = activity if activity and activity != "nan" else comment
            if not description:
                continue

            # Parse amount — Paytm may use signed amounts or separate columns
            amount_raw = row.get(col_map.get("amount", ""), None)
            amount = _parse_decimal(amount_raw)

            status = str(row.get(col_map.get("status", ""), "")
                         ).strip().lower()
            if status and status != "nan" and "success" not in status and "completed" not in status:
                continue  # Skip failed transactions

            if amount is None:
                continue

            # Determine direction from amount sign or activity
            if amount < 0:
                direction = TransactionDirection.DEBIT
                amount = abs(amount)
            elif amount > 0:
                activity_lower = description.lower()
                if any(kw in activity_lower for kw in ["paid", "sent", "payment", "debit", "transfer to"]):
                    direction = TransactionDirection.DEBIT
                elif any(kw in activity_lower for kw in ["received", "credited", "cashback", "refund", "credit"]):
                    direction = TransactionDirection.CREDIT
                else:
                    direction = TransactionDirection.DEBIT  # Default to debit
            else:
                continue  # Skip zero amounts

            source_dest = str(
                row.get(col_map.get("source_dest", ""), "")).strip()
            if source_dest == "nan":
                source_dest = ""

            vpa, counterparty_app = _split_handle(source_dest)
            merchant = _clean_merchant(description) or _extract_counterparty(description)

            txn_time = str(row.get(col_map.get("time", ""), "")).strip()
            if txn_time == "nan":
                txn_time = ""

            external_tag = _clean_tag(row.get(col_map.get("tags", ""), ""))

            txn = Transaction(
                source=TransactionSource.PAYTM,
                # Paytm "UPI Ref No." is the RRN — normalise it as the join key.
                source_ref=_norm_ref(row.get(col_map.get("txn_id", ""), "")),
                date=txn_date,
                amount=amount,
                direction=direction,
                raw_description=description,
                counterparty=merchant,
                upi_id=vpa,
                counterparty_app=counterparty_app,
                txn_time=txn_time or None,
                external_tag=external_tag,
                provenance=Provenance(
                    source_file=file_path.name,
                    row_index=int(idx),
                ),
            )
            transactions.append(txn)
        except Exception:
            logger.warning("Skipping Paytm row %d due to parsing error.", idx)
            continue

    logger.info("Parsed %d transactions from Paytm statement.",
                len(transactions))
    return transactions


def _map_paytm_columns(columns: list[str]) -> dict[str, str]:
    """Map Paytm column names to canonical names.

    Handles both the newer multi-sheet format with columns like:
        Date, Time, Transaction Details, Other Transaction Details
        (UPI ID or A/c No), Your Account, Amount, UPI Ref No.,
        Order ID, Remarks, Tags, Comment
    and the older single-sheet format.
    """
    mapping: dict[str, str] = {}

    for col in columns:
        col_lower = col.lower().strip()

        # Time — capture explicitly before the date branch would swallow it.
        if col_lower == "time":
            mapping["time"] = col
            continue

        # Date — match "date" but not columns that merely contain "date"
        # as part of a longer phrase like "other transaction details"
        if col_lower == "date" or (
            ("date" in col_lower or "time" in col_lower)
            and "detail" not in col_lower
            and "transaction" not in col_lower
        ):
            if "date" not in mapping:  # Take the first date column
                mapping["date"] = col

        # Counterparty / UPI ID — "other transaction details (upi id or a/c no)"
        # Must check before generic "transaction details" to avoid conflicts
        elif "other" in col_lower and "detail" in col_lower:
            mapping["source_dest"] = col
        elif "source" in col_lower or "destination" in col_lower or "merchant" in col_lower:
            if "source_dest" not in mapping:
                mapping["source_dest"] = col

        # Activity / description — "transaction details" or legacy "activity"
        elif "detail" in col_lower or "activity" in col_lower or "transaction type" in col_lower:
            if "activity" not in mapping:
                mapping["activity"] = col

        # Amount
        elif "amount" in col_lower or "value" in col_lower:
            mapping["amount"] = col

        # UPI reference — "upi ref no." (check before generic txn_id)
        elif "upi ref" in col_lower or "upi_ref" in col_lower:
            mapping["txn_id"] = col

        # Order / transaction ID (fallback if UPI ref wasn't found)
        elif "txn" in col_lower or "transaction id" in col_lower or "order" in col_lower:
            if "txn_id" not in mapping:
                mapping["txn_id"] = col

        # Comments and remarks
        elif "comment" in col_lower or "description" in col_lower or "remark" in col_lower:
            mapping["comment"] = col

        # Status
        elif "status" in col_lower:
            mapping["status"] = col

        # Tags (for categorization)
        elif "tag" in col_lower:
            mapping["tags"] = col

    logger.info("Paytm column mapping: %s", mapping)
    return mapping


# ---------------------------------------------------------------------------
# GPay PDF Parser
# ---------------------------------------------------------------------------

def parse_gpay(file_path: Path) -> list[Transaction]:
    """Parse Google Pay transaction PDF into canonical transactions.

    GPay statement PDFs use a text layout (not tabular) with this pattern
    per transaction (one entry spans several lines):
        01Nov,2025          ← date line  (DDMon,YYYY)
        10:16PM             ← time line
        ReceivedFromXYZ     ← description (camel-cased, no spaces due to PDF encoding)
        ₹30,000             ← amount line (starts with ₹)
        UPITransactionID:XXXXXXX   ← UPI ref
        PaidtoHDFCBank1210  ← bank note (ignored)
    """
    logger.info("Parsing GPay statement: %s", file_path.name)

    try:
        import pdfplumber
    except ImportError:
        logger.error(
            "pdfplumber is required for PDF parsing. Install it with: pip install pdfplumber")
        return []

    # Extract all text across all pages in one pass
    full_text_lines: list[str] = []
    with pdfplumber.open(str(file_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text_lines.extend(text.splitlines())

    transactions = _parse_gpay_text_lines(full_text_lines, file_path.name)
    logger.info("Parsed %d transactions from GPay statement.",
                len(transactions))
    return transactions


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# GPay transaction line: "01Nov,2025 Description ₹30,000"
# The date, description and amount are all on one line.
_GPAY_TXN_RE = re.compile(
    r'^(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),(\d{4})'
    r'\s+(.+?)\s+₹([\d,]+\.?\d*)$',
    re.IGNORECASE,
)
# UPI ref on the following line: "10:16PM UPITransactionID:530549395614"
_GPAY_UPI_RE = re.compile(r'UPITransactionID[:\s]*(\d+)', re.IGNORECASE)


def _parse_gpay_text_lines(lines: list[str], source_file: str) -> list[Transaction]:
    """Parse GPay PDF text lines into Transaction objects.

    GPay PDF format: each transaction occupies 1-3 lines:
      Line 1: "DDMon,YYYY  Description  ₹Amount"    (all on one line)
      Line 2: "HH:MMPM  UPITransactionID:XXXXXXX"   (optional — carries UPI ref)
      Line 3: "PaidtoHDFCBank1210"                    (skip)
    """
    transactions: list[Transaction] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        m = _GPAY_TXN_RE.match(line)
        if not m:
            i += 1
            continue

        day = int(m.group(1))
        month = _MONTH_MAP.get(m.group(2).lower()[:3], 0)
        year = int(m.group(3))
        description = m.group(4).strip()
        amount_str = m.group(5).replace(",", "")

        try:
            txn_date = date(year, month, day)
            amount = Decimal(amount_str)
        except (ValueError, InvalidOperation):
            i += 1
            continue

        if amount <= 0:
            i += 1
            continue

        # The next line carries "HH:MMPM UPITransactionID:<rrn>"
        upi_ref = ""
        txn_time = None
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            upi_m = _GPAY_UPI_RE.search(next_line)
            if upi_m:
                upi_ref = upi_m.group(1)
            time_m = re.match(r'(\d{1,2}:\d{2}\s*[AP]M)', next_line, re.IGNORECASE)
            if time_m:
                txn_time = time_m.group(1)

        # Direction from description prefix
        desc_lower = description.lower()
        if desc_lower.startswith("paidto") or desc_lower.startswith("paid to"):
            direction = TransactionDirection.DEBIT
        elif desc_lower.startswith("receivedfrom") or desc_lower.startswith("received from"):
            direction = TransactionDirection.CREDIT
        else:
            direction = TransactionDirection.DEBIT

        # Counterparty: strip direction verb prefix
        counterparty = re.sub(
            r'^(?:PaidTo|Paid to|ReceivedFrom|Received from)\s*',
            '', description, flags=re.IGNORECASE,
        ).strip()

        transactions.append(Transaction(
            source=TransactionSource.GPAY,
            source_ref=_norm_ref(upi_ref),  # GPay UPITransactionID is the RRN
            date=txn_date,
            amount=amount,
            direction=direction,
            raw_description=description,
            counterparty=counterparty[:80],
            txn_time=txn_time,
            provenance=Provenance(source_file=source_file,
                                  row_index=len(transactions)),
        ))
        i += 1

    return transactions


# ---------------------------------------------------------------------------
# Unified parser entry point
# ---------------------------------------------------------------------------

def parse_statement(file_path: Path, source: TransactionSource) -> list[Transaction]:
    """Parse a statement file based on its source type.

    Args:
        file_path: Path to the statement file.
        source: The source type (BANK, PAYTM, GPAY).

    Returns:
        List of canonical Transaction objects.
    """
    validate_upload(file_path)

    if source == TransactionSource.BANK:
        return parse_hdfc(file_path)
    elif source == TransactionSource.PAYTM:
        return parse_paytm(file_path)
    elif source == TransactionSource.GPAY:
        return parse_gpay(file_path)
    else:
        raise ValueError(f"Unknown source type: {source}")
