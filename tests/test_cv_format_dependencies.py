"""Synthetic CV format checks; actual-library tests fail clearly if not installed."""
from __future__ import annotations

import builtins
from importlib.metadata import version
from pathlib import Path

import pytest

from src.job_hunt_profile import parse_cv_file


def _minimal_pdf(text: str) -> bytes:
    """A deterministic single-page PDF with a standard font and valid xref."""
    stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n'.encode('ascii')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n' + stream + b'endstream',
    ]
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{index} 0 obj\n'.encode('ascii') + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode('ascii'))
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode('ascii'))
    return bytes(result)


def test_actual_pdf_library_extracts_synthetic_text(tmp_path: Path):
    from pypdf import PdfReader
    assert PdfReader.__module__ == 'pypdf._reader'
    print('actual pypdf=' + version('pypdf'))
    path = tmp_path/'synthetic.pdf'
    path.write_bytes(_minimal_pdf('Synthetic CV PDF skill SQL'))
    assert 'Synthetic CV PDF skill SQL' in parse_cv_file(path)


def test_actual_docx_library_extracts_generated_document(tmp_path: Path):
    from docx import Document
    assert Document.__module__ == 'docx.api'
    print('actual python-docx=' + version('python-docx'))
    path = tmp_path/'synthetic.docx'
    document = Document()
    document.add_paragraph('Synthetic CV DOCX skill Python')
    document.add_paragraph('Synthetic second paragraph')
    document.save(path)
    assert parse_cv_file(path) == 'Synthetic CV DOCX skill Python\nSynthetic second paragraph'


def test_txt_extraction_is_unchanged(tmp_path: Path):
    path = tmp_path/'synthetic.txt'
    path.write_bytes(b'Synthetic CV TXT skill SQL\nInvalid byte: \xff')
    assert parse_cv_file(path) == 'Synthetic CV TXT skill SQL\nInvalid byte: \ufffd'


@pytest.mark.parametrize('suffix,module,package', [('.pdf','pypdf','pypdf'),('.docx','docx','python-docx')])
def test_missing_format_dependency_has_install_guidance(tmp_path, monkeypatch, suffix, module, package):
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == module:
            raise ModuleNotFoundError(f'No module named {module}', name=module)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    with pytest.raises(RuntimeError) as exc:
        parse_cv_file(tmp_path/('synthetic'+suffix))
    assert package in str(exc.value)
    assert 'venv/bin/python -m pip install -r requirements-dev.txt' in str(exc.value)
