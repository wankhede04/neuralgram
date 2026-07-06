# Runbook — Deploy & rollback

## Deploy
1. CI green on `main` (all 7 stages — lint→typecheck→unit→integration+e2e+coverage→security→build).
2. Build/pull the image (`make build` produces `neuralgram:dev`; CI builds per commit).
3. Run migrations **before** rolling pods: `DATABASE_URL=... uv run alembic upgrade head`.
   Migrations are additive and reversible (rehearsed in CI: up/down/up + one-step drill).
4. Roll instances. `/health` must return 200 (Docker HEALTHCHECK gates the boot probe).
5. Watch the dashboard (`ops/dashboards/neuralgram.json`): queue depth, failed jobs,
   p95 latency, cost/tenant. Alerts in `ops/alerts.yml`.

## Rollback
1. Redeploy the previous image tag.
2. If the bad release included a migration: `uv run alembic downgrade -1`
   (rehearsed with live data in `tests/integration/test_rollback_drill.py`;
   note the drill's documented data sacrifice per migration, e.g. 0006 drops audit_events).
3. Verify `/health`, then the dashboard. Announce in the incident channel.

## Constraints
- The app DB role must be NON-superuser (RLS depends on it — ADR-0014).
- `MOCK_PROVIDERS=true` unless real provider keys are configured (cost gate, ADR-0013).
