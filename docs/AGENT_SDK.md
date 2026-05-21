# Agent SDK Guide

## Purpose

The Agent SDK generates a typed Python client that external agents (LLMs, orchestrators, other applications) use to consume an MFS-extracted service. It is the **inbound** counterpart to the Boundary SDK's **outbound** adapter.

| | Boundary SDK | Agent SDK |
|---|---|---|
| **Direction** | App → its service containers (outbound) | External agent → the app (inbound) |
| **Consumer** | The application itself | External agents, LLMs, other orchestrators |
| **Session mgmt** | None — boundaries are internal | Full session lifecycle (governance-dependent) |
| **Error model** | Returns dicts with `status` flag | Raises typed exceptions with `agent_should` |
| **Generator** | `scaffold_boundary.py` | `scaffold_agent_sdk.py` |

## Files

- `templates/agent_sdk/` — Jinja2 templates for SDK generation
- `tools/scaffold_agent_sdk.py` — Generator script
- `examples/agent_sdk_manifest_example.yaml` — Full manifest example

## Quick Start

### Minimal (Stateless API)

```bash
python tools/scaffold_agent_sdk.py \
  --app-name "MyAPI" \
  --app-slug "myapi" \
  --port 8080 \
  --governance stateless \
  --output ./myapi_sdk/
```

Generates a working SDK with:
- Config with env-var loading
- Health check
- Error classification from HTTP status codes
- Test scaffolding

### Session-Based API

```bash
python tools/scaffold_agent_sdk.py \
  --app-name "MyService" \
  --app-slug "myservice" \
  --port 5000 \
  --governance session_only \
  --output ./myservice_sdk/
```

Adds:
- Session lifecycle (create, refresh, auto-retry-on-expiry)
- Session-aware action methods
- Session tests

### Full Governance (CONCORD or equivalent)

```bash
python tools/scaffold_agent_sdk.py \
  --app-name "AcmeScanner" \
  --app-slug "acmescanner" \
  --port 5000 \
  --governance full \
  --output ./acmescanner_sdk/
```

Adds:
- Trust tier management
- Budget checking and circuit breaker awareness
- Guard failure handling
- Governance introspection (available_actions, budget_status, receipts)

### From Manifest (Complex Apps)

```bash
python tools/scaffold_agent_sdk.py \
  --from-manifest agent_sdk_manifest.yaml \
  --output ./myapp_sdk/
```

See `examples/agent_sdk_manifest_example.yaml` for the full manifest schema.

## Three Governance Modes

### `stateless`
- No sessions, pure REST
- Error classification from HTTP status codes
- Suitable for: microservices, simple APIs

### `session_only`
- Sessions with auto-create/refresh/retry-on-expiry
- No budget, trust, or guard enforcement
- Suitable for: APIs with API key + session token

### `full`
- Full CONCORD-style governance
- Sessions, trust tiers, budgets, guards, audit receipts
- `agent_should` guidance on every error
- Suitable for: governed, multi-tenant services

## Generated SDK Structure

For application `MyApp` with slug `myapp`:

```
myapp_sdk/
├── __init__.py      # Package exports
├── config.py        # MyAppConfig dataclass + from_env()
├── errors.py        # Typed exceptions + raise_for_error()
├── client.py        # MyAppClient — session + action methods
tests/
├── test_myapp_sdk.py  # Mocked HTTP test suite (6 tiers)
```

## Environment Variables

All env vars use the `{APP_UPPER}_` prefix:

| Variable | Description | Default |
|---|---|---|
| `{APP}_BASE_URL` | Service URL | `http://localhost:{port}` |
| `{APP}_AGENT_CLASS` | Agent class name | `default_agent` |
| `{APP}_TIMEOUT_S` | HTTP timeout | `30` |
| `{APP}_RETRIES` | Max retries | `2` |
| `{APP}_RETRY_DELAY_S` | Base retry delay | `1.0` |
| `{APP}_SESSION_TTL` | Session TTL minutes (non-stateless) | `60` |
| `{APP}_TRUST_TIER` | Trust tier (full mode only) | `1` |

## Network Exposure Decision Tree

When deploying the SDK consumer relative to the service:

```
Q: Where does the consuming agent run?

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

## SDK Deployment Options

### In-Repo (Recommended for Self-Contained Apps)

SDK lives inside the application repository. Portable, versioned with the app.

### Pip Package (Recommended for Multi-Consumer)

SDK is a standalone `pip install`-able package. Best when 3+ consumers exist.

## Test Architecture

Generated tests follow a 6-tier structure:

| Tier | Tests | What It Validates |
|---|---|---|
| Config | 3 | Defaults, env-var loading, explicit overrides |
| Error Classification | 5-10 | Every error code → correct exception, agent_should present |
| Session Lifecycle | 5 | Create, reuse, force-create, auto-retry-on-expiry, refresh |
| Action Methods | 1 per action | Correct endpoint, parameters passed, response handled |
| Graceful Degradation | 4 | ConnectionError, Timeout, health true/false |
| Protocol | 3 | Context manager, repr, explicit agent_class |

All tests use mocked HTTP — `unittest.mock.patch` on `requests.Session.request`. No live server required.

## Reference Implementation

See `docs/MSF_SDK_Technical_Report.md` for a reference implementation with detailed rationale for every design decision.

See `docs/MSF_SDK_Blueprint.md` for the complete template specification.
