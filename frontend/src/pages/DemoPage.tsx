import { useState } from "react";
import { Link } from "react-router-dom";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const DEMO_API_KEY = import.meta.env.VITE_DEMO_API_KEY || "";

const heroGradient = {
  background: "linear-gradient(135deg, #eef6f8 0%, #f4f9fb 40%, #eaf3f6 100%)",
};

const cardStyle = { backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" };
const headingStyle = { fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" };

type Message = { user: string; text: string };
type Chunk = { chunk_id: string; source_id: string; content_md: string };
type SummaryNode = { summary_id: string; tree_type: string; scope_id: string; level: number; body_md: string };

async function demoFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "x-api-key": DEMO_API_KEY, ...init.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function IngestDemo() {
  const [sourceId, setSourceId] = useState("");
  const [messages, setMessages] = useState<Message[]>([{ user: "", text: "" }]);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const updateMessage = (index: number, field: keyof Message, value: string) => {
    setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const addRow = () => {
    if (messages.length < 3) setMessages((prev) => [...prev, { user: "", text: "" }]);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    try {
      const now = Date.now() / 1000;
      const response = await demoFetch<{ documents: number; chunks_inserted: number }>(
        "/memory/ingest",
        {
          method: "POST",
          body: JSON.stringify({
            source_id: sourceId || "demo-playground",
            source_type: "slack",
            payload: {
              messages: messages
                .filter((m) => m.text.trim())
                .map((m, i) => ({ user: m.user || "you", text: m.text, ts: (now + i).toFixed(6) })),
            },
          }),
        }
      );
      setResult(`Ingested ${response.documents} document(s), ${response.chunks_inserted} chunk(s) inserted.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed.");
    }
  };

  return (
    <div className="rounded-[10px] p-5" style={cardStyle}>
      <h3 className="text-lg font-semibold mb-3">Ingest (max 3 messages)</h3>
      <form onSubmit={submit} className="space-y-3">
        <input
          className="w-full rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "#dfe8e9" }}
          placeholder="Source ID (optional)"
          value={sourceId}
          onChange={(e) => setSourceId(e.target.value)}
        />
        {messages.map((m, i) => (
          <div key={i} className="flex gap-2">
            <input
              className="w-28 rounded-md border px-3 py-2 text-sm"
              style={{ borderColor: "#dfe8e9" }}
              placeholder="User"
              value={m.user}
              onChange={(e) => updateMessage(i, "user", e.target.value)}
            />
            <input
              className="flex-1 rounded-md border px-3 py-2 text-sm"
              style={{ borderColor: "#dfe8e9" }}
              placeholder="Message"
              value={m.text}
              onChange={(e) => updateMessage(i, "text", e.target.value)}
            />
          </div>
        ))}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={addRow}
            disabled={messages.length >= 3}
            className="rounded-full px-4 py-2 text-sm border disabled:opacity-40"
            style={{ borderColor: "#dfe8e9" }}
          >
            + Add message ({messages.length}/3)
          </button>
          <button type="submit" className="rounded-full px-4 py-2 text-sm text-white" style={{ backgroundColor: "#17594f" }}>
            Ingest
          </button>
        </div>
      </form>
      {result && <p className="text-sm mt-3" style={{ color: "#17594f" }}>{result}</p>}
      {error && <p className="text-sm mt-3 text-red-600">{error}</p>}
    </div>
  );
}

function SearchDemo() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Chunk[]>([]);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const params = new URLSearchParams({ q: query, mode: "hybrid", limit: "5" });
      const response = await demoFetch<Chunk[]>(`/memory/search?${params.toString()}`);
      setResults(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    }
  };

  return (
    <div className="rounded-[10px] p-5" style={cardStyle}>
      <h3 className="text-lg font-semibold mb-3">Search</h3>
      <form onSubmit={submit} className="flex gap-2">
        <input
          className="flex-1 rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "#dfe8e9" }}
          placeholder="Query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="rounded-full px-4 py-2 text-sm text-white" style={{ backgroundColor: "#17594f" }}>
          Search
        </button>
      </form>
      {error && <p className="text-sm mt-3 text-red-600">{error}</p>}
      <div className="space-y-2 mt-3">
        {results.map((chunk) => (
          <div key={chunk.chunk_id} className="text-sm rounded-md p-3" style={{ backgroundColor: "#fff", border: "1px solid #e2e9ea" }}>
            {chunk.content_md}
          </div>
        ))}
      </div>
    </div>
  );
}

function SummariesDemo() {
  const [scopeId, setScopeId] = useState("");
  const [nodes, setNodes] = useState<SummaryNode[]>([]);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const params = new URLSearchParams({ tree: "source", scope_id: scopeId });
      const response = await demoFetch<SummaryNode[]>(`/memory/summaries?${params.toString()}`);
      setNodes(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed.");
    }
  };

  return (
    <div className="rounded-[10px] p-5" style={cardStyle}>
      <h3 className="text-lg font-semibold mb-3">Summaries (source tree)</h3>
      <form onSubmit={submit} className="flex gap-2">
        <input
          className="flex-1 rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "#dfe8e9" }}
          placeholder="Scope ID (the Source ID you ingested)"
          value={scopeId}
          onChange={(e) => setScopeId(e.target.value)}
        />
        <button type="submit" className="rounded-full px-4 py-2 text-sm text-white" style={{ backgroundColor: "#17594f" }}>
          Look up
        </button>
      </form>
      {error && <p className="text-sm mt-3 text-red-600">{error}</p>}
      <div className="space-y-2 mt-3">
        {nodes.length === 0 && <p className="text-sm" style={{ color: "#9aa5a6" }}>No summary yet — summaries build up after enough messages accumulate.</p>}
        {nodes.map((node) => (
          <div key={node.summary_id} className="text-sm rounded-md p-3" style={{ backgroundColor: "#fff", border: "1px solid #e2e9ea" }}>
            {node.body_md}
          </div>
        ))}
      </div>
    </div>
  );
}

export function DemoPage() {
  return (
    <div style={heroGradient} className="min-h-screen font-sans text-[#1a1a1a]">
      <div className="max-w-3xl mx-auto px-8 py-12">
        <h1 className="text-4xl mb-3" style={headingStyle}>Try it yourself</h1>
        <p className="text-base mb-10" style={{ color: "#5b6a6c" }}>
          No signup needed. This playground uses a shared demo tenant, so ingest is
          capped at 3 messages per call — search and summaries are wide open.
        </p>

        <div className="rounded-[10px] p-6 mb-10" style={cardStyle}>
          <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: "#9aa5a6" }}>
            Example
          </div>
          <p className="text-sm mb-2" style={{ color: "#5b6a6c" }}>
            <strong>Ingested:</strong> "We discussed the Q3 roadmap yesterday and agreed to ship by end of month."
          </p>
          <p className="text-sm mb-2" style={{ color: "#5b6a6c" }}>
            <strong>Search:</strong> "what did we agree on?"
          </p>
          <p className="text-sm" style={{ color: "#3f4d4e" }}>
            <strong>Answer:</strong> The team agreed to ship the Q3 roadmap by end of month.
          </p>
        </div>

        <div className="space-y-6">
          <IngestDemo />
          <SearchDemo />
          <SummariesDemo />
        </div>

        <p className="text-sm mt-10" style={{ color: "#7a8a8c" }}>
          Want your own tenant with no limits?{" "}
          <Link to="/login" className="hover:underline" style={{ color: "#17594f" }}>
            Sign up →
          </Link>
        </p>
      </div>
    </div>
  );
}
