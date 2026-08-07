import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { ErrorBanner } from "../components/ErrorBanner";
import { Input } from "../components/Input";
import { PageHeader } from "../components/PageHeader";
import { apiClient, ApiError } from "../lib/apiClient";

type AuditRecord = {
  actor: string;
  action: string;
  resource: string;
  status: number;
  created_at: string;
};

export function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState("100");

  const fetchAudit = () => {
    setLoading(true);
    setError(null);
    apiClient
      .get<AuditRecord[]>("/admin/audit", { limit })
      .then(setRecords)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load audit log.")
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <PageHeader title="Audit" subtitle="Who queried whose memory" />
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      <div className="mb-4 flex items-end gap-3">
        <div className="w-24">
          <Input label="Limit" type="number" value={limit} onChange={setLimit} />
        </div>
        <Button type="button" onClick={fetchAudit} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </Button>
      </div>
      <Card>
        {loading ? (
          <p className="text-sm text-slate-400">Loading...</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="pb-2">Actor</th>
                <th className="pb-2">Action</th>
                <th className="pb-2">Resource</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">When</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-2 font-mono text-xs">{record.actor}</td>
                  <td className="py-2">{record.action}</td>
                  <td className="py-2 font-mono text-xs">{record.resource}</td>
                  <td className="py-2">{record.status}</td>
                  <td className="py-2 text-xs text-slate-400">{record.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
