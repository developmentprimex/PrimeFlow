"""Download and extract the contents of an authorized Discord attachment."""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Iterable, Iterator
from datetime import date, datetime, time
from pathlib import PurePath
from urllib.parse import urlsplit
from zipfile import ZipFile

import httpx

from app.schemas.ga_discord_mentions import DiscordAttachmentLink

CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
TEXT_EXTENSIONS = {".txt", ".pdf", ".docx"}
TABLE_EXTENSIONS = {".csv", ".xls", ".xlsx", ".xlsm"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MAX_DOWNLOAD = 12 * 1024**2
MAX_IMAGE = 4 * 1024**2
MAX_EXPANDED_OFFICE = 40 * 1024**2
MAX_TEXT = 140_000
MAX_ROWS = 2_000
MAX_COLUMNS = 256
MAX_SHEETS = 64
MAX_PDF_PAGES = 100


class AttachmentError(ValueError):
    """An attachment error safe to show without disclosing its signed URL."""


def attachment_extension(name: str) -> str:
    suffix = PurePath(name).suffix.lower()
    if suffix not in TEXT_EXTENSIONS | TABLE_EXTENSIONS | IMAGE_TYPES.keys():
        raise AttachmentError("Format i pambështetur. Përdor XLSX, XLS, XLSM, CSV, DOCX, PDF, TXT, PNG ose JPG.")
    return suffix


async def download_attachment(attachment: DiscordAttachmentLink, *, limit: int) -> bytes:
    try:
        url = urlsplit(attachment.url)
    except ValueError:
        raise AttachmentError("Linku i skedarit nuk është i vlefshëm.") from None
    if url.scheme != "https" or url.netloc not in CDN_HOSTS or not url.path.startswith("/attachments/"):
        raise AttachmentError("Skedari nuk vjen nga CDN-ja e Discord-it.")

    data = bytearray()
    try:
        async with (
            asyncio.timeout(18),
            httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client,
            client.stream("GET", attachment.url, headers={"Accept-Encoding": "identity"}) as response,
        ):
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise AttachmentError("Kodimi i skedarit nga Discord nuk mbështetet.")
            declared = response.headers.get("content-length")
            if declared and declared.isdecimal() and int(declared) > limit:
                raise AttachmentError(f"Skedari tejkalon kufirin prej {limit // 1024**2} MB.")
            async for chunk in response.aiter_raw(chunk_size=65536):
                if len(data) + len(chunk) > limit:
                    raise AttachmentError(f"Skedari tejkalon kufirin prej {limit // 1024**2} MB.")
                data.extend(chunk)
    except (httpx.HTTPError, TimeoutError):
        raise AttachmentError("Skedari nuk u shkarkua nga Discord. Provo përsëri.") from None
    return bytes(data)


def _decoded_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        if encoding != "utf-8-sig":
            raise
        text = data.decode("cp1252")
    if "\x00" in text:
        raise AttachmentError("Skedari nuk përmban tekst të lexueshëm.")
    return text


def _office_archive(data: bytes) -> None:
    with ZipFile(io.BytesIO(data)) as archive:
        files = archive.infolist()
        if len(files) > 2_000 or sum(file.file_size for file in files) > MAX_EXPANDED_OFFICE:
            raise AttachmentError("Dokumenti është shumë i madh për t'u përpunuar.")
        if any(file.flag_bits & 1 for file in files):
            raise AttachmentError("Dokumenti është i mbrojtur me fjalëkalim.")


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def _tables(sheets: Iterable[tuple[str, Iterable[Iterable[object]]]], *, csv_input: bool = False) -> dict:
    remaining_rows, remaining_text = MAX_ROWS, MAX_TEXT
    result = []
    truncated = False
    line = io.StringIO(newline="")
    writer = csv.writer(line)
    for name, rows in sheets:
        if len(result) == MAX_SHEETS:
            truncated = True
            break
        lines = []
        sheet_truncated = False
        for row in rows:
            if remaining_rows == 0 or remaining_text == 0:
                sheet_truncated = True
                break
            values = list(row)
            if len(values) > MAX_COLUMNS:
                values = values[:MAX_COLUMNS]
                sheet_truncated = True
            if not csv_input:
                while values and values[-1] is None:
                    values.pop()
            line.seek(0)
            line.truncate(0)
            writer.writerow(_cell_text(value) for value in values)
            csv_row = line.getvalue()
            if len(csv_row) > remaining_text:
                sheet_truncated = True
                remaining_text = 0
                break
            lines.append(csv_row)
            remaining_rows -= 1
            remaining_text -= len(csv_row)
        result.append({"name": name, "csv": "".join(lines), "row_count": len(lines), "truncated": sheet_truncated})
        truncated |= sheet_truncated
    return {"kind": "table", "sheets": result, "truncated": truncated}


def _excel_xlsx(data: bytes) -> dict:
    from openpyxl import load_workbook

    _office_archive(data)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    try:
        # Iterate actual rows instead of trusting the worksheet's dimensions.
        def sheets():
            for sheet in workbook.worksheets:
                sheet.reset_dimensions()
                yield sheet.title, sheet.values

        return _tables(sheets())
    finally:
        workbook.close()


def _excel_xls(data: bytes) -> dict:
    import xlrd

    def rows(sheet) -> Iterator[list[object]]:
        for index in range(sheet.nrows):
            values = []
            for cell in sheet.row(index):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    values.append(xlrd.xldate_as_datetime(cell.value, workbook.datemode))
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    values.append(bool(cell.value))
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    values.append(xlrd.error_text_from_code.get(cell.value, "#ERROR!"))
                else:
                    values.append(cell.value)
            yield values

    workbook = xlrd.open_workbook(file_contents=data, on_demand=True, ragged_rows=True)
    try:
        return _tables((name, rows(workbook.sheet_by_index(index))) for index, name in enumerate(workbook.sheet_names()))
    finally:
        workbook.release_resources()


def _csv(data: bytes, name: str) -> dict:
    text = _decoded_text(data)
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    return _tables([(name, rows)], csv_input=True)


def _plain_text(parts: Iterable[str]) -> dict:
    blocks = []
    remaining = MAX_TEXT
    truncated = False
    for part in parts:
        if not part:
            continue
        if len(part) > remaining:
            blocks.append(part[:remaining])
            truncated = True
            break
        blocks.append(part)
        remaining -= len(part)
    return {"kind": "text", "text": "".join(blocks).strip(), "truncated": truncated}


def _word(data: bytes) -> dict:
    from docx import Document
    from docx.text.paragraph import Paragraph

    _office_archive(data)
    document = Document(io.BytesIO(data))

    def blocks():
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                yield block.text + "\n"
            else:
                for row in block.rows:
                    yield "\t".join(cell.text for cell in row.cells) + "\n"

    return _plain_text(blocks())


def _pdf(data: bytes) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise AttachmentError("PDF-ja është e mbrojtur me fjalëkalim.")
    page_count = len(reader.pages)
    result = _plain_text(
        text + "\n\n" for page in reader.pages[:MAX_PDF_PAGES] if (text := page.extract_text()).strip()
    )
    result["truncated"] |= page_count > MAX_PDF_PAGES
    if not result["text"]:
        result["note"] = "Nuk u gjet tekst i nxjerrshëm në faqet e lexuara. PDF-ja mund të jetë skanim."
    return result


def extract_attachment(data: bytes, name: str, suffix: str) -> dict:
    """Extract data without running macros or fetching document relationships."""
    try:
        if suffix in {".xlsx", ".xlsm"}:
            return _excel_xlsx(data)
        if suffix == ".xls":
            return _excel_xls(data)
        if suffix == ".csv":
            return _csv(data, name)
        if suffix == ".docx":
            return _word(data)
        if suffix == ".pdf":
            return _pdf(data)
        if suffix == ".txt":
            return _plain_text([_decoded_text(data)])
        from PIL import Image

        with Image.open(io.BytesIO(data), formats=("PNG", "JPEG")) as image:
            if image.width * image.height > 24_000_000:
                raise AttachmentError("Fotoja tejkalon kufirin prej 24 megapikselësh.")
            mime_type = Image.MIME.get(image.format)
            if mime_type != IMAGE_TYPES[suffix]:
                raise AttachmentError("Formati i fotos nuk përputhet me prapashtesën e skedarit.")
            if image.format == "JPEG":
                image.load()
            else:
                image.verify()
        return {"kind": "image", "mime_type": mime_type}
    except AttachmentError:
        raise
    except Exception:  # noqa: BLE001 - external parsers can raise format-specific errors
        # Parser errors can contain document content and internal filenames.
        raise AttachmentError("Përmbajtja e skedarit nuk mund të lexohej në këtë format.") from None
