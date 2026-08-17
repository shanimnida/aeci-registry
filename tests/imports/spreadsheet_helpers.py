"""Shared helpers for building .xlsx/.csv fixtures in memory for the
spreadsheet import tests. Deliberately not a committed binary .xlsx fixture
file -- a CSV fixture is readable in a diff and in code review; an .xlsx is
not -- but every test still exercises the real openpyxl read path by
building the workbook bytes here rather than mocking anything.

Not a test module itself (no test_ prefix), so pytest does not try to
collect it.
"""

import csv
import io

import openpyxl

from imports.spreadsheet import HEADER_TEXTS


def row_dict(**overrides) -> dict:
    """One spreadsheet row: every documented header blank except what is
    overridden by column header text, e.g. row_dict(**{"Last Name": "CRUZ"}).
    """
    row = {header: "" for header in HEADER_TEXTS}
    row.update(overrides)
    return row


def person_row(**overrides) -> dict:
    """A minimally complete, entirely fictional person -- every field
    required end to end (source image, name, confidence, form version) is
    filled in; everything else is blank unless overridden."""
    row = row_dict(
        **{
            "Source Image": "IMG_FICTIONAL_1.jpg",
            "Last Name": "SANTOS",
            "First Name": "PEDRO ANDRES",
            "Confidence": "high",
            "Form Version": "v1",
        }
    )
    row.update(overrides)
    return row


def csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER_TEXTS)
    for row in rows:
        writer.writerow([row.get(header, "") for header in HEADER_TEXTS])
    return buffer.getvalue().encode("utf-8")


def xlsx_bytes(rows: list[dict]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(list(HEADER_TEXTS))
    for row in rows:
        sheet.append([row.get(header, "") for header in HEADER_TEXTS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
