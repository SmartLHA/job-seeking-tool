"""Offline tests for validation before each redirect request."""
from email.message import Message
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from src import job_hunt_parsing as parsing


def redirect(url, destination):
    return HTTPError(url, 302, 'Found', {'Location': destination}, BytesIO())


class Page:
    def __init__(self, url):
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = 'text/html; charset=utf-8'
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url
    def read(self, limit): return b'<html><body>Business Analyst<br>Company: Example</body></html>'


@pytest.mark.parametrize('destination', ['https://evil.example/job', 'http://reed.co.uk/job', 'https://127.0.0.1/job'])
def test_unsafe_destination_never_requested(destination):
    original = 'https://reed.co.uk/start'
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing._robots_cache, 'is_allowed', return_value=True), patch.object(parsing, 'urlopen', side_effect=redirect(original, destination)) as transport:
        with pytest.raises(parsing.JobParsingError):
            parsing.parse_job_from_url(original)
    assert transport.call_count == 1
    assert transport.call_args.args[0].full_url == original


def test_relative_redirect_validated_then_fetched():
    original, final = 'https://reed.co.uk/start', 'https://reed.co.uk/next'
    with patch.object(parsing, '_check_ssrf') as dns, patch.object(parsing._robots_cache, 'is_allowed', return_value=True) as robots, patch.object(parsing, 'urlopen', side_effect=[redirect(original, '/next'), Page(final)]) as transport:
        result = parsing.parse_job_from_url(original)
    assert result['source_ref'] == original
    assert [c.args[0].full_url for c in transport.call_args_list] == [original, final]
    assert [c.args[0] for c in robots.call_args_list] == [original, final]
    assert dns.call_count == 2


def test_redirect_hops_are_bounded():
    def hop(request, **kwargs):
        number = int(request.full_url.rsplit('/', 1)[1])
        raise redirect(request.full_url, '/' + str(number + 1))
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing._robots_cache, 'is_allowed', return_value=True), patch.object(parsing, 'urlopen', side_effect=hop) as transport:
        with pytest.raises(parsing.JobParsingError, match='Too many redirects'):
            parsing.parse_job_from_url('https://reed.co.uk/0')
    assert transport.call_count == parsing.MAX_REDIRECTS + 1


def test_opener_refuses_implicit_redirect():
    handler = parsing._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, 'Found', {}, 'https://evil.example') is None


def test_allowlisted_redirect_private_dns_never_requested():
    original = 'https://reed.co.uk/start'
    with patch.object(parsing, '_check_ssrf', side_effect=[None, parsing.JobParsingError('private address')]), patch.object(parsing._robots_cache, 'is_allowed', return_value=True), patch.object(parsing, 'urlopen', side_effect=redirect(original, 'https://www.reed.co.uk/next')) as transport:
        with pytest.raises(parsing.JobParsingError, match='private address'):
            parsing.parse_job_from_url(original)
    assert transport.call_count == 1


def test_redirect_robots_denial_never_requests_destination():
    original = 'https://reed.co.uk/start'
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing._robots_cache, 'is_allowed', side_effect=[True, False]), patch.object(parsing, 'urlopen', side_effect=redirect(original, '/private')) as transport:
        with pytest.raises(parsing.JobParsingError, match='robots'):
            parsing.parse_job_from_url(original)
    assert transport.call_count == 1
