# Plan 004: Block SSRF in web-ingest (URL scheme + resolved-IP guard, no redirect-follow)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/fetch_web.py kb/classify.py tests/test_fetch_web.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #4 — https://github.com/Jehu/cognee-kb/issues/4

## Why this matters

A `web` ingest makes the server issue an authenticated HTTP request to an
arbitrary URL. There is no scheme, host, or IP validation anywhere — the only
filter is `URL_RE = ^https?://\S+$` (`classify.py:6`), which permits loopback,
link-local, RFC1918, Tailscale IPs, and the cloud metadata endpoint. On the
`cloud` wall (if hosted on a cloud VM) this reaches `169.254.169.254` (instance
credentials); on the `local` wall it reaches the unauthenticated instance
services on `127.0.0.1:8801/8802` and every LAN/Tailscale host. A malicious or
prompt-injected ingest (an MCP agent following instructions inside ingested
content) can weaponize this. `trafilatura.fetch_url` also follows redirects,
which would defeat a hostname-only check.

This system's whole purpose is a hard privacy wall (local never phones home);
an unrestricted server-side fetch contradicts that guarantee.

## Current state

`kb/fetch_web.py` (full file, 15 lines):

```python
1: import trafilatura
3: from kb.fetch_youtube import FetchedDoc
6: def fetch(url: str) -> FetchedDoc:
7:     html = trafilatura.fetch_url(url)         # arbitrary URL, follows redirects
8:     if html is None:
9:         raise RuntimeError(f"Konnte {url} nicht laden")
10:    text = trafilatura.extract(html, output_format="markdown", with_metadata=False)
...
13:    meta = trafilatura.extract_metadata(html)
14:    title = (meta.title if meta and meta.title else url)
15:    return FetchedDoc(title=title, body=text, url=url)
```

`kb/worker.py:14-18` dispatches `web` jobs straight into `fetch_web.fetch`:
```python
17:    if kind == "web":
18:        return fetch_web.fetch(payload["url"])
```

`kb/classify.py:4-6`:
```python
4: YOUTUBE_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")
6: URL_RE = re.compile(r"^https?://\S+$")
```

Grep for `is_private|is_loopback|is_link_local|is_reserved|allowlist` in `kb/`
returns zero matches. `trafilatura.extract` / `extract_metadata` accept raw
HTML strings, so the network fetch can be replaced by a controlled `httpx`
call without changing the extraction pipeline.

`httpx` is already a dependency (`pyproject.toml`). `fetch_youtube.fetch` only
ever contacts fixed YouTube hosts with a `[\w-]{11}`-validated `video_id`
(`classify.py:4`), so it is out of scope.

## Repo conventions to match

- German docstrings/comments explaining the why (see `fetch_youtube.py:21-24`
  for style). Add a comment stating *why* internal IPs are refused (SSRF /
  privacy wall).
- Raise `RuntimeError` on fetch failure (matches `fetch_web.py:8-12`), so the
  worker's `except Exception` marks the job `failed` cleanly.

## Commands you will need

| Purpose    | Command                                  | Expected on success |
|------------|------------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_fetch_web.py`  | all pass            |
| Full suite | `uv run pytest` (or `make test`)         | all pass            |

## Scope

**In scope**:
- `kb/fetch_safety.py` (create)
- `kb/fetch_web.py` (replace `trafilatura.fetch_url` with a guarded `httpx` fetch)
- `tests/test_fetch_web.py` (SSRF table + redirect-to-internal test)
- `tests/test_fetch_safety.py` (create, unit-test the guard directly)

**Out of scope**:
- `kb/fetch_youtube.py` (fixed hosts, validated id — safe).
- `kb/classify.py` (leave `URL_RE` as the coarse pre-filter; the real guard is
  `fetch_safety`).
- Changing the gateway/MCP ingest contract or the worker dispatch.

## Git workflow

- Branch: `advisor/004-ssrf-guard`
- Commit style: `Guard web-ingest against SSRF (scheme + resolved-IP, no redirects)`

## Steps

### Step 1: Create `kb/fetch_safety.py`

```python
"""SSRF-Schutz für Web-Ingest.

Der Server darf nicht beliebige URLs fetchen — sonst erreicht ein
(prompt-injected) Ingest interne Dienste (127.0.0.1:8801/8802 ohne Token),
Tailscale-Hosts oder den Cloud-Metadata-Endpoint (169.254.169.254).
Gelöst über Schema-Whitelist plus Auflösung ALLER A/AAAA-Records: sobald
eine IP in einer gesperrten Range liegt, wird der Request verweigert.
"""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """URL würde eine interne/gesperrte Adresse erreichen."""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"Schema nicht erlaubt: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL ohne Host")
    # Hostnamen auflösen (nicht der URL vertrauen — DNS kann auf interne
    # Adressen zeigen). Jede aufgelöste IP muss sauber sein.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Host {host} nicht auflösbar: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked(ip):
            raise UnsafeUrlError(f"Host {host} resolve zu gesperrter IP {ip}")
```

**Verify**: `uv run python -c "from kb.fetch_safety import assert_safe_url, UnsafeUrlError"` → imports clean.

### Step 2: Unit-test the guard directly

Create `tests/test_fetch_safety.py` with a parametrized table (use
`pytest.mark.parametrize`). Blocked (expect `UnsafeUrlError`): `http://127.0.0.1/x`,
`http://localhost/x`, `http://169.254.169.254/latest/meta-data/`,
`http://10.0.0.1/x`, `http://192.168.1.1/x`, `http://[::1]/x`, `ftp://example.com/x`,
`file:///etc/passwd`. Allowed (expect no raise): mock `socket.getaddrinfo` to
return a public IP for a hostname like `example.com`. Use `monkeypatch.setattr`
to avoid real DNS in the allowed case and to force private resolutions where
needed.

**Verify**: `uv run pytest tests/test_fetch_safety.py` → all rows pass.

### Step 3: Rewrite `fetch_web.fetch` to use a guarded, no-redirect `httpx` fetch

Replace the body so the network call is controlled:

```python
import httpx
import trafilatura

from kb.fetch_safety import UnsafeUrlError, assert_safe_url
from kb.fetch_youtube import FetchedDoc

_MAX_HOPS = 3


def fetch(url: str) -> FetchedDoc:
    # Kontrollierter Fetch statt trafilatura.fetch_url: wir validieren jede
    # URL (Start + Redirects) gegen fetch_safety und folgen Redirects per
    # Hand, sodass ein Redirect-Niemand auf eine interne IP entkommen kann.
    assert_safe_url(url)
    html = _fetch_following_redirects(url)
    if html is None:
        raise RuntimeError(f"Konnte {url} nicht laden")
    text = trafilatura.extract(html, output_format="markdown", with_metadata=False)
    if not text:
        raise RuntimeError(f"Kein extrahierbarer Text auf {url}")
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else url)
    return FetchedDoc(title=title, body=text, url=url)


def _fetch_following_redirects(url: str, hops: int = 0) -> str | None:
    # follow_redirects=False: jede Hop-URL explizit erneut prüfen.
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        r = client.get(url)
        if r.status_code in (301, 302, 303, 307, 308) and hops < _MAX_HOPS:
            loc = r.headers.get("location")
            if not loc:
                return None
            next_url = str(httpx.URL(url).join(loc))
            assert_safe_url(next_url)
            return _fetch_following_redirects(next_url, hops + 1)
        if r.status_code != 200:
            return None
        return r.text
```

Keep `RuntimeError` as the failure type so the worker's `except Exception`
marks the job `failed` with a clear message. `UnsafeUrlError` is a `ValueError`
subclass and will likewise be caught and surfaced in the job error text.

**Verify**: `uv run pytest tests/test_fetch_web.py` → existing tests pass
(patch the new `httpx.Client.get` / `assert_safe_url` as the existing tests do
for `trafilatura.fetch_url`).

### Step 4: Add an SSRF regression test in `tests/test_fetch_web.py`

Add a test that calls `fetch("http://169.254.169.254/latest/meta-data/")` and
asserts it raises `UnsafeUrlError` (no network). Add a second test that a
redirect chain from a safe URL to `127.0.0.1` is refused: mock
`httpx.Client.get` to return a 302 to `http://127.0.0.1/` after the first
`assert_safe_url` passes, and assert `UnsafeUrlError`.

**Verify**: `uv run pytest tests/test_fetch_web.py -k ssrf` → passes.

### Step 5: Full suite

**Verify**: `uv run pytest` (or `make test`) → all pass.

## Test plan

- `tests/test_fetch_safety.py`: parametrized block/allow table (Step 2).
- `tests/test_fetch_web.py`: (a) SSRF URL raises before any fetch; (b)
  redirect-to-internal is refused; (c) existing happy-path test updated to
  mock `httpx.Client.get` instead of `trafilatura.fetch_url`.
- Pattern: existing `tests/test_fetch_web.py` shows how the suite mocks the
  fetch layer with `monkeypatch`.
- Verification: `uv run pytest` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] `kb/fetch_safety.py` exists with `assert_safe_url` + `UnsafeUrlError`
- [ ] `kb/fetch_web.py` no longer calls `trafilatura.fetch_url`
      (`grep -n "trafilatura.fetch_url" kb/` → no matches)
- [ ] Redirects are followed manually with a per-hop `assert_safe_url` call
- [ ] Tests cover: loopback/private/link-local/metadata blocked, public allowed,
      redirect-to-internal refused
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `httpx` is not available or its API differs at HEAD — STOP (`httpx>=0.28.1`
  is pinned; confirm `follow_redirects=False` is a valid `Client` kwarg).
- `trafilatura.extract` / `extract_metadata` reject the HTML shape `httpx`
  returns — if extraction breaks on real fetched HTML, STOP and report (do not
  silently weaken extraction).
- A legitimate ingest target legitimately needs a private IP (it should not —
  the system ingests public web pages). If a real use case appears, STOP and
  surface it rather than punching a hole.

## Maintenance notes

- This guard is the single chokepoint for web fetches — any new fetcher must
  call `assert_safe_url` (or route through `_fetch_following_redirects`).
- DNS rebinding (TTL tricks) is not fully mitigated by a single resolution; if
  the threat model rises, pin the resolved IP for the actual connect
  (`httpx` transport hook). Note this in the module docstring if added.
- Reviewers: confirm the redirect test actually exercises the second
  `assert_safe_url` call, not just the first.
