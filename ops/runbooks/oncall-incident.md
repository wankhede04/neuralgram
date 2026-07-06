# Runbook — On-call & incident response

## Alert playbook (ops/alerts.yml)
| Alert | First moves |
|---|---|
| NeuralgramJobFailures | `SELECT kind, payload, retry_count FROM jobs WHERE status='failed'`; fix root cause; requeue by setting status='queued', retry_count=0 |
| NeuralgramQueueBacklogHigh | Check worker logs (`worker.job_failed`); verify pool is running (lifespan); scale workers; look for a poison job |
| NeuralgramHttpLatencyHigh | Check DB (`pg_stat_activity`), pgvector query plans, container CPU; consider IVFFlat/HNSW index (ADR-0011 note) |
| NeuralgramTenantSpendSpike | Inspect usage_events for the tenant; confirm caps (TENANT_SPEND_CAPS); a tripped cap returns 429s by design |

## Incident flow
1. Acknowledge; open an incident doc (impact, start time, suspected cause).
2. Stabilize: prefer rollback (see deploy-rollback.md) over forward-fixing under pressure.
3. Data incidents: **never** hand-delete tenant data — use the erasure runbook, or restore
   from backup (rehearsed in tests/integration/test_backup_restore.py).
4. Cross-tenant read suspicion = SEV-1: check `/admin/audit` per tenant and the RLS
   policies (`\d+ chunks` shows tenant_isolation); confirm the app role is non-superuser.
5. Postmortem within 48h; add a regression test before closing.

## Standing invariants (do not "fix" these away)
- Fail-closed RLS; repo-layer scoping; never commit on a red gate; never expose raw API keys
  (audit uses fingerprints).
