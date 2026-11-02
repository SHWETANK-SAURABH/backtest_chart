"""Writes report content as PDF, CSV, JSON or Parquet. Every format carries the metadata."""

import csv
import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pyarrow as pa
import pyarrow.parquet as pq
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.domain.enums import ExportFormat
from app.reporting.content import ReportContent, Section

# Short explanatory tables whose text is shown in full rather than shortened.
WRAPPED_SECTIONS = {"Units", "Sharpe ratio assumptions", "How labels are calculated"}
EXCHANGE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30")
REPORT_FORMATS = (ExportFormat.PDF, ExportFormat.CSV, ExportFormat.JSON, ExportFormat.PARQUET)
# Beyond this, a PDF table shows its first rows and points to the CSV or Parquet export.
PDF_ROW_LIMIT = 500
# Wide tables are trimmed to these columns in the PDF; other formats keep every column.
PDF_COLUMNS = {
    "Trades": [
        "trade_number", "date", "side", "entry_time", "exit_time", "entry_price", "exit_price",
        "stop_loss", "target", "exit_reason", "net_points", "market_regime",
    ],
    "Strategy decisions, every candle": [
        "time", "close", "cpr_tc", "cpr_bc", "weekly_tc", "weekly_bc", "action", "reason_codes",
        "position_after",
    ],
}  # fmt: skip


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    """Every key used by any row, in first-seen order, so no value is dropped."""
    return list(dict.fromkeys(key for row in rows for key in row))


def _flat(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


def write_json(content: ReportContent, path: Path) -> None:
    document = {
        "title": content.title,
        "category": content.category.value,
        "metadata": content.metadata,
        "sections": [{"title": s.title, "text": s.text, "rows": s.rows} for s in content.sections],
    }
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")


def write_csv(content: ReportContent, path: Path) -> None:
    """The main table, preceded by '# key: value' metadata lines (read with comment='#')."""
    rows = content.main_table.rows
    columns = _columns(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(f"# {content.title}\n")
        for key, value in content.metadata.items():
            handle.write(f"# {key}: {json.dumps(value) if isinstance(value, dict) else value}\n")
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _flat(v) for k, v in row.items()})


def write_parquet(content: ReportContent, path: Path) -> None:
    """The main table, with the metadata stored in the file's key-value metadata."""
    columns = _columns(content.main_table.rows)
    rows = [{c: _flat(row.get(c)) for c in columns} for row in content.main_table.rows]
    table = pa.Table.from_pylist(rows) if rows else pa.table({})
    metadata = {
        b"report_title": content.title.encode(),
        b"report_metadata": json.dumps(content.metadata, default=str).encode(),
    }
    pq.write_table(table.replace_schema_metadata(metadata), path)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    text = str(_flat(value))
    # Exchange-time ISO stamps read more easily as "YYYY-MM-DD HH:MM".
    if EXCHANGE_TIME.fullmatch(text):
        return f"{text[:10]} {text[11:16]}"
    return text if len(text) <= 60 else text[:57] + "..."


def _pdf_table(section: Section, style: Any, wrap: bool = False) -> list[Any]:
    """A table of the section's rows. With `wrap`, cells wrap instead of being shortened."""
    rows = section.rows
    if not rows:
        return [Paragraph("No rows.", style)]
    available = _columns(rows)
    columns = [c for c in PDF_COLUMNS.get(section.title, available) if c in available]
    shown = rows[:PDF_ROW_LIMIT]
    body = [
        [Paragraph(escape(str(_flat(row.get(c)))), style) if wrap else _cell(row.get(c))
         for c in columns]
        for row in shown
    ]  # fmt: skip
    # Wrapped tables give the last column the remaining page width.
    widths = (
        [40 * mm] * (len(columns) - 1) + [(273 - 40 * (len(columns) - 1)) * mm] if wrap else None
    )
    table = LongTable([columns, *body], repeatRows=1, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ebf0")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c4c9d1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )
    flow: list[Any] = [table]
    if len(rows) > len(shown):
        flow.append(
            Paragraph(
                f"Showing {len(shown)} of {len(rows)} rows. "
                "The CSV and Parquet exports contain all rows and columns.",
                style,
            )
        )
    elif section.title in PDF_COLUMNS:
        flow.append(Paragraph("Selected columns. The CSV and Parquet exports have all.", style))
    return flow


def write_pdf(content: ReportContent, path: Path) -> None:
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    cell = styles["BodyText"].clone("cell", fontSize=6.5, leading=8)
    # A heading always stays on the same page as the start of its table.
    heading = styles["Heading2"].clone("heading", keepWithNext=True)
    flow: list[Any] = [
        Paragraph(content.title, styles["Title"]),
        Paragraph(content.metadata["notice"], small),
        Paragraph("Times are exchange time (IST).", small),
        Spacer(1, 4 * mm),
    ]
    meta_rows = [
        {"field": k, "value": json.dumps(v) if isinstance(v, dict) else v}
        for k, v in content.metadata.items()
        if k != "notice"
    ]
    flow += [Paragraph("Report details", heading)]
    flow += _pdf_table(Section("Report details", meta_rows), cell, wrap=True)
    for section in content.sections:
        flow += [Spacer(1, 4 * mm), Paragraph(section.title, heading)]
        if section.text:
            flow.append(Paragraph(section.text, small))
        flow += _pdf_table(section, cell, wrap=section.title in WRAPPED_SECTIONS)

    def footer(canvas: Any, document: Any) -> None:
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            12 * mm,
            7 * mm,
            f"Backtest {content.metadata['backtest_id']} | index points, not rupees | "
            f"page {document.page}",
        )

    document = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=content.title,
    )
    document.build(flow, onFirstPage=footer, onLaterPages=footer)


WRITERS = {
    ExportFormat.PDF: write_pdf,
    ExportFormat.CSV: write_csv,
    ExportFormat.JSON: write_json,
    ExportFormat.PARQUET: write_parquet,
}
