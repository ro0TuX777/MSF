# Boundary SDK Guide

## Purpose
Boundary SDK standardizes host-app adapters that call MFS services.

It provides shared behavior for:
- timeout handling,
- retries,
- readiness waits,
- optional autostart command execution,
- feature-flag gating,
- optional local fallback.

## Files
- `boundary_sdk/client.py`
- `templates/boundary/boundary.py.tmpl`
- `tools/scaffold_boundary.py`

## Quick Start
Generate a boundary:

```bash
python tools/scaffold_boundary.py --feature sentiment-analysis --base-url http://localhost:8670
```

Default output:
- `examples/generated_boundaries/sentiment_analysis_boundary.py`

## Boundary Env Contract
Using feature prefix `MFS_SENTIMENT_ANALYSIS`, supported env vars are:
- `MFS_SENTIMENT_ANALYSIS_BASE_URL`
- `MFS_SENTIMENT_ANALYSIS_TOKEN`
- `MFS_SENTIMENT_ANALYSIS_TIMEOUT_S`
- `MFS_SENTIMENT_ANALYSIS_READY_WAIT_S`
- `MFS_SENTIMENT_ANALYSIS_RETRIES`
- `MFS_SENTIMENT_ANALYSIS_RETRY_DELAY_S`
- `MFS_SENTIMENT_ANALYSIS_AUTOSTART_ON_DEMAND`
- `MFS_SENTIMENT_ANALYSIS_AUTOSTART_CMD`
- `MFS_SENTIMENT_ANALYSIS_AUTOSTART_TIMEOUT_S`
- `MFS_SENTIMENT_ANALYSIS_ENABLED`
- `MFS_SENTIMENT_ANALYSIS_ALLOW_LOCAL_FALLBACK`

## Integration Pattern
1. Generate boundary from template.
2. Wire host UI/service calls through generated boundary only.
3. Implement `_local_fallback` only if explicitly required.
4. Keep fallback disabled by default in production.

## Notes
- `AUTOSTART_CMD` is optional. When provided and autostart enabled, command runs before readiness polling.
- SDK treats disabled feature as degraded response (`feature_disabled`) unless custom fallback is enabled.
