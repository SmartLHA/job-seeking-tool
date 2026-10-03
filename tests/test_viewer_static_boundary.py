"""Synthetic static boundary checks; never read real project data or home files."""
import importlib
import json
from pathlib import Path

import pytest


class ResponseSocket:
    def __init__(self):
        self.response = b""

    def sendall(self, data):
        self.response += data


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "viewer"))
    module = importlib.import_module("viewer_server")
    root = tmp_path / "public-root"
    root.mkdir()
    monkeypatch.setattr(module, "PROJECT_ROOT", root)
    return module, root


def write_file(root, relative, content=b"public fixture"):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_loopback_default(viewer):
    module, _ = viewer
    assert module.VIEWER_HOST == "127.0.0.1"


def test_all_public_files_and_index_aliases(viewer):
    module, root = viewer
    for relative in module._PUBLIC_STATIC_FILES:
        write_file(root, relative)
        sock = ResponseSocket()
        assert module.serve_file(sock, "/" + relative)
        assert sock.response.startswith(b"HTTP/1.1 200 OK\r\n")
        assert sock.response.endswith(b"public fixture")
    for path in ["/", "/viewer", "/viewer/"]:
        assert module.serve_file(ResponseSocket(), path)


@pytest.mark.parametrize("path", [
    "/.env", "/.git/config", "/src/ui_handlers.py", "/viewer/viewer_server.py",
    "/profiles/profile.json", "/state/jobs.json", "/docs/private.md",
    "/viewer/private.json", "/viewer/trust_log.json", "/viewer/system_kanban.html",
    "/viewer/../INDEX.md", "/viewer/%2e%2e/INDEX.md", "/viewer/%2E%2E/INDEX.md",
    "/viewer/%252e%252e/INDEX.md", "/viewer/./app.js", "/viewer/%2e/app.js",
    "/viewer%5capp.js", "/viewer/app.js%00", "//viewer/app.js",
])
def test_nonpublic_and_traversal_rejected(viewer, path):
    module, root = viewer
    for relative in [
        ".env", ".git/config", "src/ui_handlers.py", "viewer/viewer_server.py",
        "profiles/profile.json", "state/jobs.json", "docs/private.md",
        "viewer/private.json", "viewer/trust_log.json", "viewer/system_kanban.html",
        "INDEX.md", "viewer/app.js",
    ]:
        write_file(root, relative, b"synthetic fixture")
    sock = ResponseSocket()
    assert module.serve_file(sock, path) is False
    assert sock.response == b""


def test_untrusted_manifest_cannot_grant_access(viewer):
    module, root = viewer
    write_file(root, "viewer/documents.json", json.dumps([{"path": "/docs/private.md"}]).encode())
    write_file(root, "docs/private.md", b"synthetic private fixture")
    assert module.serve_file(ResponseSocket(), "/viewer/documents.json")
    assert module.serve_file(ResponseSocket(), "/docs/private.md") is False


@pytest.mark.parametrize("outside", [False, True])
def test_public_file_symlinks_rejected(viewer, tmp_path, outside):
    module, root = viewer
    target_root = tmp_path if outside else root
    target = write_file(target_root, "synthetic-target.md")
    (root / "INDEX.md").symlink_to(target)
    assert module.serve_file(ResponseSocket(), "/INDEX.md") is False


def test_public_parent_symlink_rejected(viewer, tmp_path):
    module, root = viewer
    target = tmp_path / "linked-viewer"
    target.mkdir()
    write_file(target, "app.js")
    (root / "viewer").symlink_to(target, target_is_directory=True)
    assert module.serve_file(ResponseSocket(), "/viewer/app.js") is False


def test_manifest_uses_only_canonical_public_document_paths(viewer):
    module, _ = viewer
    manifest = Path(__file__).resolve().parents[1] / "viewer" / "documents.json"
    for entry in json.loads(manifest.read_text()):
        path = entry["path"]
        if path.startswith("https://"):
            continue
        assert path.startswith("/")
        assert ".." not in path.split("/")
        assert path[1:] in module._PUBLIC_STATIC_FILES
