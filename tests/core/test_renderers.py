import hashlib
import io
from zipfile import ZipFile

import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentRenderer, DocumentSnapshot, synthetic_snapshot
from docx import Document
from pypdf import PdfReader


def test_vietnamese_docx_pdf_share_the_same_immutable_snapshot():
    snapshot = synthetic_snapshot()
    renderer = DocumentRenderer()
    word, pdf = renderer.docx(snapshot), renderer.pdf(snapshot)
    assert word.snapshot_sha256 == pdf.snapshot_sha256 == snapshot.sha256
    assert word.content_sha256 == hashlib.sha256(word.content).hexdigest()
    assert pdf.content_sha256 == hashlib.sha256(pdf.content).hexdigest()
    document = Document(io.BytesIO(word.content))
    assert document.core_properties.identifier == snapshot.sha256
    assert "Đắk Lắk" in "\n".join(p.text for p in document.paragraphs)
    assert document.tables[0].cell(1, 1).text == "1.234,567"
    with ZipFile(io.BytesIO(word.content)) as archive:
        assert "vbaProject.bin" not in "\n".join(archive.namelist())
    reader = PdfReader(io.BytesIO(pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Đắk Lắk" in text and "Cà phê Robusta" in text and "123.456.789,01" in text
    assert snapshot.sha256 in reader.metadata.subject
    embedded = []
    for page in reader.pages:
        for font in page["/Resources"]["/Font"].values():
            descriptor = font.get_object().get("/FontDescriptor")
            if descriptor:
                embedded.append("/FontFile2" in descriptor.get_object())
    assert embedded and all(embedded)


def test_renderer_rejects_mutable_and_invalid_snapshots():
    with pytest.raises(CoreError, match="RENDER_SNAPSHOT_INVALID"):
        DocumentSnapshot(title="test", paragraphs=["mutable"])
    with pytest.raises(CoreError, match="RENDER_SNAPSHOT_INVALID"):
        DocumentSnapshot(title="test", column_headers=("one",), rows=(("a", "b"),))
