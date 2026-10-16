"""CSV export utility with UTF-8 BOM, RFC 4180 formatting and formula injection defense.

Supports S-58 requirements:
- UTF-8 with BOM (\ufeff) for native Microsoft Excel Vietnamese text support.
- Neutralization of spreadsheet formula injection characters (=, +, -, @, \t, \r).
- RFC 4180 compliant quoting and escaping.
- Async streaming response for memory efficiency with large datasets.
"""

import csv
import io
from collections.abc import AsyncGenerator, AsyncIterable, Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.responses import StreamingResponse

UTF8_BOM = "\ufeff"
DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralize potential CSV formula injection in cell values.

    Prefixes dangerous characters with a single quote (') so spreadsheet
    applications (Excel, LibreOffice, Google Sheets) treat them as literal text.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        # Format decimal with dot separator, strip excessive trailing zeroes if clean
        return f"{value:f}" if value % 1 else str(int(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"

    text = str(value)
    # If the text starts with a dangerous spreadsheet prefix, neutralize it
    if text and text[0] in DANGEROUS_FORMULA_PREFIXES:
        return f"'{text}"
    return text


def format_csv_row(row: Sequence[Any]) -> str:
    """Format a single sequence of values into an RFC 4180 CSV line."""
    output = io.StringIO()
    writer = csv.writer(
        output,
        delimiter=",",
        quotechar='"',
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    sanitized_row = [sanitize_csv_cell(cell) for cell in row]
    writer.writerow(sanitized_row)
    return output.getvalue()


async def generate_csv_chunks(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]] | AsyncIterable[Sequence[Any]],
) -> AsyncGenerator[bytes, None]:
    """Generate byte chunks of CSV file starting with UTF-8 BOM."""
    # Yield UTF-8 BOM so Excel opens Vietnamese characters correctly
    yield UTF8_BOM.encode("utf-8")

    # Header line
    yield format_csv_row(headers).encode("utf-8")

    # Rows
    if isinstance(rows, AsyncIterable):
        async for row in rows:
            yield format_csv_row(row).encode("utf-8")
    else:
        for row in rows:
            yield format_csv_row(row).encode("utf-8")


def build_csv_streaming_response(
    filename: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]] | AsyncIterable[Sequence[Any]],
) -> StreamingResponse:
    """Create a FastAPI StreamingResponse for CSV download."""
    safe_filename = filename.replace('"', '\\"')
    return StreamingResponse(
        generate_csv_chunks(headers, rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
