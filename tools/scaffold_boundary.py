#!/usr/bin/env python3
"""Scaffold a boundary adapter from reusable templates.

Usage:
  python tools/scaffold_boundary.py --feature sentiment-analysis --base-url http://localhost:8670
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from string import Template
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates" / "boundary"


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Feature name must contain at least one alphanumeric character")
    return slug


def _snake(raw: str) -> str:
    return _slugify(raw).replace("-", "_")


def _camel_from_slug(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("-"))


def _load_template(name: str) -> Template:
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing template: {path}")
    return Template(path.read_text(encoding="utf-8"))


def _render(name: str, vars_map: Dict[str, str]) -> str:
    return _load_template(name).substitute(vars_map)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold an MFS boundary adapter")
    parser.add_argument("--feature", required=True, help="Feature name, e.g. sentiment-analysis")
    parser.add_argument("--base-url", required=True, help="Default service base URL")
    parser.add_argument("--output-dir", default="examples/generated_boundaries", help="Output directory for generated boundary")
    parser.add_argument("--class-name", default="", help="Optional boundary class name override")
    parser.add_argument("--env-prefix", default="", help="Optional env prefix override")
    parser.add_argument("--capabilities-path", default="", help="Capabilities path override")
    parser.add_argument("--call-path", default="", help="Primary call path override")
    parser.add_argument("--call-method", default="POST", choices=["GET", "POST"], help="Primary call HTTP method")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args()

    feature_slug = _slugify(args.feature)
    feature_snake = _snake(args.feature)
    class_name = args.class_name.strip() or f"{_camel_from_slug(feature_slug)}Boundary"
    env_prefix = args.env_prefix.strip().upper() or f"MFS_{feature_snake.upper()}"
    capabilities_path = args.capabilities_path.strip() or f"/v1/{feature_slug}/capabilities"
    call_path = args.call_path.strip() or f"/v1/{feature_slug}"
    factory_name = f"get_{feature_snake}_boundary"

    vars_map = {
        "feature_slug": feature_slug,
        "class_name": class_name,
        "env_prefix": env_prefix,
        "default_base_url": args.base_url.strip().rstrip("/"),
        "source_name": f"{feature_snake}_boundary",
        "capabilities_path": capabilities_path,
        "call_path": call_path,
        "call_method": args.call_method,
        "factory_name": factory_name,
    }

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{feature_snake}_boundary.py"
    if output_file.exists() and not args.force:
        raise FileExistsError(f"Output file already exists: {output_file}. Use --force to overwrite.")

    rendered = _render("boundary.py.tmpl", vars_map)
    output_file.write_text(rendered, encoding="utf-8")

    print(f"Generated boundary: {output_file}")
    print(f"Class: {class_name}")
    print(f"Env prefix: {env_prefix}")
    print("Suggested env vars:")
    for name in [
        "BASE_URL",
        "TOKEN",
        "TIMEOUT_S",
        "READY_WAIT_S",
        "RETRIES",
        "RETRY_DELAY_S",
        "AUTOSTART_ON_DEMAND",
        "AUTOSTART_CMD",
        "AUTOSTART_TIMEOUT_S",
        "ENABLED",
        "ALLOW_LOCAL_FALLBACK",
    ]:
        print(f"- {env_prefix}_{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
