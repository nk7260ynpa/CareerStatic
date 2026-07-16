"""crawler.client 的單元測試（不發真實網路請求）。"""

import pytest

from careerstatic.crawler.client import Client104, CrawlError


class FakeResponse:
    """模擬 curl_cffi 回應。"""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("非 JSON 回應")
        return self._payload


class FakeSession:
    """依序回覆預先安排回應的假 session。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture
def no_sleep(monkeypatch):
    """關閉節流與退避等待，加速測試。"""
    monkeypatch.setattr("careerstatic.crawler.client.time.sleep", lambda _s: None)


def _make_client(responses):
    client = Client104(min_delay=0, max_delay=0)
    client._session = FakeSession(responses)
    return client


def _page_payload(page, last_page, count=2):
    items = [{"jobNo": f"{page}-{i}"} for i in range(count)]
    return {
        "data": items,
        "metadata": {"pagination": {"currentPage": page, "lastPage": last_page}},
    }


class TestRequestRetry:
    def test_retries_then_succeeds(self, no_sleep):
        client = _make_client(
            [FakeResponse(403), FakeResponse(403), FakeResponse(200, {"ok": 1})]
        )
        assert client._request("http://x", None, "referer") == {"ok": 1}
        assert len(client._session.calls) == 3

    def test_exhausts_retries(self, no_sleep):
        client = _make_client([FakeResponse(403)] * 4)
        with pytest.raises(CrawlError, match="重試耗盡"):
            client._request("http://x", None, "referer")

    def test_non_retryable_4xx(self, no_sleep):
        client = _make_client([FakeResponse(404)])
        with pytest.raises(CrawlError, match="404"):
            client._request("http://x", None, "referer")

    def test_invalid_json_retries(self, no_sleep):
        client = _make_client([FakeResponse(200, None), FakeResponse(200, {"ok": 2})])
        assert client._request("http://x", None, "referer") == {"ok": 2}


class TestIterSearch:
    def test_stops_at_last_page(self, no_sleep, monkeypatch):
        client = Client104(min_delay=0, max_delay=0)
        pages = {1: _page_payload(1, 3), 2: _page_payload(2, 3), 3: _page_payload(3, 3)}
        monkeypatch.setattr(
            client, "_request", lambda url, params, referer: pages[int(params["page"])]
        )
        results = list(client.iter_search("AI", max_pages=10))
        assert len(results) == 3

    def test_respects_max_pages(self, no_sleep, monkeypatch):
        client = Client104(min_delay=0, max_delay=0)
        monkeypatch.setattr(
            client,
            "_request",
            lambda url, params, referer: _page_payload(int(params["page"]), 150),
        )
        results = list(client.iter_search("AI", max_pages=2))
        assert len(results) == 2

    def test_stops_on_empty_page(self, no_sleep, monkeypatch):
        client = Client104(min_delay=0, max_delay=0)
        payloads = {1: _page_payload(1, 5), 2: {"data": [], "metadata": {}}}
        monkeypatch.setattr(
            client,
            "_request",
            lambda url, params, referer: payloads[int(params["page"])],
        )
        results = list(client.iter_search("AI", max_pages=10))
        assert len(results) == 1
