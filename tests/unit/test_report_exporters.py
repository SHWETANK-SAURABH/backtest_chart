"""Exporters with rows whose fields differ (test content only)."""

import csv
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app.domain.enums import ExportFormat, ReportCategory
from app.reporting.content import ReportContent, Section
from app.reporting.exporters import WRITERS, _cell

ROWS = [
    {"unit": "points", "value": 12.5},
    {"unit": "actual_monetary", "value": None, "note": "not available"},
]
CONTENT = ReportContent(
    ReportCategory.PERFORMANCE,
    "Test report",
    {"backtest_id": "test", "notice": "points, not rupees", "settings": {"a": 1}},
    Section("Units", ROWS),
    [Section("Units", ROWS, text="test")],
)


def test_csv_keeps_columns_that_only_some_rows_have(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    WRITERS[ExportFormat.CSV](CONTENT, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Test report"
    assert '# settings: {"a": 1}' in lines
    rows = list(
        csv.DictReader(io.StringIO("\n".join(line for line in lines if not line.startswith("#"))))
    )
    assert rows[1]["note"] == "not available"
    assert rows[0]["note"] == ""


def test_parquet_and_json_keep_every_field(tmp_path: Path) -> None:
    WRITERS[ExportFormat.PARQUET](CONTENT, tmp_path / "r.parquet")
    table = pq.read_table(tmp_path / "r.parquet")
    assert table.column_names == ["unit", "value", "note"]
    assert json.loads(table.schema.metadata[b"report_metadata"])["backtest_id"] == "test"

    WRITERS[ExportFormat.JSON](CONTENT, tmp_path / "r.json")
    document = json.loads((tmp_path / "r.json").read_text())
    assert document["sections"][0]["rows"][1]["note"] == "not available"


def test_pdf_is_written(tmp_path: Path) -> None:
    WRITERS[ExportFormat.PDF](CONTENT, tmp_path / "r.pdf")
    assert (tmp_path / "r.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (None, ""),
        (1234.5678, "1,234.57"),
        ("2025-06-02T09:15:00+05:30", "2025-06-02 09:15"),
        ("x" * 70, "x" * 57 + "..."),
        ({"b": 2}, '{"b": 2}'),
    ],
)
def test_pdf_cell_formatting(value: object, shown: str) -> None:
    assert _cell(value) == shown
