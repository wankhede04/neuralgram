import { useState } from "react";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { ErrorBanner } from "../components/ErrorBanner";
import { Input } from "../components/Input";
import { PageHeader } from "../components/PageHeader";
import { Select } from "../components/Select";
import { apiClient, ApiError } from "../lib/apiClient";

type Chunk = {
  chunk_id: string;
  source_id: string;
  content_md: string;
  provenance: { author: string; timestamp: string };
  rank?: number;
};

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [limit, setLimit] = useState("10");
  const [results, setResults] = useState<Chunk[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setSearched(true);
    try {
      const response = await apiClient.get<Chunk[]>("/memory/search", {
        q: query,
        mode,
        limit,
      });
      setResults(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader title="Search" subtitle="Query your ingested memory" />
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      <Card className="mb-6">
        <form onSubmit={handleSubmit} className="flex items-end gap-3">
          <div className="flex-1">
            <Input label="Query" value={query} onChange={setQuery} required />
          </div>
          <div className="w-40">
            <Select
              label="Mode"
              value={mode}
              onChange={setMode}
              options={[
                { value: "hybrid", label: "Hybrid" },
                { value: "semantic", label: "Semantic" },
                { value: "keyword", label: "Keyword" },
              ]}
            />
          </div>
          <div className="w-24">
            <Input label="Limit" type="number" value={limit} onChange={setLimit} />
          </div>
          <Button type="submit" disabled={loading}>
            {loading ? "Searching..." : "Search"}
          </Button>
        </form>
      </Card>
      <div className="space-y-3">
        {results.map((chunk) => (
          <Card key={chunk.chunk_id}>
            <p className="text-sm text-slate-800 whitespace-pre-wrap">{chunk.content_md}</p>
            <p className="mt-2 text-xs text-slate-400">
              {chunk.provenance.author} · {chunk.source_id} · {chunk.provenance.timestamp}
              {chunk.rank !== undefined && ` · rank ${chunk.rank.toFixed(4)}`}
            </p>
          </Card>
        ))}
        {searched && results.length === 0 && !loading && (
          <p className="text-sm text-slate-400">No results yet — try a search above.</p>
        )}
      </div>
    </div>
  );
}
