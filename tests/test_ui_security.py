"""Security boundary tests for the loopback-only local UI."""
from __future__ import annotations

from email.message import Message
import io
import json
import logging
import socket
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from src.ui_routes import (
    MAX_CV_UPLOAD_BODY_BYTES,
    MAX_REQUEST_BODY_BYTES,
    _build_handler,
    _http_url,
    _server_class_for_host,
    build_parser,
)
from src.ui_state import UIServerConfig


def _make_handler(
    tmp_path: Path,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: bytes = b"",
):
    config = UIServerConfig(
        profile_path=tmp_path / "profile.json",
        state_root=tmp_path / "state",
        report_dir=tmp_path / "reports",
        host="127.0.0.1",
        port=0,
    )
    handler_type = _build_handler(config)
    handler = handler_type.__new__(handler_type)
    handler.command = method
    handler.path = "/missing"
    handler.headers = Message()
    for name, value in (headers or {}).items():
        handler.headers[name] = value
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} /missing HTTP/1.1"
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 9000))
    return handler


def _response(handler) -> tuple[int, bytes]:
    raw_response = handler.wfile.getvalue()
    status = int(raw_response.split(b" ", 2)[1])
    body = raw_response.split(b"\r\n\r\n", 1)[1]
    return status, body


@pytest.mark.parametrize("host", ["127.0.0.1", "127.10.20.30", "::1", "localhost"])
def test_host_parser_accepts_loopback_only(host: str) -> None:
    args = build_parser().parse_args(["--profile", "profile.json", "--host", host])
    assert args.host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_host_parser_rejects_non_loopback(host: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--profile", "profile.json", "--host", host])


def test_ipv6_loopback_selects_ipv6_server() -> None:
    assert _server_class_for_host("::1").address_family == socket.AF_INET6
    assert _server_class_for_host("127.0.0.1").address_family == socket.AF_INET
    assert _server_class_for_host("localhost").address_family == socket.AF_INET


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "http://127.0.0.1:9000"),
        ("localhost", "http://localhost:9000"),
        ("::1", "http://[::1]:9000"),
    ],
)
def test_http_url_formats_loopback_hosts(host: str, expected: str) -> None:
    assert _http_url(host, 9000) == expected


@pytest.mark.parametrize(
    ("content_length", "expected_status"),
    [
        ("not-a-number", HTTPStatus.BAD_REQUEST),
        ("-1", HTTPStatus.BAD_REQUEST),
        (str(MAX_REQUEST_BODY_BYTES + 1), HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    ],
)
def test_invalid_content_length_fails_before_body_read(
    tmp_path: Path,
    content_length: str,
    expected_status: HTTPStatus,
) -> None:
    handler = _make_handler(
        tmp_path,
        headers={"Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000", "Content-Length": content_length},
    )
    handler.rfile = mock.Mock()
    handler.rfile.read.side_effect = AssertionError("body must not be read")

    handler.do_POST()

    status, body = _response(handler)
    assert status == expected_status
    assert json.loads(body)["ok"] is False
    handler.rfile.read.assert_not_called()


@pytest.mark.parametrize("file_size", [2 * 1024 * 1024, 5 * 1024 * 1024, 5 * 1024 * 1024 + 1])
def test_cv_upload_dispatcher_preserves_file_size_limit(tmp_path: Path, file_size: int) -> None:
    boundary = "synthetic-cv-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="cv_file"; filename="synthetic.txt"\r\n'
        'Content-Type: text/plain\r\n\r\n'
    ).encode() + b"X" * file_size + f"\r\n--{boundary}--\r\n".encode()
    handler = _make_handler(tmp_path, headers={
        "Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }, body=body)
    handler.path = "/profile/parse-cv"

    def parse_synthetic_cv(path: Path) -> str:
        assert path.stat().st_size == file_size
        return "Synthetic business analyst CV"

    with mock.patch("src.ui_handlers.parse_cv_file", side_effect=parse_synthetic_cv) as parse_cv:
        with mock.patch("src.job_hunt_parsing.extract_skills_from_cv", return_value=([], None)):
            handler.do_POST()

    status, response_body = _response(handler)
    payload = json.loads(response_body)
    if file_size > 5 * 1024 * 1024:
        assert status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert payload == {"ok": False, "error": "File too large. Maximum size is 5 MB."}
        parse_cv.assert_not_called()
    else:
        assert status == HTTPStatus.OK
        assert payload["ok"] is True
        parse_cv.assert_called_once()


@pytest.mark.parametrize(
    ("path", "content_type", "length", "expected_status"),
    [
        ("/profile/parse-cv", "multipart/form-data; boundary=synthetic", str(MAX_CV_UPLOAD_BODY_BYTES + 1), 413),
        ("/profile/parse-cv", "multipart/form-data; boundary=synthetic", "not-a-number", 400),
        ("/profile/parse-cv", "multipart/form-data; boundary=synthetic", "-1", 400),
        ("/profile/parse-cv", "text/plain", str(MAX_REQUEST_BODY_BYTES + 1), 413),
        ("/profile/parse-cv", "application/json; charset=multipart/form-data", str(MAX_REQUEST_BODY_BYTES + 1), 413),
        ("/profile/parse-cv/", "multipart/form-data; boundary=synthetic", str(MAX_REQUEST_BODY_BYTES + 1), 413),
        ("/profile/parse-cv-extra", "multipart/form-data; boundary=synthetic", str(MAX_REQUEST_BODY_BYTES + 1), 413),
    ],
)
def test_upload_transport_limit_rejects_before_read(
    tmp_path: Path, path: str, content_type: str, length: str, expected_status: int
) -> None:
    handler = _make_handler(tmp_path, headers={
        "Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000",
        "Content-Type": content_type, "Content-Length": length,
    })
    handler.path = path
    handler.rfile = mock.Mock()
    handler.rfile.read.side_effect = AssertionError("body must not be read")

    with mock.patch("src.ui_routes.handle_parse_cv") as parse_cv:
        handler.do_POST()

    assert _response(handler)[0] == expected_status
    handler.rfile.read.assert_not_called()
    parse_cv.assert_not_called()


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example:9000", "Origin": "http://attacker.example:9000"},
    {"Host": "127.0.0.1:9000", "Origin": "https://attacker.example"},
])
def test_upload_transport_allowance_preserves_source_checks(tmp_path: Path, headers: dict[str, str]) -> None:
    handler = _make_handler(tmp_path, headers={**headers,
        "Content-Type": "multipart/form-data; boundary=synthetic",
        "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1),
    })
    handler.path = "/profile/parse-cv"
    handler.rfile = mock.Mock()
    handler.rfile.read.side_effect = AssertionError("body must not be read")

    handler.do_POST()

    assert _response(handler)[0] == HTTPStatus.FORBIDDEN
    handler.rfile.read.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "127.0.0.1:9000", "Origin": "https://attacker.example"},
        {"Host": "127.0.0.1:9000", "Origin": "null"},
        {"Host": "127.0.0.1:9000", "Referer": "http://attacker.example/form"},
        {
            "Host": "attacker.example:9000",
            "Origin": "http://attacker.example:9000",
        },
        {"Host": "127.0.0.1:9001", "Origin": "http://127.0.0.1:9001"},
    ],
)
def test_cross_origin_browser_posts_are_rejected(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    handler = _make_handler(tmp_path, headers={**headers, "Content-Length": "0"})

    handler.do_POST()

    status, body = _response(handler)
    assert status == HTTPStatus.FORBIDDEN
    assert json.loads(body) == {
        "ok": False,
        "error": "Cross-origin requests are not allowed.",
    }


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000"},
        {
            "Host": "127.0.0.1:9000",
            "Referer": "http://127.0.0.1:9000/profile",
        },
        {"Host": "localhost:9000", "Origin": "http://localhost:9000"},
        {"Host": "[::1]:9000", "Origin": "http://[::1]:9000"},
    ],
)
def test_same_origin_posts_remain_compatible(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    handler = _make_handler(tmp_path, headers={**headers, "Content-Length": "0"})

    handler.do_POST()

    status, _body = _response(handler)
    assert status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unhandled_errors_are_generic_but_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
) -> None:
    handler = _make_handler(
        tmp_path,
        method=method,
        headers={"Host": "127.0.0.1", "Content-Length": "0"},
    )
    secret_detail = "private filesystem detail"
    monkeypatch.setattr(
        type(handler),
        f"_do_{method}_inner",
        lambda self: (_ for _ in ()).throw(RuntimeError(secret_detail)),
    )

    with caplog.at_level(logging.ERROR, logger="src.ui_routes"):
        getattr(handler, f"do_{method}")()

    status, body = _response(handler)
    assert status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert secret_detail.encode() not in body
    assert b"Internal server error." in body
    assert secret_detail in caplog.text


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('host', [None, '', '127.0.0.1:9001', 'example.com:9000',
    'user@localhost:9000', 'localhost:9000/path', 'localhost:9000?x',
    'localhost:9000#x', 'localhost:', '::1:9000', '[::1',
    'localhost:abc', '[::1]evil:9000', ' localhost:9000', 'localhost:9000\\path', 'duplicate'])
def test_host_boundary_before_dispatch_and_read(tmp_path, method, host):
    handler = _make_handler(tmp_path, method=method,
        headers={'Origin': 'http://127.0.0.1:9000'})
    if host is not None:
        handler.headers['Host'] = '127.0.0.1:9000' if host == 'duplicate' else host
    if host == 'duplicate':
        handler.headers['Host'] = '127.0.0.1:9000'
    handler.path = '/job/synthetic/explain'
    handler.rfile = mock.Mock()
    with mock.patch('src.ui_routes.handle_job_explain') as provider:
        getattr(handler, 'do_' + method)()
        assert _response(handler)[0] == 403
        provider.assert_not_called()
    handler.rfile.read.assert_not_called()


@pytest.mark.parametrize('sources', [{}, {'Origin': 'null'}, {'Origin': ''},
    {'Origin': 'http://127.0.0.1:9001'}, {'Origin': 'https://127.0.0.1:9000'},
    {'Origin': 'http://127.0.0.1:9000', 'Referer': 'http://localhost:9000/'},
    {'Referer': 'http://user@127.0.0.1:9000/'},
    {'Origin': 'http://127.0.0.1:9000/path'}, {'Origin': 'duplicate'}])
def test_post_origin_boundary_before_body_and_provider(tmp_path, sources):
    handler = _make_handler(tmp_path, headers={'Host': '127.0.0.1:9000', **sources})
    if sources.get('Origin') == 'duplicate':
        handler.headers['Origin'] = 'http://127.0.0.1:9000'
    handler.path = '/job/synthetic/explain'
    handler.rfile = mock.Mock()
    with mock.patch('src.ui_routes.handle_job_explain') as provider:
        handler.do_POST()
        assert _response(handler)[0] == 403
        provider.assert_not_called()
    handler.rfile.read.assert_not_called()


def test_explanation_get_has_allow_post_without_provider(tmp_path):
    handler = _make_handler(tmp_path, method='GET', headers={'Host': '127.0.0.1:9000'})
    handler.path = '/job/synthetic/explain'
    with mock.patch('src.ui_routes.handle_job_explain') as provider:
        handler.do_GET()
        assert _response(handler)[0] == 405
        assert b'Allow: POST\r\n' in handler.wfile.getvalue()
        provider.assert_not_called()


@pytest.mark.parametrize('sources', [
    {'Origin': 'http://127.0.0.1:9000'},
    {'Referer': 'http://127.0.0.1:9000/profile?tab=cv'},
    {'Origin': 'http://127.0.0.1:9000', 'Referer': 'http://127.0.0.1:9000/profile'}])
def test_explanation_same_origin_post_dispatches_once(tmp_path, sources):
    handler = _make_handler(tmp_path, headers={'Host': '127.0.0.1:9000', **sources})
    handler.path = '/job/synthetic/explain'
    with mock.patch('src.ui_routes.handle_job_explain') as provider:
        handler.do_POST()
        provider.assert_called_once()
        assert provider.call_args.args[-1] == 'synthetic'


def test_rendered_explanation_fetch_is_post():
    # Inspect the actual renderer function, rather than a copied JS fixture.
    import inspect
    from src import ui_render
    source = inspect.getsource(ui_render)
    assert 'fetch("/job/{job_id_esc}/explain",{{method:"POST"}})' in source


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_explanation_actual_handler_mocked_provider(tmp_path, method):
    handler = _make_handler(tmp_path, method=method,
        headers={'Host': '127.0.0.1:9000', 'Origin': 'http://127.0.0.1:9000'})
    handler.path = '/job/synthetic/explain'
    profile, job, analysis = object(), object(), object()
    with mock.patch('src.ui_handlers.load_candidate_profile', return_value=profile), \
         mock.patch('src.ui_handlers.load_reviewed_job', return_value=job), \
         mock.patch('src.ui_handlers.load_job_analysis', return_value=analysis), \
         mock.patch('src.job_hunt_llm.explain_job_match_with_llm',
                    return_value=({'fit': 'Synthetic fit'}, None)) as provider:
        getattr(handler, 'do_' + method)()
        if method == 'GET':
            assert _response(handler)[0] == 405
            provider.assert_not_called()
        else:
            assert _response(handler)[0] == 200
            assert json.loads(_response(handler)[1])['fit'] == 'Synthetic fit'
            provider.assert_called_once_with(profile, job, analysis)
