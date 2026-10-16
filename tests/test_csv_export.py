"""Unit tests for CSV export utilities (S-58)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.platform.csv_export import (
    UTF8_BOM,
    build_csv_streaming_response,
    format_csv_row,
    generate_csv_chunks,
    sanitize_csv_cell,
)


def test_sanitize_csv_cell_neutralizes_formulas() -> None:
    # Dangerous prefixes
    assert (
        sanitize_csv_cell("=HYPERLINK('http://evil.com')")
        == "'=HYPERLINK('http://evil.com')"
    )
    assert sanitize_csv_cell("+123456789") == "'+123456789"
    assert sanitize_csv_cell("-123") == "'-123"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("\tTabbed") == "'\tTabbed"
    assert sanitize_csv_cell("\rReturn") == "'\rReturn"

    # Safe text
    assert sanitize_csv_cell("Trạm Sạc Quận 1") == "Trạm Sạc Quận 1"
    assert sanitize_csv_cell("CP-01") == "CP-01"

    # None and empty
    assert sanitize_csv_cell(None) == ""
    assert sanitize_csv_cell("") == ""

    # Numbers
    assert sanitize_csv_cell(1000) == 1000
    assert sanitize_csv_cell(38500) == 38500
    assert sanitize_csv_cell(Decimal("10.500000")) == "10.500000"
    assert sanitize_csv_cell(Decimal("10.0")) == "10"

    # Dates and UUIDs
    d = date(2026, 10, 1)
    assert sanitize_csv_cell(d) == "2026-10-01"
    dt = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    assert sanitize_csv_cell(dt) == "2026-10-01T12:00:00+00:00"

    u = uuid4()
    assert sanitize_csv_cell(u) == str(u)


def test_format_csv_row_rfc4180() -> None:
    # Commas and quotes handled cleanly
    row = ['Trạm Sạc "Sài Gòn", Q.1', 1000, Decimal("15.25")]
    formatted = format_csv_row(row)
    assert formatted == '"Trạm Sạc ""Sài Gòn"", Q.1",1000,15.25\r\n'

    # Newlines within text
    row_nl = ["Dòng 1\nDòng 2", "=1+1"]
    formatted_nl = format_csv_row(row_nl)
    assert formatted_nl == '"Dòng 1\nDòng 2",\'=1+1\r\n'


@pytest.mark.asyncio
async def test_generate_csv_chunks_has_bom_and_utf8() -> None:
    headers = ["period_from", "station_name", "total_vnd"]
    rows = [
        ["2026-10-01", "Trạm Sạc Quận 1", 38500],
        ["2026-10-02", "=HYPERLINK()", 42000],
    ]

    chunks = []
    async for chunk in generate_csv_chunks(headers, rows):
        chunks.append(chunk)

    full_bytes = b"".join(chunks)

    # Starts with UTF-8 BOM
    bom_bytes = UTF8_BOM.encode("utf-8")
    assert full_bytes.startswith(bom_bytes)

    # Decodes cleanly to Vietnamese
    decoded = full_bytes.decode("utf-8")
    assert "Trạm Sạc Quận 1" in decoded
    assert "'=HYPERLINK()" in decoded
    assert "period_from,station_name,total_vnd" in decoded


def test_build_csv_streaming_response_headers() -> None:
    res = build_csv_streaming_response("test_report.csv", ["h1"], [["v1"]])
    assert res.media_type == "text/csv; charset=utf-8"
    assert (
        res.headers["Content-Disposition"] == 'attachment; filename="test_report.csv"'
    )
