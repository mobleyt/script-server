"""
sheet.py — Read a metadata spreadsheet (.csv or .xlsx) into Aviary resource rows.

Column rules (header matching is case-insensitive for the reserved columns):

    Title                     required
    Access                    public | private | restricted | internal
                              (blank uses the configured default)
    Custom Unique Identifier  optional; used to skip resources that already exist
    Featured                  optional; yes/true/1 or no/false/0
    Media URL, Media URL 2…   any header starting with "Media URL"; http(s) links
                              Aviary fetches and attaches as media files

Every other header is an Aviary metadata field. ``Agent (Creator)`` means the
field ``Agent`` with vocabulary ``Creator``. A cell holding several values
separated by the delimiter (default ``|``) becomes one entry per value, and a
field may also be repeated across several columns.

Nothing here talks to Aviary or Flask, so it can be tested on its own.
"""

import csv
import datetime
import io
import os
import re
from urllib.parse import unquote, urlparse

ACCESS_VALUES = ("public", "private", "restricted", "internal")
TRUE_VALUES = {"yes", "y", "true", "t", "1", "x"}
FALSE_VALUES = {"no", "n", "false", "f", "0", ""}

RESERVED = {
    "title": "title",
    "access": "access",
    "custom unique identifier": "cuid",
    "featured": "featured",
}
MEDIA_PREFIX = "media url"

# "Agent (Creator)" -> field "Agent", vocabulary "Creator"
_VOCAB_HEADER = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")

MAX_FIELD_LENGTH = 200
MAX_VALUE_LENGTH = 65_000


class SheetError(ValueError):
    """The file as a whole can't be used (wrong type, no Title column, ...)."""


# ---- reading -------------------------------------------------------------

def _cell_text(value):
    """Turn a spreadsheet cell into trimmed text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return str(value).strip()


def _read_csv(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError("The CSV file's text encoding could not be read. "
                         "Save it as CSV UTF-8 and try again")
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]


def _read_xlsx(data):
    from openpyxl import load_workbook  # imported lazily: only needed for .xlsx

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise SheetError("The Excel file could not be opened. Check that it "
                         "is a valid .xlsx workbook") from e
    try:
        ws = wb.worksheets[0]
        return [[_cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def read_table(filename, data):
    """Return the first sheet as a list of rows of text cells."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return _read_csv(data)
    if name.endswith(".xlsx"):
        return _read_xlsx(data)
    if name.endswith(".xls"):
        raise SheetError("Old .xls workbooks aren't supported. Save the file as "
                         ".xlsx or .csv first")
    raise SheetError("Only .csv and .xlsx files can be read")


# ---- columns -------------------------------------------------------------

def _plan_columns(headers):
    """Map each column index to what it holds.

    Returns a list of (index, kind, field, vocabulary) where kind is one of the
    RESERVED values, "media" or "meta".
    """
    plan = []
    seen_reserved = set()
    for i, raw in enumerate(headers):
        header = " ".join(raw.split())
        if not header:
            continue
        key = header.lower()
        if key in RESERVED:
            kind = RESERVED[key]
            if kind in seen_reserved:
                raise SheetError(f"The column “{header}” appears more than once")
            seen_reserved.add(kind)
            plan.append((i, kind, None, None))
        elif key.startswith(MEDIA_PREFIX):
            plan.append((i, "media", None, None))
        else:
            m = _VOCAB_HEADER.match(header)
            field, vocab = (m.group(1), m.group(2).strip()) if m else (header, "")
            if not field:
                raise SheetError(f"The column “{header}” has no field name")
            if len(field) > MAX_FIELD_LENGTH:
                raise SheetError(f"The column “{header[:40]}…” has too long a name")
            plan.append((i, "meta", field, vocab))
    if "title" not in seen_reserved:
        raise SheetError("The first row must have a “Title” column header")
    return plan


def split_values(cell, delimiter):
    if not delimiter:
        return [cell] if cell else []
    return [v.strip() for v in cell.split(delimiter) if v.strip()]


# ---- rows ----------------------------------------------------------------

def _is_http_url(url):
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def media_title(url):
    """A display title for a media link: its file name, else the URL."""
    path = urlparse(url).path.rstrip("/")
    name = unquote(path.rsplit("/", 1)[-1]) if path else ""
    return name or url


def validate_row(row, default_access="private"):
    """Check a row dict and fill in defaults. Returns a list of error strings.

    Used both after parsing and again on the server before anything is sent to
    Aviary, since the browser hands the parsed row back for upload.
    """
    errors = []
    if not row.get("title"):
        errors.append("Title is empty")
    elif len(row["title"]) > 1000:
        errors.append("Title is longer than 1000 characters")

    access = (row.get("access") or default_access).strip().lower()
    if access not in ACCESS_VALUES:
        errors.append(f"Access “{row.get('access')}” must be one of: "
                      + ", ".join(ACCESS_VALUES))
    row["access"] = access

    for url in row.get("media", []):
        if not _is_http_url(url):
            errors.append(f"Media URL “{url}” is not an http(s) link")

    for entry in row.get("metadata", []):
        if len(entry.get("value", "")) > MAX_VALUE_LENGTH:
            errors.append(f"A value in “{entry.get('field')}” is too long")
    return errors


def _build_row(number, cells, plan, delimiter, default_access):
    row = {"row": number, "title": "", "access": "", "cuid": "",
           "featured": False, "metadata": [], "media": [], "errors": []}
    featured_raw = ""

    for i, kind, field, vocab in plan:
        cell = cells[i] if i < len(cells) else ""
        if kind == "title":
            row["title"] = cell
        elif kind == "access":
            row["access"] = cell
        elif kind == "cuid":
            row["cuid"] = cell
        elif kind == "featured":
            featured_raw = cell
        elif kind == "media":
            row["media"].extend(split_values(cell, delimiter))
        else:
            for value in split_values(cell, delimiter):
                row["metadata"].append(
                    {"field": field, "value": value, "vocabulary": vocab})

    flag = featured_raw.strip().lower()
    if flag in TRUE_VALUES:
        row["featured"] = True
    elif flag not in FALSE_VALUES:
        row["errors"].append(f"Featured “{featured_raw}” should be yes or no")

    row["errors"].extend(validate_row(row, default_access))
    return row


def parse_sheet(filename, data, delimiter="|", default_access="private",
                max_rows=500):
    """Parse a spreadsheet into a list of row dicts.

    Each row has: row (spreadsheet row number), title, access, cuid, featured,
    metadata [{field, value, vocabulary}], media [url], errors [str].
    Raises SheetError when the file as a whole can't be used.
    """
    table = read_table(filename, data)
    # Skip leading blank lines so a header on row 2 still works.
    start = next((i for i, r in enumerate(table) if any(r)), None)
    if start is None:
        raise SheetError("The file is empty")

    plan = _plan_columns(table[start])
    rows = []
    for offset, cells in enumerate(table[start + 1:], start=start + 2):
        if not any(cells):
            continue
        rows.append(_build_row(offset, cells, plan, delimiter, default_access))
        if len(rows) > max_rows:
            raise SheetError(f"The file has more than {max_rows} rows. "
                             "Split it into smaller files")
    if not rows:
        raise SheetError("The file has a header row but no data rows")

    # Within one file, a custom unique identifier must be unique.
    seen = {}
    for row in rows:
        if row["cuid"]:
            first = seen.setdefault(row["cuid"], row["row"])
            if first != row["row"]:
                row["errors"].append(f"Custom Unique Identifier repeats row {first}")
    return rows


def template_csv(delimiter="|"):
    """A starter spreadsheet with the reserved columns and common fields."""
    out = io.StringIO()
    w = csv.writer(out)
    d = f" {delimiter} "
    w.writerow(["Title", "Access", "Custom Unique Identifier", "Featured",
                "Agent (Creator)", "Date (Created)", "Description",
                "Subject (Topical)", "Keyword", "Language (Primary)",
                "Rights Statement", "Media URL"])
    w.writerow(["Interview with Jane Smith", "private", "OH-0001", "no",
                f"Smith, Jane{d}Doe, John", "1999-01-01",
                "Oral history interview about the 1960s.",
                f"Civil rights{d}Charleston (S.C.)", f"oral history{d}interview",
                "English", "In Copyright",
                f"https://example.org/media/oh-0001-part1.mp3{d}"
                f"https://example.org/media/oh-0001-part2.mp3"])
    return out.getvalue()


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1]
    with open(path, "rb") as f:
        print(json.dumps(parse_sheet(os.path.basename(path), f.read(),
                                     delimiter=os.environ.get("MULTI_VALUE_DELIMITER", "|")),
                         indent=2))
