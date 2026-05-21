#!/usr/bin/env python3
"""Scaffold an MCP server from an MFS service registry entry.

Generates a standalone MCP server + OpenAPI spec that wraps an MFS-extracted
service as MCP tools for AI agent consumption.

Usage (from registry):
  python tools/scaffold_mcp.py --service example-service --output ./mcp_servers/example/

Usage (with custom MCP port):
  python tools/scaffold_mcp.py --service example-service --mcp-port 9100 --output ./mcp_servers/example/

Usage (all registered services):
  python tools/scaffold_mcp.py --all --output ./mcp_servers/

The generated MCP server works with:
- Claude Desktop (stdio transport)
- Any MCP client (SSE or streamable-http transport)
- EasyMCP (via the generated openapi.json)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "registry" / "services.json"
CONTRACTS_DIR = ROOT / "contracts"
TEMPLATES_DIR = ROOT / "templates" / "mcp_server"

# Default MCP port offset from the service port
MCP_PORT_OFFSET = 1000


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Name must contain at least one alphanumeric character.")
    return slug


def _snake(raw: str) -> str:
    return _slugify(raw).replace("-", "_")


def _load_registry() -> Dict[str, Any]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_contract(contract_file: str) -> Dict[str, Any]:
    path = ROOT / contract_file
    if not path.exists():
        print(f"WARNING: Contract file not found: {path}", file=sys.stderr)
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_service(registry: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for svc in registry.get("services", []):
        if svc.get("name") == name:
            return svc
    return None


def _extract_port(url: str) -> int:
    """Extract port from a URL like http://localhost:8610."""
    try:
        return int(url.rsplit(":", 1)[-1].rstrip("/"))
    except (ValueError, IndexError):
        return 8080


def _detect_extra_endpoints(service_dir: Path) -> List[Dict[str, Any]]:
    """Scan the service app.py for POST/PUT endpoints beyond health and capabilities.

    Returns a list of endpoint metadata dicts ready for template rendering.
    """
    app_path = service_dir / "app.py"
    if not app_path.exists():
        return []

    endpoints: List[Dict[str, Any]] = []
    content = app_path.read_text(encoding="utf-8")

    # Match Flask route decorators: @app.post("/v1/example/process")
    import re as _re
    pattern = _re.compile(
        r'@app\.(post|put|patch)\(\s*["\']([^"\']+)["\']\s*\)',
        _re.IGNORECASE,
    )

    for match in pattern.finditer(content):
        method = match.group(1).upper()
        path = match.group(2)

        # Skip health and capabilities — we handle those natively
        if path == "/health" or path.endswith("/capabilities"):
            continue

        # Derive tool name from path: /v1/example/process → process_example
        segments = [s for s in path.strip("/").split("/") if s and s != "v1"]
        tool_name = "_".join(reversed(segments)) if segments else "call_endpoint"
        # Sanitize for Python identifier
        tool_name = _re.sub(r"[^a-z0-9_]", "_", tool_name.lower()).strip("_")

        description = f"{method} {path}"

        # Check the function docstring if available
        func_start = match.end()
        docstring_match = _re.search(
            r'"""(.+?)"""',
            content[func_start:func_start + 500],
            _re.DOTALL,
        )
        if docstring_match:
            first_line = docstring_match.group(1).strip().split("\n")[0].strip()
            if first_line:
                description = first_line

        endpoints.append({
            "method": method,
            "path": path,
            "tool_name": tool_name,
            "description": description,
            "params": [
                {
                    "name": "payload",
                    "type": "str",
                    "openapi_type": "object",
                    "description": "JSON payload as a string (will be parsed)",
                }
            ] if method == "POST" else [],
            "params_signature": "payload: str = '{}'" if method == "POST" else "",
            "payload_builder": 'json.loads(payload) if isinstance(payload, str) else payload' if method == "POST" else "{}",
            "params_builder": "{}",
        })

    return endpoints


def _build_context(
    service: Dict[str, Any],
    contract: Dict[str, Any],
    *,
    mcp_port: int,
    output_path: str,
) -> Dict[str, Any]:
    """Build the Jinja2 template context from registry + contract data."""
    name = service["name"]
    feature_slug = _slugify(name.replace("-service", ""))
    feature_snake = _snake(name.replace("-service", ""))
    env_prefix = f"MFS_{feature_snake.upper()}"
    default_base_url = service.get("default_base_url", "http://localhost:8080")
    service_port = _extract_port(default_base_url)

    # Check if there's a token env var in the registry
    token_env = f"{env_prefix}_TOKEN"
    token_required = True  # Assume token support is available

    # Build required fields list for OpenAPI
    required_fields = list(contract.get("required_fields", {}).keys())
    allowed_status = contract.get("allowed_status", ["healthy", "degraded", "unavailable"])

    # Detect extra endpoints from service source
    service_dir_name = f"{feature_snake}_service"
    service_dir = ROOT / "services" / service_dir_name
    extra_endpoints = _detect_extra_endpoints(service_dir)

    return {
        "service_name": name,
        "feature_slug": feature_slug,
        "feature_name": feature_slug.replace("-", " ").title(),
        "feature_snake": feature_snake,
        "env_prefix": env_prefix,
        "default_base_url": default_base_url,
        "service_port": service_port,
        "mcp_port": mcp_port,
        "health_path": service.get("health_path", "/health"),
        "contract_path": service.get("contract_path", f"/v1/{feature_slug}/capabilities"),
        "contract_version": contract.get("contract_version", "v1"),
        "contract_json": json.dumps(contract, indent=2),
        "token_required": token_required,
        "required_fields_json": json.dumps(required_fields),
        "allowed_status_json": json.dumps(allowed_status),
        "extra_endpoints": extra_endpoints,
        "output_path": output_path,
    }


def _render_and_write(
    env: Environment,
    template_name: str,
    output_path: Path,
    context: Dict[str, Any],
    *,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite: {output_path}. Use --force.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = env.get_template(template_name)
    rendered = template.render(**context)
    output_path.write_text(rendered, encoding="utf-8")


def scaffold_one(
    service: Dict[str, Any],
    contract: Dict[str, Any],
    *,
    output_dir: Path,
    mcp_port: int,
    force: bool,
    env: Environment,
) -> List[Path]:
    """Scaffold MCP server files for a single service. Returns list of generated paths."""
    context = _build_context(
        service,
        contract,
        mcp_port=mcp_port,
        output_path=str(output_dir),
    )

    files = {
        "server.py.j2": output_dir / "server.py",
        "openapi.json.j2": output_dir / "openapi.json",
        "requirements.txt.j2": output_dir / "requirements.txt",
        "Dockerfile.j2": output_dir / "Dockerfile",
        "README.md.j2": output_dir / "README.md",
    }

    generated = []
    for template_name, out_path in files.items():
        _render_and_write(env, template_name, out_path, context, force=force)
        generated.append(out_path)

    return generated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold an MCP server from an MFS service registry entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--service", default="", help="Service name from registry (e.g. example-service)")
    parser.add_argument("--all", action="store_true", help="Scaffold MCP servers for all registered services")
    parser.add_argument("--mcp-port", type=int, default=0,
                        help="MCP server port (default: service port + 1000)")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    args = parser.parse_args()

    if not args.service and not args.all:
        parser.error("Must specify --service <name> or --all")

    registry = _load_registry()
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )

    if args.all:
        services = registry.get("services", [])
    else:
        svc = _find_service(registry, args.service)
        if not svc:
            available = [s["name"] for s in registry.get("services", [])]
            print(f"ERROR: Service '{args.service}' not found in registry.", file=sys.stderr)
            print(f"Available: {', '.join(available)}", file=sys.stderr)
            return 1
        services = [svc]

    total_generated = []

    for svc in services:
        contract = _load_contract(svc.get("contract_file", ""))
        service_port = _extract_port(svc.get("default_base_url", "http://localhost:8080"))
        mcp_port = args.mcp_port if args.mcp_port else service_port + MCP_PORT_OFFSET

        if args.all:
            feature_slug = _slugify(svc["name"].replace("-service", ""))
            out_dir = Path(args.output).resolve() / feature_slug
        else:
            out_dir = Path(args.output).resolve()

        generated = scaffold_one(
            svc,
            contract,
            output_dir=out_dir,
            mcp_port=mcp_port,
            force=args.force,
            env=env,
        )
        total_generated.extend(generated)

        print(f"\n{'='*60}")
        print(f"  MCP Server scaffolded: {svc['name']}")
        print(f"  MCP port:             {mcp_port}")
        print(f"  Service URL:          {svc.get('default_base_url', 'N/A')}")
        print(f"{'='*60}\n")
        print("Generated files:")
        for path in generated:
            print(f"  {path}")

    if total_generated:
        print(f"\n--- Next Steps ---")
        print(f"1. Start the MFS service:  docker compose up -d --build")
        print(f"2. Install deps:           pip install -r {total_generated[0].parent}/requirements.txt")
        print(f"3. Run MCP server:         python {total_generated[0].parent}/server.py")
        print(f"4. Or with EasyMCP:        easymcp create <name> --openapi {total_generated[0].parent}/openapi.json")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
