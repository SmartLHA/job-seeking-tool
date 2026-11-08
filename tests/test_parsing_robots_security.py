from unittest.mock import patch

import pytest
from src import job_hunt_parsing as parsing


@pytest.mark.parametrize('first', ['/open', '/private'])
def test_rules_apply_to_each_path_and_user_agent(first):
    cache = parsing._RobotsCache()
    with patch.object(parsing, '_fetch_robots_lines', return_value=['User-agent: Restricted', 'Disallow: /', 'User-agent: *', 'Disallow: /private']) as fetch:
        first_allowed = cache.is_allowed('https://reed.co.uk' + first, 'Example')
        assert first_allowed == (first == '/open')
        assert cache.is_allowed('https://reed.co.uk/open', 'Example') is True
        assert cache.is_allowed('https://reed.co.uk/private', 'Example') is False
        assert cache.is_allowed('https://reed.co.uk/open', 'Restricted') is False
    assert len(cache._cache) == 1


def test_cache_separates_origins_and_expires():
    cache = parsing._RobotsCache()
    with patch.object(parsing, '_fetch_robots_lines', return_value=['User-agent: *', 'Allow: /']), patch.object(parsing.time, 'time', return_value=1000) as clock:
        assert cache.is_allowed('https://reed.co.uk/open', 'Example')
        assert cache.is_allowed('http://reed.co.uk/open', 'Example')
        clock.return_value = 1301
        assert cache.is_allowed('https://reed.co.uk/open', 'Example')
    assert len(cache._cache) == 2
    assert cache._cache['https://reed.co.uk'][1] == 1301


def test_robots_timeout_is_explicit_and_fails_closed():
    cache = parsing._RobotsCache()
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing.time, 'monotonic', return_value=10), patch.object(parsing, 'urlopen', side_effect=TimeoutError) as transport:
        assert cache.is_allowed('https://reed.co.uk/open', 'Example', deadline=13) is False
        assert cache.is_allowed('https://reed.co.uk/another', 'Example', deadline=13) is False
    assert transport.call_count == 1
    assert transport.call_args.kwargs['timeout'] == 3


def test_robots_unsafe_redirect_never_requested():
    from io import BytesIO
    from urllib.error import HTTPError
    error = HTTPError('https://reed.co.uk/robots.txt', 302, 'Found', {'Location': 'https://evil.example/robots.txt'}, BytesIO())
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing, 'urlopen', side_effect=error) as transport:
        assert parsing._RobotsCache().is_allowed('https://reed.co.uk/open', 'Example') is False
    assert transport.call_count == 1


def test_exhausted_budget_prevents_robots_request():
    with patch.object(parsing, '_check_ssrf'), patch.object(parsing.time, 'monotonic', return_value=10), patch.object(parsing, 'urlopen') as transport:
        assert parsing._RobotsCache().is_allowed('https://reed.co.uk/open', 'Example', deadline=9) is False
    transport.assert_not_called()
