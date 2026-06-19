import asyncio

import httpx
import pytest

from kb import query_proxy
from kb.query_proxy import QueryProxyError, proxy_query


def _client(response=None, exc=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, json=None):
            if exc is not None:
                raise exc
            return response

    return FakeClient


class _Resp:
    def __init__(self, status_code=200, payload=None, text=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else str(payload)
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


def test_success_returns_dict(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _client(response=_Resp(payload={"answer": "42", "sources": []})))
    data = asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))
    assert data == {"answer": "42", "sources": []}


def test_transport_error_raises(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _client(exc=httpx.ConnectError("zu")))
    with pytest.raises(QueryProxyError, match="nicht erreichbar"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_non_200_raises(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _client(response=_Resp(status_code=500)))
    with pytest.raises(QueryProxyError, match="500"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_non_json_200_raises(monkeypatch):
    # 200 mit HTML-Body statt JSON — früher crashete das Gateway hier (500).
    r = _Resp(status_code=200, raise_json=True, text="<html>upstream</html>")
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _client(response=r))
    with pytest.raises(QueryProxyError, match="keine JSON-Antwort"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_missing_answer_raises(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient",
                        _client(response=_Resp(payload={"error": "boom"})))
    with pytest.raises(QueryProxyError, match="keine Antwort"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))
