#!/usr/bin/env python3
"""Scaffold an agent-facing SDK for external consumption of an MFS-extracted service.

Usage (minimal — stateless API):
  python tools/scaffold_agent_sdk.py --app-name "MyAPI" --app-slug myapi --port 8080 --governance stateless --output ./myapi_sdk/

Usage (full governance):
  python tools/scaffold_agent_sdk.py --app-name "AcmeScanner" --app-slug acmescanner --port 5000 --governance full --output ./acmescanner_sdk/

Usage (from manifest):
  python tools/scaffold_agent_sdk.py --from-manifest agent_sdk_manifest.yaml --output ./myapp_sdk/
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates" / "agent_sdk"

GOVERNANCE_MODES = ("full", "session_only", "stateless")

# Default values for optional manifest fields
DEFAULTS = {
    "api_base_path": "/api/v1",
    "health_endpoint": "/health",
    "session_create_path": "/session",
    "session_refresh_path": "/session/refresh",
    "session_id_field": "session_id",
    "intent_endpoint": "/intent",
}


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        raise ValueError("App name must contain at least one alphanumeric character.")
    return slug


def _snake(raw: str) -> str:
    return _slugify(raw).replace("-", "_")


def _pascal(raw: str) -> str:
    return "".join(part.capitalize() for part in _slugify(raw).split("-"))


def _upper_snake(raw: str) -> str:
    return _snake(raw).upper()


def _build_action_context(action: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich an action dict with template-friendly computed fields."""
    params = action.get("parameters", [])

    # Build Python method signature
    sig_parts = []
    for p in params:
        ptype = p.get("type", "Any")
        if p.get("required", True):
            sig_parts.append(f"{p['name']}: {ptype}")
        else:
            default = p.get("default", "None")
            sig_parts.append(f"{p['name']}: Optional[{ptype}] = {default}")

    params_signature = (", " + ", ".join(sig_parts)) if sig_parts else ""

    # Build test call args (use sensible defaults for each type)
    test_parts = []
    for p in params:
        if p.get("required", True):
            ptype = p.get("type", "str")
            if ptype == "str":
                test_parts.append(f'"{p["name"]}_test"')
            elif ptype == "int":
                test_parts.append("1")
            elif ptype == "float":
                test_parts.append("1.0")
            elif ptype == "bool":
                test_parts.append("True")
            elif "List" in ptype:
                test_parts.append("[]")
            elif "Dict" in ptype:
                test_parts.append("{}")
            else:
                test_parts.append(f'"{p["name"]}_test"')

    test_args = ", ".join(test_parts)

    return {
        **action,
        "params_signature": params_signature,
        "test_args": test_args,
        "parameters": params,
    }


def _load_manifest(path: Path) -> Dict[str, Any]:
    """Load a YAML manifest file."""
    if not HAS_YAML:
        print("ERROR: PyYAML is required for --from-manifest. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    if not path.exists():
        print(f"ERROR: Manifest file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_context_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """Build template context from CLI arguments."""
    return {
        "app_name": args.app_name,
        "app_slug": _snake(args.app_slug),
        "app_pascal": _pascal(args.app_slug),
        "app_upper": _upper_snake(args.app_slug),
        "default_port": str(args.port),
        "governance_mode": args.governance,
        "api_base_path": args.api_base_path or DEFAULTS["api_base_path"],
        "health_endpoint": args.health_endpoint or DEFAULTS["health_endpoint"],
        "session_create_path": DEFAULTS["session_create_path"],
        "session_refresh_path": DEFAULTS["session_refresh_path"],
        "session_id_field": DEFAULTS["session_id_field"],
        "intent_endpoint": DEFAULTS["intent_endpoint"],
        "actions": [],
        "custom_errors": [],
    }


def _build_context_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Build template context from a YAML manifest."""
    service = manifest.get("service", {})
    app_name = service.get("app_name", "MyApp")
    app_slug = _snake(service.get("app_slug", app_name))

    actions_raw = manifest.get("actions", [])
    actions = [_build_action_context(a) for a in actions_raw]

    custom_errors = manifest.get("errors", [])

    return {
        "app_name": app_name,
        "app_slug": app_slug,
        "app_pascal": _pascal(service.get("app_slug", app_name)),
        "app_upper": _upper_snake(service.get("app_slug", app_name)),
        "default_port": str(service.get("default_port", 8080)),
        "governance_mode": service.get("governance_mode", "stateless"),
        "api_base_path": service.get("api_base_path", DEFAULTS["api_base_path"]),
        "health_endpoint": service.get("health_endpoint", DEFAULTS["health_endpoint"]),
        "session_create_path": service.get("session_create_endpoint", DEFAULTS["session_create_path"]),
        "session_refresh_path": service.get("session_refresh_endpoint", DEFAULTS["session_refresh_path"]),
        "session_id_field": service.get("session_id_field", DEFAULTS["session_id_field"]),
        "intent_endpoint": service.get("intent_endpoint", DEFAULTS["intent_endpoint"]),
        "actions": actions,
        "custom_errors": custom_errors,
    }


def _render_and_write(env: Environment, template_name: str, output_path: Path,
                      context: Dict[str, Any], *, force: bool) -> None:
    """Render a Jinja2 template and write to disk."""
    if output_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite: {output_path}. Use --force.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = env.get_template(template_name)
    rendered = template.render(**context)
    output_path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold an agent-facing SDK for an MFS-extracted service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Manifest mode
    parser.add_argument("--from-manifest", default="", help="Path to agent_sdk_manifest.yaml")

    # Direct CLI mode
    parser.add_argument("--app-name", default="", help="Human-readable application name (e.g., 'AcmeScanner')")
    parser.add_argument("--app-slug", default="", help="Python-safe slug (e.g., 'acmescanner')")
    parser.add_argument("--port", type=int, default=8080, help="Default service port")
    parser.add_argument("--governance", choices=GOVERNANCE_MODES, default="stateless",
                        help="Governance mode: full, session_only, or stateless")
    parser.add_argument("--api-base-path", default="", help="API base path (default: /api/v1)")
    parser.add_argument("--health-endpoint", default="", help="Health check endpoint (default: /health)")

    # Output
    parser.add_argument("--output", required=True, help="Output directory for the generated SDK")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    args = parser.parse_args()

    # Build context from manifest or CLI args
    if args.from_manifest:
        manifest = _load_manifest(Path(args.from_manifest))
        context = _build_context_from_manifest(manifest)
    else:
        if not args.app_name or not args.app_slug:
            parser.error("--app-name and --app-slug are required when not using --from-manifest")
        context = _build_context_from_args(args)

    # Validate governance mode
    if context["governance_mode"] not in GOVERNANCE_MODES:
        parser.error(f"Invalid governance mode: {context['governance_mode']}. Must be one of {GOVERNANCE_MODES}")

    # Setup Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Resolve output paths — enforce directory name matches Python package name
    output_dir = Path(args.output).resolve()
    app_slug = context["app_slug"]
    expected_dir_name = f"{app_slug}_sdk"

    # If the output dir name doesn't match the package import name, auto-correct
    if output_dir.name != expected_dir_name:
        corrected = output_dir.parent / expected_dir_name
        print(f"NOTE: Output dir renamed to '{expected_dir_name}' to match Python import name")
        sdk_dir = corrected
    else:
        sdk_dir = output_dir
    tests_dir = sdk_dir.parent / "tests"

    # File mapping: template → output
    files = {
        "__init__.py.j2": sdk_dir / "__init__.py",
        "config.py.j2": sdk_dir / "config.py",
        "errors.py.j2": sdk_dir / "errors.py",
        "client.py.j2": sdk_dir / "client.py",
        "test_sdk.py.j2": tests_dir / f"test_{app_slug}_sdk.py",
    }

    # Render all templates
    generated = []
    for template_name, output_path in files.items():
        _render_and_write(env, template_name, output_path, context, force=args.force)
        generated.append(output_path)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Agent SDK scaffolded: {context['app_name']}")
    print(f"  Governance mode:      {context['governance_mode']}")
    print(f"  Default port:         {context['default_port']}")
    print(f"{'='*60}\n")
    print("Generated files:")
    for path in generated:
        print(f"  {path}")

    print(f"\nEnvironment variables (prefix: {context['app_upper']}):")
    env_vars = [
        f"{context['app_upper']}_BASE_URL",
        f"{context['app_upper']}_AGENT_CLASS",
        f"{context['app_upper']}_TIMEOUT_S",
        f"{context['app_upper']}_RETRIES",
        f"{context['app_upper']}_RETRY_DELAY_S",
    ]
    if context["governance_mode"] != "stateless":
        env_vars.append(f"{context['app_upper']}_SESSION_TTL")
    if context["governance_mode"] == "full":
        env_vars.append(f"{context['app_upper']}_TRUST_TIER")
    for var in env_vars:
        print(f"  {var}")

    n_actions = len(context.get("actions", []))
    if n_actions:
        print(f"\nAction methods generated: {n_actions}")
        for a in context["actions"]:
            print(f"  client.{a['name']}()")
    else:
        print("\nNo actions defined — add methods manually or use --from-manifest")

    print(f"\nRun tests:")
    print(f"  python -m pytest {tests_dir / f'test_{app_slug}_sdk.py'} -v")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
