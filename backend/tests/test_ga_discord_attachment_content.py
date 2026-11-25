import asyncio
import csv
import io
from unittest.mock import patch

import httpx
import pytest
from docx import Document
from openpyxl import Workbook
from PIL import Image
from reportlab.pdfgen import canvas

from app.schemas.ga_discord_mentions import DiscordAttachmentLink
from app.services import ga_discord_attachment_content as attachments


def test_workbook_has_named_sheets_and_a_shared_row_limit(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_ROWS", 4)
    workbook = Workbook()
    workbook.active.title = "Porositë"
    workbook.active.append(["Artikulli", "Sasia"])
    workbook.active.append(["A, B", 5])
    second = workbook.create_sheet("Detajet")
    for index in range(3):
        second.append([index])
    output = io.BytesIO()
    workbook.save(output)

    result = attachments.extract_attachment(output.getvalue(), "porosite.xlsx", ".xlsx")

    assert result["truncated"]
    first, second = result["sheets"]
    assert first["name"] == "Porositë" and not first["truncated"]
    assert list(csv.reader(io.StringIO(first["csv"]))) == [["Artikulli", "Sasia"], ["A, B", "5"]]
    assert second["name"] == "Detajet" and second["truncated"]
    assert second["row_count"] == 2


def test_csv_uses_quoted_cells_and_detects_separator():
    data = 'Titulli;Sasia\r\n"A; B";2\r\n'.encode("utf-8-sig")
    result = attachments.extract_attachment(data, "porosite.csv", ".csv")
    assert result["kind"] == "table"
    assert list(csv.reader(io.StringIO(result["sheets"][0]["csv"]))) == [["Titulli", "Sasia"], ["A; B", "2"]]


def test_extracting_text_from_word_pdf_and_txt():
    document = Document()
    document.add_paragraph("Hyrja e raportit")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Emri", "Sasia"
    docx = io.BytesIO()
    document.save(docx)

    pdf = io.BytesIO()
    writer = canvas.Canvas(pdf)
    writer.drawString(30, 650, "PDF i raportit")
    writer.save()

    assert attachments.extract_attachment(docx.getvalue(), "raport.docx", ".docx")["text"] == "Hyrja e raportit\nEmri\tSasia"
    assert attachments.extract_attachment(pdf.getvalue(), "raport.pdf", ".pdf")["text"] == "PDF i raportit"
    assert attachments.extract_attachment("Shënimi".encode("utf-16"), "note.txt", ".txt")["text"] == "Shënimi"


@pytest.mark.parametrize(("format_name", "suffix", "mime"), [("PNG", ".png", "image/png"), ("JPEG", ".jpg", "image/jpeg")])
def test_image_is_verified_and_retains_the_detected_mime_type(format_name, suffix, mime):
    output = io.BytesIO()
    Image.new("RGB", (4, 4)).save(output, format=format_name)
    assert attachments.extract_attachment(output.getvalue(), "photo" + suffix, suffix) == {"kind": "image", "mime_type": mime}
    with pytest.raises(attachments.AttachmentError):
        attachments.extract_attachment(b"not an image", "photo" + suffix, suffix)


class ByteStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"text"
        yield b"data"


def test_cdn_download_has_no_auth_header_redirects_or_unbounded_stream():
    requests = []

    def discord(request):
        requests.append(request)
        if request.url.path.endswith("/redirect.txt"):
            return httpx.Response(302, headers={"Location": "https://example.org/"})
        return httpx.Response(200, stream=ByteStream())

    def file(url):
        return DiscordAttachmentLink(name="test.txt", content_type="text/plain", url=url)

    def mock_client(**kwargs):
        return client_type(transport=httpx.MockTransport(discord), **kwargs)

    async def check():
        cdn = "https://cdn.discordapp.com/attachments/1/2"
        assert await attachments.download_attachment(file(cdn + "/test.txt"), limit=8) == b"textdata"
        with pytest.raises(attachments.AttachmentError, match="kufirin"):
            await attachments.download_attachment(file(cdn + "/test.txt"), limit=7)
        with pytest.raises(attachments.AttachmentError, match="nuk u shkarkua"):
            await attachments.download_attachment(file(cdn + "/redirect.txt"), limit=8)
        with pytest.raises(attachments.AttachmentError, match="CDN"):
            await attachments.download_attachment(file("https://example.org/attachments/1/2/test.txt"), limit=8)

    client_type = httpx.AsyncClient
    with patch.object(attachments.httpx, "AsyncClient", side_effect=mock_client):
        asyncio.run(check())
    assert len(requests) == 3 and all("authorization" not in request.headers for request in requests)
