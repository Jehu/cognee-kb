import asyncio

import httpx
import pytest

from kb import query_proxy
from kb.query_proxy import QueryProxyError, proxy_query, proxy_search


def _client(response=None, exc=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, json=None, headers=None):
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
    monkeypatch.setattr(
        query_proxy.httpx,
        "AsyncClient",
        _client(response=_Resp(payload={"answer": "42", "sources": []})),
    )
    data = asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))
    assert data == {"answer": "42", "sources": []}


def test_search_accepts_evidence_without_answer(monkeypatch):
    monkeypatch.setattr(
        query_proxy.httpx,
        "AsyncClient",
        _client(response=_Resp(payload={"answer": None, "evidence": [{"rank": 1}]})),
    )

    data = asyncio.run(proxy_search("cloud", "Q?", ["business-mwe"]))

    assert data["evidence"] == [{"rank": 1}]


def test_transport_error_raises(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _client(exc=httpx.ConnectError("zu")))
    with pytest.raises(QueryProxyError, match="nicht erreichbar"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_non_200_raises(monkeypatch):
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _client(response=_Resp(status_code=500)))
    with pytest.raises(QueryProxyError, match="500"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_non_json_200_raises(monkeypatch):
    # 200 mit HTML-Body statt JSON — früher crashete das Gateway hier (500).
    r = _Resp(status_code=200, raise_json=True, text="<html>upstream</html>")
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _client(response=r))
    with pytest.raises(QueryProxyError, match="keine JSON-Antwort"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_missing_answer_raises(monkeypatch):
    monkeypatch.setattr(
        query_proxy.httpx, "AsyncClient", _client(response=_Resp(payload={"error": "boom"}))
    )
    with pytest.raises(QueryProxyError, match="keine Antwort"):
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))


def test_structured_gap_response_may_have_no_answer(monkeypatch):
    payload = {
        "answer": None,
        "evidence": [{"evidence_id": "e1"}],
        "gaps": [{"kind": "evidence_unavailable", "detail": "LLM down"}],
    }
    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _client(response=_Resp(payload=payload)))

    data = asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"]))

    assert data == payload


def test_forwards_request_id_header(monkeypatch):
    # Korrelation Gateway → Instance: X-Request-ID wird als Header mitgegeben.
    sent: dict[str, object] = {}

    class _CapturingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, json=None, headers=None):
            sent["headers"] = headers
            return _Resp(payload={"answer": "x"})

    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", _CapturingClient)
    asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"], request_id="abc-123"))
    assert sent["headers"] == {"X-Request-ID": "abc-123"}


def test_forwards_nonempty_collection_scope(monkeypatch):
    sent = {}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, json=None, headers=None):
            sent["json"] = json
            return _Resp(payload={"answer": "x"})

    monkeypatch.setattr(query_proxy.httpx, "AsyncClient", Client)
    asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"], collection_ids=["c1"]))
    assert sent["json"]["collection_ids"] == ["c1"]


def test_preserves_upstream_validation_error(monkeypatch):
    monkeypatch.setattr(
        query_proxy.httpx,
        "AsyncClient",
        _client(response=_Resp(status_code=422, payload={"detail": "Unbekannte Collection"})),
    )
    with pytest.raises(QueryProxyError) as caught:
        asyncio.run(proxy_query("cloud", "Q?", ["business-mwe"], collection_ids=["bad"]))
    assert caught.value.status_code == 422
    assert str(caught.value) == "Unbekannte Collection"
