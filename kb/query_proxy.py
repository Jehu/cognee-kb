"""Geteilter Query-Proxy an den Instance Service (Gateway + MCP nutzen das).

Kapselt httpx + Normalisierung, sodass beide Aufrufer dieselbe Defensivität
bekommen (Transportfehler, non-200, non-JSON, fehlender 'answer'-Key). Das
verhindert die frühere Divergenz: das Gateway crashete bei 200-non-JSON bzw.
fehlendem 'answer'-Key (HTTPException 500), der MCP-Server nicht.
"""

import httpx

from kb.config import get_instance

QUERY_TIMEOUT = 120.0  # GRAPH_COMPLETION kann dauern


class QueryProxyError(RuntimeError):
    """Konnte keine Antwort vom Instance Service erhalten."""


async def proxy_query(
    instance_name: str,
    question: str,
    datasets: list[str],
    request_id: str | None = None,
) -> dict[str, object]:
    """Liefert die geparste JSON-Antwort des Instance Service (mit 'answer').

    Hebt bei Transport-/Status-/Format-/Inhalts-Fehlern QueryProxyError mit
    lesbarem Text. Optional wird eine X-Request-ID mitgegeben (Korrelation
    Gateway → Instance /query → Logs).
    """
    inst = get_instance(instance_name)
    headers = {"X-Request-ID": request_id} if request_id else {}
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            r = await client.post(
                f"http://127.0.0.1:{inst.port}/query",
                json={"question": question, "datasets": datasets},
                headers=headers,
            )
    except httpx.TransportError:
        raise QueryProxyError(
            f"Instance Service '{inst.name}' (Port {inst.port}) nicht erreichbar — "
            f"läuft `kb serve-instance {inst.name}`?"
        ) from None
    if r.status_code != 200:
        raise QueryProxyError(f"Instance Service '{inst.name}' antwortete mit {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise QueryProxyError(
            f"Instance Service lieferte keine JSON-Antwort: {r.text[:200]}"
        ) from None
    if not isinstance(data, dict) or not data.get("answer"):
        raise QueryProxyError(f"Instance Service lieferte keine Antwort: {data}")
    return data
