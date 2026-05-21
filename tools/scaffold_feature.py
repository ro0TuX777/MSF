#!/usr/bin/env python3
"""Scaffold a new MFS feature service, contract, and registry entry.

Usage:
  python tools/scaffold_feature.py --feature sentiment-analysis --port 8670
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from string import Template
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "registry" / "services.json"
CONTRACTS_DIR = ROOT / "contracts"
SERVICES_DIR = ROOT / "services"
TEMPLATES_DIR = ROOT / "templates" / "scaffold"


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Feature name must contain at least one alphanumeric character.")
    return slug


def _snake(raw: str) -> str:
    return _slugify(raw).replace("-", "_")


def _load_registry() -> Dict[str, Any]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(payload: Dict[str, Any]) -> None:
    with REGISTRY_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _write_file(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_template(name: str) -> Template:
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing template file: {path}")
    return Template(path.read_text(encoding="utf-8"))


def _render_template(name: str, vars_map: Dict[str, Any]) -> str:
    normalized = {k: str(v) for k, v in vars_map.items()}
    return _load_template(name).substitute(normalized)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new MFS feature service")
    parser.add_argument("--feature", required=True, help="Feature name (for example: sentiment-analysis)")
    parser.add_argument("--port", type=int, required=True, help="Service port")
    parser.add_argument("--force", action="store_true", help="Overwrite generated files if they already exist")
    args = parser.parse_args()

    feature_slug = _slugify(args.feature)
    feature_snake = _snake(args.feature)
    feature_key = feature_slug.replace("-", "_")
    service_name = f"{feature_slug}-service"
    service_source = f"{feature_slug}_service"
    service_dir = f"{feature_snake}_service"
    endpoint = f"/v1/{feature_slug}/capabilities"
    port_env = f"MFS_{feature_snake.upper()}_PORT"

    contract_path = CONTRACTS_DIR / f"{feature_snake}_v1.json"
    service_root = SERVICES_DIR / service_dir
    app_path = service_root / "app.py"
    dockerfile_path = service_root / "Dockerfile"
    requirements_path = service_root / "requirements.txt"

    registry = _load_registry()
    services = registry.setdefault("services", [])
    if any(svc.get("name") == service_name for svc in services):
        raise ValueError(f"Registry already contains service '{service_name}'.")

    vars_map = {
        "feature_slug": feature_slug,
        "feature_snake": feature_snake,
        "feature_key": feature_key,
        "service_name": service_name,
        "service_source": service_source,
        "service_dir": service_dir,
        "service_module": service_dir,
        "endpoint": endpoint,
        "port": args.port,
        "port_env": port_env,
    }

    _write_file(contract_path, _render_template("contract_v1.json.tmpl", vars_map), force=args.force)
    _write_file(app_path, _render_template("app.py.tmpl", vars_map), force=args.force)
    _write_file(dockerfile_path, _render_template("Dockerfile.tmpl", vars_map), force=args.force)
    _write_file(requirements_path, _render_template("requirements.txt.tmpl", vars_map), force=args.force)

    services.append(
        {
            "name": service_name,
            "base_url_envs": [f"MFS_{feature_snake.upper()}_BASE_URL"],
            "default_base_url": f"http://localhost:{args.port}",
            "health_path": "/health",
            "contract_path": endpoint,
            "contract_file": f"contracts/{feature_snake}_v1.json",
        }
    )
    _save_registry(registry)

    print(f"Created {service_name}")
    print(f"- {contract_path.relative_to(ROOT)}")
    print(f"- {app_path.relative_to(ROOT)}")
    print(f"- {dockerfile_path.relative_to(ROOT)}")
    print(f"- {requirements_path.relative_to(ROOT)}")
    print("Updated registry/services.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
