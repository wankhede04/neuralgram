import { useState } from "react";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { ErrorBanner } from "../components/ErrorBanner";
import { Input } from "../components/Input";
import { PageHeader } from "../components/PageHeader";
import { Select } from "../components/Select";
import { apiClient, ApiError } from "../lib/apiClient";

type SummaryNode = {
  summary_id: string;
  tree_type: string;
  scope_id: string;
  level: number;
  body_md: string;
};

export function SummariesPage() {
  const [tree, setTree] = useState("source");
  const [scopeId, setScopeId] = useState("");
  const [level, setLevel] = useState("");
  const [results, setResults] = useState<SummaryNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setSearched(true);
    try {
      const params: Record<string, string> = { tree, scope_id: scopeId };
      if (tree === "source" && level.trim() !== "") {
        params.level = level;
      }
      const response = await apiClient.get<SummaryNode[]>("/memory/summaries", params);
      setResults(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Lookup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Summaries"
        subtitle="Source drill-down, topic, and daily digest views"
      />
      <p className="text-sm text-slate-500 mb-4">
        A source needs at least 8 ingested messages before a summary is generated for
        it — ingest more messages for the same source_id, then look it up here.
      </p>
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      <Card className="mb-6">
        <form onSubmit={handleSubmit} className="flex items-end gap-3">
          <div className="w-40">
            <Select
              label="Tree"
              value={tree}
              onChange={setTree}
              options={[
                { value: "source", label: "Source" },
                { value: "topic", label: "Topic" },
                { value: "global", label: "Global (daily)" },
              ]}
            />
          </div>
          <div className="flex-1">
            <Input
              label="Scope ID"
              value={scopeId}
              onChange={setScopeId}
              placeholder={tree === "global" ? "YYYY-MM-DD" : "source_id or topic name"}
              required
            />
          </div>
          {tree === "source" && (
            <div className="w-24">
              <Input label="Level" type="number" value={level} onChange={setLevel} />
            </div>
          )}
          <Button type="submit" disabled={loading}>
            {loading ? "Loading..." : "Look up"}
          </Button>
        </form>
      </Card>
      <div className="space-y-3">
        {results.map((node) => (
          <Card key={node.summary_id}>
            <p className="text-xs text-slate-400 mb-2">
              {node.tree_type} · level {node.level}
            </p>
            <p className="text-sm text-slate-800 whitespace-pre-wrap">{node.body_md}</p>
          </Card>
        ))}
        {searched && results.length === 0 && !loading && (
          <p className="text-sm text-slate-400">
            No summary yet for this scope — summaries build up as more data is ingested.
          </p>
        )}
      </div>
    </div>
  );
}
