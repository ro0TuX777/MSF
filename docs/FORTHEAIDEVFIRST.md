You are in execution mode. Do not stay at high-level discussion. Produce artifacts and commands first, then summarize.

Mission:
Migrate a legacy app toward containerized microservices using the MSF Framework, while preserving legacy UI/routes/UX.

Inputs:
- MSF path: <MSF_PATH>
- Legacy repo: <LEGACY_REPO_PATH>
- Priority features (optional): <FEATURES_CSV>

Step 1: Read MSF docs (required)
- <MSF_PATH>/README.md
- <MSF_PATH>/docs/MFS_FRAMEWORK_REFERENCE.md
- <MSF_PATH>/docs/MIGRATION_PLAYBOOK.md
- <MSF_PATH>/docs/CUTOVER_ORCHESTRATION.md
- <MSF_PATH>/docs/UI_PARITY_HARNESS.md
- <MSF_PATH>/docs/ONBOARDING_COMMAND.md
- <MSF_PATH>/docs/AGENT_SDK.md

Step 2: Run onboarding + discovery (required)
- python <MSF_PATH>/tools/mfs_onboard.py --target <LEGACY_REPO_PATH> --profile auto --run-discovery --force
- If feature hints provided, include:
  --features <FEATURES_CSV>

Step 3: Build AI migration context pack (required)
- python <MSF_PATH>/tools/build_migration_pack.py --workspace <LEGACY_REPO_PATH>/mfs_migration --top 10 --include-file-snippets

Step 4: Score and select extraction candidates (required)
- Use generated candidate scores + runtime/discovery signals.
- Select top 3 candidates for phased extraction.

Step 5: Produce concrete migration plan (required)
For each top candidate provide:
- Proposed service boundary
- Contract file path/version plan
- Boundary adapter approach (timeouts/retries/readiness/fallback)
- Containerization steps
- Cutover stages + rollback path
- UI parity checks (checklist + smoke + browser)

Step 5.5: Agent SDK (optional — prompt before executing)
After boundary wiring, ask the operator:
> "Should I also scaffold an agent-facing SDK for external agent consumption?"
If yes:
- Determine governance mode (full / session_only / stateless)
- List actions to expose
- Run: python <MSF_PATH>/tools/scaffold_agent_sdk.py --app-name "<APP>" --app-slug "<app>" --port <PORT> --governance <MODE> --output ./<app>_sdk/
- See <MSF_PATH>/docs/AGENT_SDK.md for details

Step 5.6: MCP Bridge (optional — prompt before executing)
After boundary wiring, ask the operator:
> "Should I also scaffold an MCP server so agents can consume this service via MCP?"
If yes:
- Run: python <MSF_PATH>/tools/scaffold_mcp.py --service <SERVICE_NAME> --output ./mcp_servers/<feature>/
- Generated server works with Claude Desktop (stdio), any MCP client (SSE), and EasyMCP (OpenAPI)
- See <MSF_PATH>/docs/MCP_BRIDGE.md for details

Step 6: Emit executable next actions (required)
Provide the next 10 commands to run, in order, with expected output artifacts.

Output format (strict):
1) What you executed
2) Generated artifacts (paths)
3) Top-3 candidates table (impact/risk/complexity/UI-coupling/sequence)
4) Phase plan with cutover + rollback
5) UI parity gate plan
6) Next 10 exact commands
7) Risks, assumptions, unresolved questions

Constraints:
- Preserve existing UI/routes unless explicitly justified.
- Prefer incremental canary cutover over big-bang replacement.
- Block promotion if parity or health gates fail.
