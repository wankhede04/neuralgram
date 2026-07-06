# Runbook — GDPR / data-subject erasure

Erasure is a first-class, tested operation (tests/integration/test_gdpr_erasure.py).

## Org-tenant erasure
1. Verify the request's authority (org admin; D1=organizational — memory belongs to the org).
2. `POST /admin/erase` with the tenant's **admin** key. Scope is the caller's own tenant only.
3. The cascade removes: chunks → scores (embeddings included) → chunk_entities → entities
   → summaries → queue jobs referencing the data → vault `.md` files.
4. Retained by design: `usage_events` (billing) and `audit_events` (security) — no memory
   content, legitimate-interest retention. Document this in the response to the requester.
5. Verify: the erasure report counts; re-run is safe (idempotent sweep).
6. Backups: erased data persists in dumps until backup rotation completes — record the
   erasure date and confirm expiry of pre-erasure backups per retention policy.
