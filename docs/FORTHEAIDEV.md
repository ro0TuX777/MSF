You are migrating a legacy app using the MSF Framework.

Context:
- MSF framework path: <MSF_PATH>
- Legacy repo path: <LEGACY_REPO_PATH>
- Goal: extract high-value legacy features into containerized microservices while preserving existing UI/routes/UX as much as possible.

First, read these MSF docs completely:
1) <MSF_PATH>/README.md
2) <MSF_PATH>/docs/MFS_FRAMEWORK_REFERENCE.md
3) <MSF_PATH>/docs/MIGRATION_PLAYBOOK.md
4) <MSF_PATH>/docs/CUTOVER_ORCHESTRATION.md
5) <MSF_PATH>/docs/UI_PARITY_HARNESS.md
6) <MSF_PATH>/docs/ONBOARDING_COMMAND.md
7) <MSF_PATH>/docs/AGENT_SDK.md

Then execute this workflow in the legacy repo:
1) Run onboarding:
   python <MSF_PATH>/tools/mfs_onboard.py --target <LEGACY_REPO_PATH> --profile auto --run-discovery
2) Review generated artifacts in <LEGACY_REPO_PATH>/mfs_migration/.
3) Identify and rank extraction candidates (focus on high impact + clear boundaries + manageable UI coupling).
4) Propose phased migration plan:
   - candidate order
   - contract/boundary approach
   - containerization approach
   - cutover stages (canary/rollback)
   - UI parity protection strategy
5) For the top candidate, generate concrete implementation steps and exact commands/files to create or modify using MSF tools.

## Agent-Facing SDK (Optional)

After a service is extracted and boundaries are wired, the operator may
request an agent-facing SDK for external consumption. This is appropriate when:

- An external agent (LLM, orchestrator, another application) needs to call
  this application programmatically
- The application has a governed API (CONCORD or equivalent)
- Multiple consumers need to share session/retry/error handling logic

### When to prompt

After completing service extraction and boundary wiring, ask:

> "The service boundaries are wired. Should I also scaffold an agent-facing
> SDK so external agents can consume this application? This generates a typed
> Python client with session management, retry logic, and error classification."

### How to scaffold

If the operator says yes:

1. Identify the governance mode (full / session_only / stateless)
2. List the actions the SDK should expose
3. Run: python <MSF_PATH>/tools/scaffold_agent_sdk.py --app-name "<APP>" --app-slug "<app>" --port <PORT> --governance <MODE> --output ./<app>_sdk/
4. Wire tests into the existing test suite
5. See <MSF_PATH>/docs/AGENT_SDK.md for full details.

Output format required:
- Executive summary
- Top 5 candidate table (impact, risk, complexity, UI coupling, recommended order)
- Phase-by-phase migration plan
- Cutover + rollback plan
- UI parity validation plan
- Immediate next 10 actions with exact commands
- Risks/assumptions/open questions
