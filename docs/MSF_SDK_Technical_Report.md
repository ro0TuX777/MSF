# Agent SDK Wiring Harness — Technical Report

**Application:** Reference Implementation (AcmeScanner)  
**Date:** 2026-04-02  
**Scope:** Agent-facing SDK for governed API consumption  
**Status:** Complete — 275 tests, 0 failures

---

## 1. Problem Statement

The reference application is a containerized security scanning platform. It exposes a **governed REST API** (CONCORD-style v0.5) that enforces session management, trust tiers, budget limits, guard pre-conditions, and full audit trails on every action.

A local agent — orchestrated by a PM (local LLM) with a human via WebUI — needed to consume the application's capabilities programmatically. The raw API has 12 endpoints with interdependent session/budget/trust mechanics that an agent would need to manually manage on every call.

**The core question:** What wiring harness should an agent use to leverage a governed service container?

---

## 2. Solution Architecture

We evaluated three harness patterns and selected **Option B: Lightweight SDK**.

### Options Evaluated

| Option | Pattern | Complexity | Agent Burden |
|---|---|---|---|
| A | Direct HTTP (`requests`) | None (0 new code) | High — agent manages sessions, retries, errors |
| **B** | **Python SDK wrapper** | **Low (~300 lines)** | **None — SDK handles everything** |
| C | A2A Event Bridge | High (event bus needed) | None — fully decoupled |

### Why SDK Won

1. **Zero agent burden** — session lifecycle, retries, error classification are automatic
2. **PM-friendly** — `client.dispatch(url)` is a single function call the LLM can reason about
3. **Portable** — ships inside the application container, no external dependencies
4. **Testable** — all logic is unit-testable with mocked HTTP (no live server)
5. **Consistent** — follows the same SDK pattern across all services

---

## 3. What Was Built

### File Inventory

```
acmescanner_sdk/
├── __init__.py      # Package exports (45 lines)
├── config.py        # AcmeScannerConfig dataclass + env-var loading (55 lines)
├── errors.py        # 11 typed exceptions + raise_for_error() (220 lines)
├── client.py        # AcmeScannerClient — the main harness (380 lines)
tests/
├── test_acmescanner_sdk.py  # 35 unit tests, 6 tiers (330 lines)
```

**Total new code: ~1,030 lines** (including tests)

---

## 4. Key Design Decisions

### 4.1 Config Layer (`config.py`)

**Pattern:** Dataclass with `from_env()` classmethod.

```python
@dataclass
class AcmeScannerConfig:
    base_url: str = ""
    agent_class: str = "default_agent"
    timeout_s: float = 30.0
    retries: int = 2
    
    @classmethod
    def from_env(cls) -> AcmeScannerConfig:
        return cls(
            base_url=os.environ.get("ACMESCANNER_BASE_URL", "http://localhost:5000"),
            ...
        )
```

**Why this matters for MSF:**
- Every application will have its own URL, port, agent class, timeouts
- The env-var prefix (`ACMESCANNER_`) is the only application-specific part
- Everything else is structural and can be templated

### 4.2 Error Classification Layer (`errors.py`)

**Pattern:** Code-mapped exception hierarchy with `agent_should` guidance.

```python
class AcmeScannerError(Exception):
    def __init__(self, code, message, agent_should="", details=None):
        ...

class SessionExpiredError(AcmeScannerError):
    def __init__(self, message="Session has expired", **kw):
        super().__init__(
            code="SESSION_EXPIRED",
            agent_should="Create a new session via client.ensure_session(force=True)",
            ...
        )

# Dispatch table: error code string → exception class
_CODE_MAP = {
    "SESSION_EXPIRED": SessionExpiredError,
    "BUDGET_EXCEEDED": BudgetExceededError,
    ...
}

def raise_for_error(response_json):
    """Auto-classify API errors into typed exceptions."""
```

**Why this matters for MSF:**
- The error codes come from the governance layer
- The `agent_should` field is what makes this useful to an LLM orchestrator
- The `_CODE_MAP` dispatch table is a generic pattern — MSF can define its own error codes
- If an application doesn't have governance, it still has HTTP status codes and error bodies

### 4.3 Session Lifecycle (`client.py`)

**Pattern:** Automatic session management with transparent retry.

The SDK handles three session states:

```
┌─────────────┐    ensure_session()    ┌─────────────┐
│ No Session  │ ──────────────────────►│   Active     │
└─────────────┘                        └──────┬──────┘
                                              │ TTL expires
                                              ▼
                                       ┌─────────────┐
                                       │   Expired    │
                                       └──────┬──────┘
                                              │ auto-retry detects
                                              ▼
                                       ┌─────────────┐
                                       │  Re-create   │ → loops back to Active
                                       └─────────────┘
```

**Key implementation detail:**

```python
def _request(self, method, path, json_body=None, ...):
    for attempt in range(max_retries + 1):
        resp = self._http.request(method, url, json=json_body, ...)
        body = resp.json()
        
        # Auto-handle session expiry
        if body.get("error", {}).get("code") in ("SESSION_EXPIRED", "SESSION_NOT_FOUND"):
            self._create_session()
            json_body["session_id"] = self._session_id  # patch and retry
            continue
        
        raise_for_error(body)
        return body
```

**Why this matters for MSF:**
- Any governed API with session mechanics needs this pattern
- The retry-on-expiry logic is generic — only the session creation endpoint changes
- Applications without sessions can skip this entirely (the SDK should degrade)

### 4.4 Action Methods (`client.py`)

**Pattern:** Thin typed wrappers over `submit_intent()`.

```python
def dispatch(self, target_url, tools=None):
    """End-to-end: clone → scan → return findings."""
    sid = self.ensure_session()
    return self._request("POST", "/dispatch", json_body={
        "target_url": target_url,
        "session_id": sid,
    })

def scan_repo(self, directory, repo_name, tools=None):
    """Scan a local directory."""
    return self.submit_intent("run_scan", parameters={
        "directory": directory,
        "repo_name": repo_name,
    })
```

**Why this matters for MSF:**
- Each application will have its own set of actions
- The method names are semantic (agent reads `scan_repo`, not `POST /api/v1/intent`)
- The underlying mechanism (`submit_intent`) is always the same
- **MSF's job: auto-generate these methods from the action registry**

### 4.5 Health Check

**Pattern:** Non-session, non-governed liveness probe.

```python
def health(self) -> bool:
    try:
        resp = self._http.get(f"{self._base}/api/v1/actions", timeout=5)
        return resp.status_code == 200
    except (ConnectionError, Timeout):
        return False
```

**Why this matters for MSF:**
- Every SDK needs a pre-flight check
- The health endpoint path varies per application
- Must NOT require a session (it's used before session creation)

---

## 5. Test Architecture

### Tier Structure

| Tier | Tests | What It Validates |
|---|---|---|
| Config | 3 | Defaults, env-var loading, explicit overrides |
| Error Classification | 10 | Every error code → correct exception, agent_should present |
| Session Lifecycle | 5 | Create, reuse, force-create, auto-retry-on-expiry, refresh |
| Action Methods | 8 | dispatch, scan, search, export, network, actions, budget, receipts |
| Review Workflow | 3 | Create, poll, submit decision |
| Graceful Degradation | 4 | ConnectionError, Timeout, health true/false |
| Protocol | 3 | Context manager, repr, explicit agent_class |

**All tests use mocked HTTP** — `unittest.mock.patch` on `requests.Session.request`. No live server required.

---

## 6. Integration Points

### How the Local Agent Uses It

```python
from acmescanner_sdk import AcmeScannerClient

# PM (LLM) creates client once
client = AcmeScannerClient("http://localhost:5000")

# PM decides to scan a repo
result = client.dispatch("https://github.com/target/repo")
findings = result["review_bundle"]["findings_count"]

# PM wants more detail
details = client.search_findings("sql injection", repo_name="repo")

# Human reviews via WebUI
bundle_id = client.create_review("run_scan", {"findings": details})
# ... human approves in UI ...
status = client.check_review(bundle_id)
```

### Port Mapping (Example)

| Service | Internal | External | Purpose |
|---|---|---|---|
| Application Host | 5000 | 5000 | Governed API + WebUI |
| Memory Service | 8700 | 8710 | Memory/RAG API |
| Database | 5432 | 5432 | Data storage |

---

## 7. Metrics

| Metric | Value |
|---|---|
| SDK code (excluding tests) | ~700 lines |
| Test code | ~330 lines |
| New files | 5 |
| Test pass rate | 35/35 (100%) |
| Full suite (all suites) | 275/275 (100%) |
| Time to build | ~30 minutes |
| External dependencies | 1 (`requests` — already in project) |

---

## 8. What MSF Should Extract

The following components are **application-agnostic** and should become MSF templates:

1. **Config dataclass** — parameterized by env-var prefix
2. **Error hierarchy** — parameterized by error code map
3. **Session lifecycle** — parameterized by session endpoint
4. **Request wrapper** — retry logic, error classification
5. **Action method generator** — from action registry to typed methods
6. **Health check** — parameterized by liveness endpoint
7. **Test scaffolding** — 6-tier structure with mocked HTTP

See `MSF_SDK_Blueprint.md` for the templatized version.
