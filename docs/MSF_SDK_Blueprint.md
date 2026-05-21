# MSF SDK Wiring Harness Blueprint

**Purpose:** Application-agnostic template for generating governed SDK wiring harnesses.  
**Source Pattern:** Reference SDK Implementation  
**Target:** Any MFS-extracted service container that needs agent consumption.

---

## 1. Overview

When MSF extracts a service into a container, external agents need a clean interface to consume it. Raw HTTP is fragile — agents must manually manage sessions, retries, error parsing, and budget checks. The **SDK Wiring Harness** pattern solves this by generating a thin typed client that wraps the service's API.

### The Pattern

```
┌─────────────────────┐                     ┌──────────────────────┐
│   Consuming Agent   │   Generated SDK     │  Service Container   │
│   (LLM / WebUI /    │ ═══════════════════►│  (Governed API)      │
│    another service)  │   typed + governed   │                      │
└─────────────────────┘                     └──────────────────────┘
```

### What the SDK Provides

| Capability | Agent Burden Without SDK | With SDK |
|---|---|---|
| Session management | Agent creates, refreshes, handles expiry | Automatic |
| Error handling | Agent parses JSON, maps codes | Typed exceptions with `agent_should` |
| Retries | Agent implements backoff | Built-in exponential backoff |
| Budget tracking | Agent polls budget endpoint | Pre-check on every call |
| Action discovery | Agent reads `/actions` | `client.available_actions()` |
| Health check | Agent sends HTTP ping | `client.health()` → bool |

---

## 2. Required Inputs (What MSF Needs to Generate an SDK)

To generate an SDK for application `{APP}`, MSF needs:

### 2.1 Service Manifest

```yaml
# msf_service_manifest.yaml
app_name: "MyApp"                          # Human-readable name
app_slug: "myapp"                          # Used in: module name, env prefix, URI scheme
api_base_path: "/api/v1"                   # API URL prefix
default_port: 5000                         # Default service port
health_endpoint: "/api/v1/actions"         # Non-authenticated liveness probe

# Session mechanics (set has_sessions: false if the API is stateless)
has_sessions: true
session_create_endpoint: "/api/v1/session"
session_create_method: "POST"
session_create_body:
  agent_class: "{agent_class}"
  mode: "unattended"
  entry_point: "sdk"
  ttl_minutes: "{session_ttl_minutes}"
session_id_field: "session_id"             # Where session_id appears in response

# Session refresh (optional)
session_refresh_endpoint: "/api/v1/session/refresh"
session_expiry_codes: ["SESSION_EXPIRED", "SESSION_NOT_FOUND"]
```

### 2.2 Action Registry

```yaml
# msf_action_registry.yaml
actions:
  - name: "dispatch"
    endpoint: "/api/v1/dispatch"
    method: "POST"
    description: "End-to-end: clone + scan + return findings"
    requires_session: true
    parameters:
      - name: "github_url"
        type: "str"
        required: true
      - name: "tools"
        type: "List[str]"
        required: false
    response_key: null  # Return full response

  - name: "scan_repo"
    endpoint: "/api/v1/intent"
    method: "POST"
    description: "Run security scan on a local directory"
    requires_session: true
    intent_action: "run_scan"  # Wraps submit_intent()
    parameters:
      - name: "directory"
        type: "str"
        required: true
      - name: "repo_name"
        type: "str"
        required: true
      - name: "tools"
        type: "List[str]"
        required: false

  - name: "search_findings"
    endpoint: "/api/v1/intent"
    method: "POST"
    description: "Semantic search across indexed findings"
    requires_session: true
    intent_action: "get_results"
    parameters:
      - name: "query"
        type: "str"
        required: true
      - name: "repo_name"
        type: "str"
        required: false
      - name: "limit"
        type: "int"
        required: false
        default: 20
```

### 2.3 Error Code Map

```yaml
# msf_error_codes.yaml
errors:
  - code: "SESSION_EXPIRED"
    exception: "SessionExpiredError"
    agent_should: "Create a new session via client.ensure_session(force=True)"
  
  - code: "BUDGET_EXCEEDED"
    exception: "BudgetExceededError"
    agent_should: "Check budget_status() and choose a cheaper action"
  
  - code: "TRUST_INSUFFICIENT"
    exception: "TrustInsufficientError"
    agent_should: "Request elevated trust or choose a lower-trust action"
  
  - code: "ACTION_NOT_FOUND"
    exception: "ActionNotFoundError"
    agent_should: "Call available_actions() to see what actions exist"
  
  - code: "GUARD_FAILED"
    exception: "GuardFailedError"
    agent_should: "Check guard failure reason in details and resolve precondition"
```

---

## 3. Generated SDK Structure

For application `{APP}` with slug `{app}`, MSF generates:

```
{app}_sdk/
├── __init__.py      # Package exports
├── config.py        # {App}Config dataclass
├── errors.py        # Typed exceptions + raise_for_error()
├── client.py        # {App}Client — session mgmt + action methods
tests/
├── test_{app}_sdk.py  # Unit tests (mocked HTTP)
```

---

## 4. Template: `config.py`

```python
"""{{APP}} SDK configuration — loaded from environment variables."""
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class {{App}}Config:
    """Configuration for the {{APP}} SDK client.
    
    Environment variables:
        {{APP_UPPER}}_BASE_URL       — Service URL
        {{APP_UPPER}}_AGENT_CLASS    — Agent class name
        {{APP_UPPER}}_TIMEOUT_S      — HTTP request timeout
        {{APP_UPPER}}_RETRIES        — Max retries for transient failures
        {{APP_UPPER}}_RETRY_DELAY_S  — Base delay between retries
    """
    base_url: str = ""
    agent_class: str = "default_agent"
    timeout_s: float = 30.0
    retries: int = 2
    retry_delay_s: float = 1.0
    session_ttl_minutes: int = 60

    def __post_init__(self):
        if not self.base_url:
            self.base_url = "http://localhost:{{DEFAULT_PORT}}"

    @classmethod
    def from_env(cls) -> "{{App}}Config":
        return cls(
            base_url=os.environ.get("{{APP_UPPER}}_BASE_URL", "http://localhost:{{DEFAULT_PORT}}"),
            agent_class=os.environ.get("{{APP_UPPER}}_AGENT_CLASS", "default_agent"),
            timeout_s=float(os.environ.get("{{APP_UPPER}}_TIMEOUT_S", "30")),
            retries=int(os.environ.get("{{APP_UPPER}}_RETRIES", "2")),
            retry_delay_s=float(os.environ.get("{{APP_UPPER}}_RETRY_DELAY_S", "1.0")),
            session_ttl_minutes=int(os.environ.get("{{APP_UPPER}}_SESSION_TTL", "60")),
        )
```

**Template variables:**
- `{{App}}` — PascalCase app name (e.g., `AcmeScanner`)
- `{{APP_UPPER}}` — UPPER_SNAKE env prefix (e.g., `ACMESCANNER`)
- `{{DEFAULT_PORT}}` — From service manifest

---

## 5. Template: `errors.py`

```python
"""{{APP}} SDK exceptions — typed errors with agent_should guidance."""
from __future__ import annotations
from typing import Any, Dict, Optional

class {{App}}Error(Exception):
    """Base exception for all {{APP}} SDK errors."""
    def __init__(self, code: str, message: str, agent_should: str = "", 
                 details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.agent_should = agent_should
        self.details = details or {}
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, 
                "agent_should": self.agent_should, "details": self.details}

# ── Generated from error_codes.yaml ──────────────────────────────
{% for error in errors %}
class {{error.exception}}({{App}}Error):
    def __init__(self, message: str = "{{error.code}}", **kw):
        super().__init__(
            code="{{error.code}}",
            message=message,
            agent_should="{{error.agent_should}}",
            **kw,
        )
{% endfor %}

class ServiceUnavailableError({{App}}Error):
    """Service host is unreachable."""
    def __init__(self, message: str = "{{APP}} service unavailable", **kw):
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=message,
            agent_should="Verify {{APP}} container is running and the base URL is correct",
            **kw,
        )

# ── Error code → exception class mapping ─────────────────────────
_CODE_MAP: Dict[str, type] = {
    {% for error in errors %}
    "{{error.code}}": {{error.exception}},
    {% endfor %}
}

def raise_for_error(response_json: Dict[str, Any]) -> None:
    if response_json.get("ok"):
        return
    error = response_json.get("error", {})
    code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
    message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
    exc_cls = _CODE_MAP.get(code, {{App}}Error)
    if exc_cls is {{App}}Error:
        raise exc_cls(code=code, message=message, details={"raw_error": error})
    raise exc_cls(message=message, details={"raw_error": error})
```

---

## 6. Template: `client.py` — Core Request Engine

The request engine is **100% application-agnostic**. Here is the invariant core:

```python
class {{App}}Client:
    def __init__(self, base_url=None, config=None, agent_class=None, auto_session=True):
        self._cfg = config or {{App}}Config.from_env()
        if base_url:
            self._cfg.base_url = base_url.rstrip("/")
        self._base = self._cfg.base_url.rstrip("/")
        self._auto_session = auto_session
        self._session_id = None
        self._http = requests.Session()
        self._http.headers.update({"Content-Type": "application/json"})

    # ═══════════════════════════════════════════════════════════════
    # INVARIANT CORE — same for every application
    # ═══════════════════════════════════════════════════════════════

    def _url(self, path: str) -> str:
        return f"{self._base}{{API_BASE_PATH}}{path}"

    def _request(self, method, path, json_body=None, params=None, retries=None):
        """HTTP request with retry, session-expiry recovery, error classification."""
        max_retries = retries if retries is not None else self._cfg.retries
        url = self._url(path)
        
        for attempt in range(max_retries + 1):
            try:
                resp = self._http.request(method, url, json=json_body, 
                                          params=params, timeout=self._cfg.timeout_s)
                body = resp.json()
                
                # Session expiry auto-recovery
                if (not body.get("ok") and self._auto_session
                    and body.get("error", {}).get("code") in {{SESSION_EXPIRY_CODES}}
                    and attempt < max_retries):
                    self._create_session()
                    if json_body and "session_id" in json_body:
                        json_body["session_id"] = self._session_id
                    continue
                
                raise_for_error(body)
                return body
                
            except requests.ConnectionError:
                if attempt < max_retries:
                    time.sleep(self._cfg.retry_delay_s * (2 ** attempt))
                    continue
                raise ServiceUnavailableError(message=f"Cannot connect to {self._base}")
            except requests.Timeout:
                if attempt < max_retries:
                    time.sleep(self._cfg.retry_delay_s * (2 ** attempt))
                    continue
                raise ServiceUnavailableError(message=f"Request timed out")

    # ═══════════════════════════════════════════════════════════════
    # SESSION LIFECYCLE — conditional on has_sessions
    # ═══════════════════════════════════════════════════════════════
    
    {% if has_sessions %}
    def _create_session(self) -> str:
        body = self._request("POST", "{{SESSION_CREATE_PATH}}", 
                             json_body={{SESSION_CREATE_BODY}}, retries=0)
        self._session_id = body["{{SESSION_ID_FIELD}}"]
        return self._session_id

    def ensure_session(self, force=False) -> str:
        if force or self._session_id is None:
            return self._create_session()
        return self._session_id
    {% endif %}

    # ═══════════════════════════════════════════════════════════════
    # ACTION METHODS — generated from action_registry.yaml
    # ═══════════════════════════════════════════════════════════════

    {% for action in actions %}
    def {{action.name}}(self, {{action.parameters_signature}}) -> Dict[str, Any]:
        """{{action.description}}"""
        {% if action.requires_session %}
        sid = self.ensure_session()
        {% endif %}
        {% if action.intent_action %}
        return self.submit_intent("{{action.intent_action}}", parameters={
            {{action.parameters_dict}}
        })
        {% else %}
        return self._request("{{action.method}}", "{{action.endpoint}}", json_body={
            {{action.body_dict}}
        })
        {% endif %}
    {% endfor %}

    # ═══════════════════════════════════════════════════════════════
    # HEALTH CHECK — always present
    # ═══════════════════════════════════════════════════════════════

    def health(self) -> bool:
        try:
            resp = self._http.get(f"{self._base}{{HEALTH_ENDPOINT}}", timeout=5)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False
```

**Template variables:**
- `{{API_BASE_PATH}}` — from manifest (e.g., `/api/v1`)
- `{{SESSION_EXPIRY_CODES}}` — from manifest (e.g., `("SESSION_EXPIRED", "SESSION_NOT_FOUND")`)
- `{{SESSION_CREATE_PATH}}` — from manifest (e.g., `/session`)
- `{{HEALTH_ENDPOINT}}` — from manifest (e.g., `/api/v1/actions`)
- `{% for action in actions %}` — iterates action registry

---

## 7. Network Exposure Decision Tree

MSF should present this decision to the operator during SDK generation:

```
Q: Where does the consuming agent run relative to the service container?

├── Same machine (localhost)
│   └── Bind to 127.0.0.1:{port}
│       Config: {APP}_BASE_URL=http://localhost:{port}
│       Security: No network exposure needed
│
├── Same Docker network (container-to-container)
│   └── Use Docker service name
│       Config: {APP}_BASE_URL=http://{service-name}:{internal_port}
│       Security: No host port binding needed
│
├── Same LAN (different machine)
│   └── Bind to 0.0.0.0:{port}
│       Config: {APP}_BASE_URL=http://{host_ip}:{port}
│       Security: Consider TLS + API key
│
└── Remote / Cloud
    └── Reverse proxy (nginx/traefik) + TLS
        Config: {APP}_BASE_URL=https://{domain}:{port}
        Security: TLS required + API key + rate limiting
```

### Docker Compose Port Template

```yaml
services:
  {{app}}-host:
    ports:
      # localhost only (default — most secure)
      - "127.0.0.1:{{port}}:{{internal_port}}"
      # OR LAN-accessible (less secure)
      # - "0.0.0.0:{{port}}:{{internal_port}}"
```

---

## 8. SDK Deployment Options

MSF should present these options during generation:

### Option A: In-Repo (Recommended for Self-Contained Apps)

SDK lives inside the application repository:

```
my_app/
├── my_app_sdk/
│   ├── __init__.py
│   ├── client.py
│   ├── config.py
│   └── errors.py
├── services/
├── docker-compose.yml
└── ...
```

**Pros:** Portable, no external deps, versioned with the app.  
**Cons:** Consumer must copy or mount the SDK directory.

### Option B: Pip Package (Recommended for Multi-Consumer)

SDK is a standalone pip-installable package:

```bash
pip install my-app-sdk
```

**Pros:** Clean dependency, versioned independently.  
**Cons:** Requires PyPI or private index, separate CI/CD.

### Option C: FastAPI Auto-Generated Client

If the service uses FastAPI with OpenAPI schema:

```bash
# Generate from OpenAPI spec
openapi-python-client generate --url http://localhost:5000/openapi.json
```

**Pros:** Zero manual SDK code.  
**Cons:** No session lifecycle, no retry logic, no agent_should — raw HTTP wrapper only.

**MSF Recommendation:** Option A for greenfield, Option B if 3+ consumers exist.

---

## 9. Test Generation Template

For every generated SDK, MSF should produce tests in this 6-tier structure:

```python
class TestConfig:
    """Tier 0: Config defaults and env-var loading."""
    def test_defaults(self): ...
    def test_from_env(self, monkeypatch): ...

class TestErrorClassification:
    """Tier 1: Every error code maps to correct exception."""
    {% for error in errors %}
    def test_raise_{{error.code | lower}}(self): ...
    {% endfor %}
    def test_all_errors_have_agent_should(self): ...

class TestSessionLifecycle:
    """Tier 2: Create, reuse, force-create, auto-retry-on-expiry."""
    def test_ensure_session_creates_new(self): ...
    def test_ensure_session_reuses_existing(self): ...
    def test_auto_retry_on_expired(self): ...

class TestActionMethods:
    """Tier 3: One test per action method."""
    {% for action in actions %}
    def test_{{action.name}}(self): ...
    {% endfor %}

class TestGracefulDegradation:
    """Tier 4: Connection errors, timeouts, health check."""
    def test_connection_error_raises_service_unavailable(self): ...
    def test_timeout_raises_service_unavailable(self): ...
    def test_health_returns_false_on_failure(self): ...
    def test_health_returns_true_on_success(self): ...

class TestProtocol:
    """Tier 5: Context manager, repr, explicit config."""
    def test_context_manager(self): ...
    def test_repr(self): ...
```

---

## 10. Generation Workflow for MSF AI Dev

```
1. Read service_manifest.yaml → extract app_name, ports, session config
2. Read action_registry.yaml → extract action list + parameter schemas
3. Read error_codes.yaml → extract error map
4. Generate config.py from config template
5. Generate errors.py from error template + error codes
6. Generate client.py from client template + actions
7. Generate __init__.py with exports
8. Generate test_sdk.py from test template
9. Run tests → verify 100% pass rate
10. Validate: client.health() → True against live container
```

### MSF CLI (Proposed)

```bash
# Generate SDK from manifests
msf sdk generate \
  --manifest service_manifest.yaml \
  --actions action_registry.yaml \
  --errors error_codes.yaml \
  --output my_app_sdk/

# Validate against live service
msf sdk validate --url http://localhost:5000

# Run generated tests
msf sdk test
```

---

The complete working implementation follows this blueprint pattern. See the technical report (`MSF_SDK_Technical_Report.md`) for a reference implementation with detailed rationale.

| File | Lines | Purpose |
|---|---|---|
| `acmescanner_sdk/__init__.py` | 45 | Package exports |
| `acmescanner_sdk/config.py` | 55 | Config dataclass |
| `acmescanner_sdk/errors.py` | 220 | Error hierarchy |
| `acmescanner_sdk/client.py` | 380 | Client harness |
| `tests/test_acmescanner_sdk.py` | 330 | Test suite |
| **Total** | **1,030** | |

The technical report (`MSF_SDK_Technical_Report.md`) documents every design decision with rationale for MSF generalization.
