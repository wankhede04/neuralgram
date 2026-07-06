# Runbook — Secrets rotation

Neuralgram reads all secrets through typed `Settings` (env vars, overridden by files in
`NEURALGRAM_SECRETS_DIR` — mount your secret manager's material there, e.g. Docker/K8s
secrets at `/run/secrets`). No secret ever lives in the repo; CI enforces this with
detect-secrets on every commit.

## Inventory
| Secret | Settings field | Consumer |
|---|---|---|
| Tenant API keys | `api_keys` / `api_key_roles` (JSON) | C5 auth (`x-api-key`) |
| Postgres credentials | `database_url` | engine + Alembic |
| Redis URL | `redis_url` | response cache |
| Provider keys (post cost-gate) | anthropic/openai key fields | C4 adapters |

## Rotating tenant API keys (zero downtime — rehearsed in CI)
1. Generate the new key; add it to `api_keys` (and `api_key_roles`) **alongside** the
   old one, mapping to the same tenant/role.
2. Deploy. Both keys now authenticate (overlap window).
3. Roll the client over to the new key; verify traffic via the audit trail
   (`GET /admin/audit` — actors are key fingerprints).
4. Remove the old key from the mapping; deploy. Old key returns 401.
The overlap+revoke flow is executed as a test on every CI run
(`tests/integration/test_secrets_rotation.py`).

## Rotating the Postgres password
1. `ALTER ROLE neuralgram_app PASSWORD '...'` (the app role is NON-superuser — RLS
   depends on this, see ADR-0014).
2. Update `database_url` in the secret store; redeploy (pool reconnects on restart).
3. Rollback: restore the previous secret version.

## Rotating provider keys (Anthropic/OpenAI)
1. Create the new key in the provider console; update the secret; redeploy.
2. Failover keeps serving during the rollout (M4-2 circuit breaker).
3. Revoke the old key at the provider **after** the rollout completes.

## Cadence & response
- Routine: quarterly. Compromise: rotate immediately, then audit `/admin/audit`
  for the compromised fingerprint and review the affected tenant's trail.
