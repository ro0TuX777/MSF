#!/usr/bin/env python3
"""MCP Bridge QA Test Suite — validates the full MSF → MCP → Agent chain.

Five-tier test architecture:
  Tier 1: Generation      — scaffold_mcp.py produces valid files
  Tier 2: OpenAPI          — generated spec is structurally valid
  Tier 3: MCP Server       — generated server imports and lists tools
  Tier 4: E2E Chain        — full chain: MSF service → MCP tool call → response
  Tier 5: EasyMCP Compat   — generated OpenAPI is EasyMCP-compatible

Run:
  python -m pytest tests/test_mcp_bridge.py -v
  python -m pytest tests/test_mcp_bridge.py -v -k "tier1"      # Generation only
  python -m pytest tests/test_mcp_bridge.py -v -k "tier4"      # E2E only (needs running service)
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
REGISTRY_PATH = ROOT / "registry" / "services.json"
CONTRACTS_DIR = ROOT / "contracts"

# Inject tools dir for import
sys.path.insert(0, str(TOOLS_DIR))


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def output_dir(tmp_path_factory):
    """Shared temp dir for all generated MCP server files."""
    return tmp_path_factory.mktemp("mcp_output")


@pytest.fixture(scope="session")
def generated_dir(output_dir):
    """Run scaffold_mcp.py once and return the output directory."""
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "scaffold_mcp.py"),
            "--service", "example-service",
            "--output", str(output_dir / "example"),
            "--force",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, f"scaffold_mcp.py failed:\n{result.stderr}"
    return output_dir / "example"


@pytest.fixture(scope="session")
def registry():
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def example_contract():
    path = CONTRACTS_DIR / "example_v1.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Tier 1: Generation ───────────────────────────────────────────

class TestTier1Generation:
    """Verify scaffold_mcp.py produces the expected file set."""

    def test_server_py_exists(self, generated_dir):
        assert (generated_dir / "server.py").exists()

    def test_openapi_json_exists(self, generated_dir):
        assert (generated_dir / "openapi.json").exists()

    def test_requirements_txt_exists(self, generated_dir):
        assert (generated_dir / "requirements.txt").exists()

    def test_dockerfile_exists(self, generated_dir):
        assert (generated_dir / "Dockerfile").exists()

    def test_readme_exists(self, generated_dir):
        assert (generated_dir / "README.md").exists()

    def test_server_is_valid_python(self, generated_dir):
        """Verify the generated server.py has no syntax errors."""
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{generated_dir / 'server.py'}').read())"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error in server.py:\n{result.stderr}"

    def test_requirements_contains_mcp(self, generated_dir):
        content = (generated_dir / "requirements.txt").read_text()
        assert "mcp" in content.lower()

    def test_requirements_contains_requests(self, generated_dir):
        content = (generated_dir / "requirements.txt").read_text()
        assert "requests" in content.lower()

    def test_all_flag_generates_multiple(self, output_dir):
        """--all should generate one subdirectory per registered service."""
        all_dir = output_dir / "all_services"
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "scaffold_mcp.py"),
                "--all",
                "--output", str(all_dir),
                "--force",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, f"--all failed:\n{result.stderr}"
        # Should have at least the example service directory
        subdirs = [p for p in all_dir.iterdir() if p.is_dir()]
        assert len(subdirs) >= 1, f"Expected subdirectories, got: {[p.name for p in subdirs]}"

    def test_invalid_service_name_fails(self, output_dir):
        """Unknown service name should return nonzero exit code."""
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "scaffold_mcp.py"),
                "--service", "nonexistent-service",
                "--output", str(output_dir / "should_not_exist"),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode != 0


# ── Tier 2: OpenAPI Validation ───────────────────────────────────

class TestTier2OpenAPI:
    """Verify the generated OpenAPI spec is structurally sound."""

    def test_openapi_is_valid_json(self, generated_dir):
        content = (generated_dir / "openapi.json").read_text()
        spec = json.loads(content)
        assert isinstance(spec, dict)

    def test_openapi_version(self, generated_dir):
        spec = json.loads((generated_dir / "openapi.json").read_text())
        assert spec.get("openapi", "").startswith("3.")

    def test_openapi_has_info(self, generated_dir):
        spec = json.loads((generated_dir / "openapi.json").read_text())
        assert "info" in spec
        assert "title" in spec["info"]
        assert "version" in spec["info"]

    def test_openapi_has_servers(self, generated_dir):
        spec = json.loads((generated_dir / "openapi.json").read_text())
        assert "servers" in spec
        assert len(spec["servers"]) >= 1
        assert "url" in spec["servers"][0]

    def test_openapi_has_health_path(self, generated_dir):
        spec = json.loads((generated_dir / "openapi.json").read_text())
        paths = spec.get("paths", {})
        assert "/health" in paths, f"Missing /health in paths: {list(paths.keys())}"

    def test_openapi_has_capabilities_path(self, generated_dir):
        spec = json.loads((generated_dir / "openapi.json").read_text())
        paths = spec.get("paths", {})
        capabilities_paths = [p for p in paths if "capabilities" in p]
        assert len(capabilities_paths) >= 1, f"No capabilities path found: {list(paths.keys())}"

    def test_openapi_operations_have_ids(self, generated_dir):
        """Every operation should have an operationId for MCP tool naming."""
        spec = json.loads((generated_dir / "openapi.json").read_text())
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    assert "operationId" in operation, (
                        f"Missing operationId for {method.upper()} {path}"
                    )

    def test_openapi_contract_fields_match(self, generated_dir, example_contract):
        """OpenAPI schema required fields should match the MSF contract."""
        spec = json.loads((generated_dir / "openapi.json").read_text())
        contract_fields = list(example_contract.get("required_fields", {}).keys())

        # Find capabilities endpoint response schema
        cap_path = example_contract.get("endpoint", "")
        if cap_path in spec.get("paths", {}):
            get_op = spec["paths"][cap_path].get("get", {})
            schema = (
                get_op.get("responses", {})
                .get("200", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            spec_required = schema.get("required", [])
            for field in contract_fields:
                assert field in spec_required, (
                    f"Contract field '{field}' missing from OpenAPI required: {spec_required}"
                )


# ── Tier 3: MCP Server Module ───────────────────────────────────

class TestTier3MCPServer:
    """Verify the generated MCP server is importable and defines tools."""

    def test_server_defines_mcp_instance(self, generated_dir):
        """server.py should define a FastMCP instance named 'mcp'."""
        content = (generated_dir / "server.py").read_text()
        assert "FastMCP" in content
        assert "mcp = FastMCP(" in content

    def test_server_defines_health_tool(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert "def health_check(" in content
        assert "@mcp.tool()" in content

    def test_server_defines_capabilities_tool(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert "def get_capabilities(" in content

    def test_server_defines_resources(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert "@mcp.resource(" in content
        assert "contract" in content
        assert "service://" in content

    def test_server_has_main_entrypoint(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content

    def test_server_supports_transport_args(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert "--transport" in content
        assert "stdio" in content
        assert "sse" in content

    def test_server_uses_correct_env_prefix(self, generated_dir):
        content = (generated_dir / "server.py").read_text()
        assert "MFS_EXAMPLE" in content

    def test_server_has_docstrings(self, generated_dir):
        """Every tool function should have a docstring for MCP discovery."""
        content = (generated_dir / "server.py").read_text()
        # After each @mcp.tool() + def, there should be a docstring
        import re
        tools = re.findall(r'@mcp\.tool\(\)\ndef \w+\([^)]*\)[^:]*:\s*"""', content)
        # At minimum health_check and get_capabilities
        assert len(tools) >= 2, f"Expected at least 2 documented tools, found {len(tools)}"


# ── Tier 4: E2E Chain ────────────────────────────────────────────

class TestTier4E2EChain:
    """Full chain test: MSF service → MCP tool → response.

    These tests mock the HTTP calls to avoid requiring a running service,
    but validate the complete data flow through the generated server code.
    """

    def test_health_tool_returns_json(self, generated_dir):
        """Mock HTTP and verify health_check returns valid JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "service": "example-service",
            "contract_version": "v1",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            # Dynamically import the generated server
            spec = importlib.util.spec_from_file_location(
                "mcp_server_test", generated_dir / "server.py"
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                # Mock FastMCP before loading
                mock_mcp = MagicMock()
                mock_mcp.tool.return_value = lambda f: f
                mock_mcp.resource.return_value = lambda f: f
                with patch.dict("sys.modules", {"mcp.server.fastmcp": MagicMock(FastMCP=lambda *a, **kw: mock_mcp)}):
                    spec.loader.exec_module(module)
                    result = module.health_check()
                    parsed = json.loads(result)
                    assert parsed["status"] == "ok"
                    assert parsed["service"] == "example-service"

    def test_capabilities_tool_returns_contract(self, generated_dir):
        """Mock HTTP and verify get_capabilities returns contract fields."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "contract_version": "v1",
            "status": "healthy",
            "source": "example_service",
            "generated_at": "2026-05-19T00:00:00Z",
            "feature": "example",
            "supports": ["process"],
            "error": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            spec = importlib.util.spec_from_file_location(
                "mcp_server_test_2", generated_dir / "server.py"
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                mock_mcp = MagicMock()
                mock_mcp.tool.return_value = lambda f: f
                mock_mcp.resource.return_value = lambda f: f
                with patch.dict("sys.modules", {"mcp.server.fastmcp": MagicMock(FastMCP=lambda *a, **kw: mock_mcp)}):
                    spec.loader.exec_module(module)
                    result = module.get_capabilities()
                    parsed = json.loads(result)
                    assert parsed["contract_version"] == "v1"
                    assert parsed["status"] == "healthy"
                    assert "supports" in parsed

    def test_error_handling_returns_unavailable(self, generated_dir):
        """When service is down, tools should return error JSON, not crash."""
        with patch("requests.get", side_effect=ConnectionError("Connection refused")):
            spec = importlib.util.spec_from_file_location(
                "mcp_server_test_3", generated_dir / "server.py"
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                mock_mcp = MagicMock()
                mock_mcp.tool.return_value = lambda f: f
                mock_mcp.resource.return_value = lambda f: f
                with patch.dict("sys.modules", {"mcp.server.fastmcp": MagicMock(FastMCP=lambda *a, **kw: mock_mcp)}):
                    spec.loader.exec_module(module)
                    result = module.health_check()
                    parsed = json.loads(result)
                    assert parsed["status"] == "unavailable"
                    assert "error" in parsed

    def test_contract_resource_returns_spec(self, generated_dir, example_contract):
        """The contract MCP resource should return the full MSF contract JSON."""
        spec = importlib.util.spec_from_file_location(
            "mcp_server_test_4", generated_dir / "server.py"
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            mock_mcp = MagicMock()
            mock_mcp.tool.return_value = lambda f: f
            mock_mcp.resource.return_value = lambda f: f
            with patch.dict("sys.modules", {"mcp.server.fastmcp": MagicMock(FastMCP=lambda *a, **kw: mock_mcp)}):
                spec.loader.exec_module(module)
                result = module.contract_resource()
                parsed = json.loads(result)
                assert parsed.get("service_name") == example_contract.get("service_name")
                assert parsed.get("contract_version") == example_contract.get("contract_version")


# ── Tier 5: EasyMCP Compatibility ────────────────────────────────

class TestTier5EasyMCPCompat:
    """Verify the generated OpenAPI spec is compatible with EasyMCP consumption.

    EasyMCP expects:
    - Valid OpenAPI 3.x spec
    - operationId on every operation (used as MCP tool name)
    - Server URL defined
    - Standard HTTP methods
    """

    def test_all_operations_have_summary(self, generated_dir):
        """EasyMCP uses summary for tool descriptions."""
        spec = json.loads((generated_dir / "openapi.json").read_text())
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    assert "summary" in operation or "description" in operation, (
                        f"Missing summary/description for {method.upper()} {path}"
                    )

    def test_server_url_is_accessible_format(self, generated_dir):
        """Server URL should be a proper HTTP URL."""
        spec = json.loads((generated_dir / "openapi.json").read_text())
        url = spec["servers"][0]["url"]
        assert url.startswith("http://") or url.startswith("https://")

    def test_operation_ids_are_unique(self, generated_dir):
        """EasyMCP maps operationId → tool name, so they must be unique."""
        spec = json.loads((generated_dir / "openapi.json").read_text())
        op_ids = []
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    op_id = operation.get("operationId")
                    if op_id:
                        op_ids.append(op_id)
        assert len(op_ids) == len(set(op_ids)), f"Duplicate operationIds: {op_ids}"

    def test_operation_ids_are_snake_case(self, generated_dir):
        """Tool names should be clean snake_case identifiers."""
        import re
        spec = json.loads((generated_dir / "openapi.json").read_text())
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    op_id = operation.get("operationId", "")
                    assert re.match(r'^[a-z][a-z0-9_]*$', op_id), (
                        f"operationId '{op_id}' is not valid snake_case"
                    )

    def test_spec_has_no_external_refs(self, generated_dir):
        """Self-contained spec — no $ref to external files."""
        content = (generated_dir / "openapi.json").read_text()
        assert "$ref" not in content, "OpenAPI spec should be self-contained (no $ref)"

    def test_easymcp_create_command_in_readme(self, generated_dir):
        """README should document the EasyMCP complementary path."""
        content = (generated_dir / "README.md").read_text()
        assert "easymcp" in content.lower()
        assert "openapi.json" in content


# ── Tier Bonus: Dockerfile Validation ────────────────────────────

class TestDockerfile:
    """Basic Dockerfile structural checks."""

    def test_dockerfile_has_from(self, generated_dir):
        content = (generated_dir / "Dockerfile").read_text()
        assert content.strip().startswith("FROM")

    def test_dockerfile_copies_server(self, generated_dir):
        content = (generated_dir / "Dockerfile").read_text()
        assert "server.py" in content

    def test_dockerfile_exposes_port(self, generated_dir):
        content = (generated_dir / "Dockerfile").read_text()
        assert "EXPOSE" in content

    def test_dockerfile_sets_transport(self, generated_dir):
        content = (generated_dir / "Dockerfile").read_text()
        assert "MCP_TRANSPORT" in content
