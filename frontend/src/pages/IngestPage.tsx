import { useState } from "react";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { ErrorBanner } from "../components/ErrorBanner";
import { Input } from "../components/Input";
import { PageHeader } from "../components/PageHeader";
import { apiClient, ApiError } from "../lib/apiClient";

type Message = { user: string; text: string };

type IngestResponse = {
  documents: number;
  chunks_inserted: number;
  chunks_skipped: number;
};

export function IngestPage() {
  const [sourceId, setSourceId] = useState("");
  const [messages, setMessages] = useState<Message[]>([{ user: "", text: "" }]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const updateMessage = (index: number, field: keyof Message, value: string) => {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m))
    );
  };

  const addMessageRow = () => setMessages((prev) => [...prev, { user: "", text: "" }]);

  const removeMessageRow = (index: number) =>
    setMessages((prev) => prev.filter((_, i) => i !== index));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const now = Date.now() / 1000;
      const payload = {
        source_id: sourceId,
        source_type: "slack",
        payload: {
          messages: messages
            .filter((m) => m.text.trim())
            .map((m, i) => ({
              user: m.user || "anonymous",
              text: m.text,
              ts: (now + i).toFixed(6),
            })),
        },
      };
      const response = await apiClient.post<IngestResponse>("/memory/ingest", payload);
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ingest failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Ingest"
        subtitle="Add conversation history for search and summarization"
      />
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {result && (
        <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Ingested {result.documents} document(s): {result.chunks_inserted} chunk(s) inserted,{" "}
          {result.chunks_skipped} skipped.
        </div>
      )}
      <Card>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input label="Source ID" value={sourceId} onChange={setSourceId} required />
          <div className="space-y-3">
            {messages.map((message, index) => (
              <div key={index} className="flex gap-2">
                <div className="w-32">
                  <Input
                    label="User"
                    value={message.user}
                    onChange={(value) => updateMessage(index, "user", value)}
                  />
                </div>
                <div className="flex-1">
                  <Input
                    label="Message"
                    value={message.text}
                    onChange={(value) => updateMessage(index, "text", value)}
                  />
                </div>
                {messages.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeMessageRow(index)}
                    className="self-end px-2 py-2 text-sm text-slate-400 hover:text-red-600"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <Button type="button" variant="secondary" onClick={addMessageRow}>
            + Add message
          </Button>
          <div>
            <Button type="submit" disabled={loading}>
              {loading ? "Ingesting..." : "Ingest"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
