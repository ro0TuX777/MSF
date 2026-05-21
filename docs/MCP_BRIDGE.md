# MCP Bridge Guide

## Purpose

The MCP Bridge generates standalone MCP servers from MFS service registry entries, enabling any MFS-extracted microservice to be consumed by AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

This creates two complementary consumption paths:

| Path | Protocol | Consumer |
|---|---|---|
| **Native MCP** | MCP (stdio/SSE/HTTP) | Claude Desktop, Codex, any MCP client |
| **EasyMCP** | MCP via OpenAPI | EasyMCP CLI → agent toolchain |
| **Agent SDK** | HTTP REST | Custom Python agents, orchestrators |

## Files

- `templates/mcp_server/` — Jinja2 templates for MCP server generation
- `tools/scaffold_mcp.py` — Generator script
- `tests/test_mcp_bridge.py` — 5-tier QA test suite

## Quick Start

### Generate MCP server for a single service

```bash
python tools/scaffold_mcp.py --service example-service --output ./mcp_servers/example/
```

### Generate for all registered services

```bash
python tools/scaffold_mcp.py --all --output ./mcp_servers/
```

### Run the MCP server

```bash
# Install dependencies
pip install -r mcp_servers/example/requirements.txt

# Start MFS service
docker compose up -d --build

# Run MCP server (stdio — for Claude Desktop)
python mcp_servers/example/server.py

# Run MCP server (SSE — for web MCP clients)
python mcp_servers/example/server.py --transport sse --port 9610
```

### Connect from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "example": {
      "command": "python",
      "args": ["mcp_servers/example/server.py"]
    }
  }
}
```

### Use with EasyMCP (complementary path)

```bash
easymcp create example \
  --openapi mcp_servers/example/openapi.json \
  --port 9610

easymcp start example
easymcp agent install codex example
```

## Generated Artifacts

For each service, the tool generates:

```
mcp_servers/<feature>/
├── server.py          # Standalone MCP server (FastMCP)
├── openapi.json       # OpenAPI 3.1 spec (for EasyMCP)
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container deployment
└── README.md          # Usage + agent install guide
```

## MCP Tools Generated

Every generated MCP server includes:

| Tool | Source | Description |
|---|---|---|
| `health_check` | `/health` | Service liveness/readiness check |
| `get_capabilities` | Contract endpoint | Contract discovery and status |
| *(auto-detected)* | POST/PUT endpoints | Feature-specific actions |

Endpoint auto-detection scans the service `app.py` for Flask POST/PUT routes beyond health and capabilities, and generates a tool for each.

## MCP Resources Generated

| URI | Description |
|---|---|
| `service://<feature>/contract` | Full MFS contract JSON |
| `service://<feature>/info` | Service metadata |

## Architecture: The Complementary Chain

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Legacy App   │────▶│  MFS Framework  │────▶│ Extracted Service│
│ (monolith)   │     │  (extract +     │     │ (container +    │
│              │     │   containerize) │     │  contract)      │
└──────────────┘     └─────────────────┘     └────────┬────────┘
                                                      │
                              ┌────────────────────────┼────────────────────┐
                              │                        │                    │
                     ┌────────▼────────┐     ┌────────▼────────┐  ┌───────▼────────┐
                     │ scaffold_mcp.py │     │ scaffold_agent   │  │ Boundary SDK   │
                     │ (MCP server +   │     │ _sdk.py          │  │ (host app      │
                     │  OpenAPI spec)  │     │ (typed Python)   │  │  adapter)      │
                     └────────┬────────┘     └────────┬────────┘  └───────┬────────┘
                              │                        │                    │
                    ┌─────────┼──────────┐             │                    │
                    │         │          │             │                    │
           ┌───────▼──┐  ┌───▼─────┐   │    ┌───────▼────────┐  ┌───────▼────────┐
           │ Claude   │  │ EasyMCP │   │    │ Custom Agents  │  │ Host App UI    │
           │ Desktop  │  │ CLI     │   │    │ / Orchestrators│  │ (preserved)    │
           └──────────┘  └─────────┘   │    └────────────────┘  └────────────────┘
                                       │
                              ┌────────▼────────┐
                              │ Any MCP Client  │
                              │ (Codex, etc.)   │
                              └─────────────────┘
```

## QA Test Suite

Run the full test suite:

```bash
python -m pytest tests/test_mcp_bridge.py -v
```

### Test Tiers

| Tier | Tests | What It Validates | Requires Service? |
|---|---|---|---|
| 1: Generation | 10 | File creation, syntax, flags | No |
| 2: OpenAPI | 8 | Spec structure, fields, versions | No |
| 3: MCP Server | 8 | Module structure, tools, resources | No |
| 4: E2E Chain | 4 | Full data flow with mocked HTTP | No (mocked) |
| 5: EasyMCP Compat | 6 | operationId, snake_case, self-contained | No |
| Bonus: Docker | 4 | Dockerfile structure | No |

All tests are self-contained — no running services, no MCP SDK install, no EasyMCP install required.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MFS_<FEATURE>_BASE_URL` | From registry | Target MFS service URL |
| `MFS_<FEATURE>_TOKEN` | *(empty)* | Bearer token for service auth |
| `MFS_<FEATURE>_TIMEOUT_S` | `10` | HTTP timeout |
| `MCP_TRANSPORT` | `stdio` | Transport: stdio, sse, streamable-http |
| `MCP_PORT` | Service port + 1000 | Port for SSE/HTTP transport |

## Docker Deployment

```bash
docker build -t mcp-example mcp_servers/example/
docker run -e MFS_EXAMPLE_BASE_URL=http://host.docker.internal:8610 mcp-example
```

## Relationship to Other Tools

| Tool | Direction | Protocol |
|---|---|---|
| `scaffold_feature.py` | Creates the service | — |
| `scaffold_boundary.py` | App → Service (outbound) | HTTP |
| `scaffold_agent_sdk.py` | Agent → App (inbound, REST) | HTTP |
| **`scaffold_mcp.py`** | **Agent → Service (inbound, MCP)** | **MCP** |
