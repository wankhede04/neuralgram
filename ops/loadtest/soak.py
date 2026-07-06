"""R-1 load/soak drill: sustained ingest + retrieval against real Postgres.

Run manually (not CI — it soaks for minutes):

    uv run python ops/loadtest/soak.py

Target volume (local-scale; revalidate on production infra when provisioned):
  - 200 documents ingested (multi-chunk, unique content) with the full
    async enrichment pipeline running,
  - 500 mixed search requests (keyword/semantic/hybrid) issued during ingest,
  - SLO: search p95 < 1s; RSS growth < 75 MB; DB connections stable.

Writes the report to ops/reports/load-soak-<date>.md and exits non-zero
if any SLO fails.
"""

import os
import random
import resource
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from neuralgram.api.app import create_app  # noqa: E402
from neuralgram.common.config import Settings  # noqa: E402

DOCS = 200
SEARCHES = 500
API_KEY = "soak-key"  # pragma: allowlist secret
TENANT = "tenant-soak"
SLO_P95_SECONDS = 1.0
SLO_RSS_GROWTH_MB = 75.0

WORDS = (
    "deploy rollout migration checklist latency budget vector retrieval summary "
    "postgres queue worker tenant provenance compression router cache entity digest"
).split()


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / (1024 * 1024 if sys.platform == "darwin" else 1024)


def _payload(i: int) -> dict[str, object]:
    random.seed(i)
    messages = []
    for m in range(5):
        body = " ".join(random.choices(WORDS, k=60)) + f" doc-{i} msg-{m}"
        messages.append(
            {"ts": f"{1783296000 + i * 60 + m}.{i:06d}", "user": f"U{i % 17:03d}", "text": body}
        )
    return {"messages": messages}


def _connection_count(container: PostgresContainer) -> int:
    code, output = container.exec(
        [
            "bash",
            "-c",
            "PGPASSWORD=test psql -U test -d test -tAc "
            "\"SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()\"",
        ]
    )
    assert code == 0, output.decode(errors="replace")
    return int(output.decode().strip())


def main() -> int:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        async_url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": async_url},
            check=True,
            capture_output=True,
        )
        settings = Settings(
            _env_file=None,
            database_url=async_url,
            vault_path=str(REPO_ROOT / ".soak-vault"),
            api_keys={API_KEY: TENANT},
        )

        latencies: list[float] = []
        rss_start = _rss_mb()
        started = time.time()

        with TestClient(create_app(settings)) as client:
            headers = {"x-api-key": API_KEY}
            conn_start = None
            searches_done = 0
            for i in range(DOCS):
                response = client.post(
                    "/memory/ingest",
                    json={"source_id": f"C{i % 5:03d}", "payload": _payload(i)},
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                if conn_start is None:
                    conn_start = _connection_count(container)
                # Interleave searches while workers enrich in the background.
                for _ in range(SEARCHES // DOCS + (1 if i < SEARCHES % DOCS else 0)):
                    mode = random.choice(["keyword", "semantic", "hybrid"])
                    t0 = time.perf_counter()
                    search = client.get(
                        "/memory/search",
                        params={"q": " ".join(random.choices(WORDS, k=3)), "mode": mode},
                        headers=headers,
                    )
                    latencies.append(time.perf_counter() - t0)
                    assert search.status_code == 200, search.text
                    searches_done += 1
            time.sleep(5)  # let the pipeline drain a little before measuring
            conn_end = _connection_count(container)
            metrics_text = client.get("/metrics").text

        duration = time.time() - started
        rss_end = _rss_mb()
        p50 = statistics.quantiles(latencies, n=100)[49]
        p95 = statistics.quantiles(latencies, n=100)[94]
        rss_growth = rss_end - rss_start
        conn_delta = (conn_end or 0) - (conn_start or 0)

        chunks_line = next(
            (
                line
                for line in metrics_text.splitlines()
                if line.startswith("neuralgram_chunks_ingested_total")
            ),
            "n/a",
        )

        slo_pass = p95 < SLO_P95_SECONDS and rss_growth < SLO_RSS_GROWTH_MB and conn_delta <= 5
        report = f"""# Load/soak report — {datetime.now(tz=UTC).date()}

**Verdict: {"PASS" if slo_pass else "FAIL"}**

| Metric | Value | SLO |
|---|---|---|
| Documents ingested | {DOCS} (x5 messages) | — |
| Searches issued | {searches_done} (mixed modes) | — |
| Duration | {duration:.1f}s | — |
| Search p50 | {p50 * 1000:.1f} ms | — |
| Search p95 | {p95 * 1000:.1f} ms | < {SLO_P95_SECONDS * 1000:.0f} ms |
| RSS growth | {rss_growth:.1f} MB | < {SLO_RSS_GROWTH_MB:.0f} MB |
| DB connection delta | {conn_delta} | <= 5 (no leak) |
| Ingest counter | `{chunks_line}` | — |

Local-scale target (mock providers, single node). Revalidate at production
volume on provisioned infra before GA traffic (external-cost gate).
"""
        out = REPO_ROOT / "ops" / "reports" / f"load-soak-{datetime.now(tz=UTC).date()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(report)
        return 0 if slo_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
