import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { ErrorBanner } from "../components/ErrorBanner";
import { Footer } from "../components/Footer";
import { Input } from "../components/Input";
import { Navbar } from "../components/Navbar";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../context/AuthContext";
import { apiClient, ApiError } from "../lib/apiClient";
import type { Session } from "../context/AuthContext";

type AuthResponse = {
  api_key: string;
  tenant_id: string;
  role: "reader" | "writer" | "admin";
};

export function AuthPage() {
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const { login, sessionEndedReason } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const path = mode === "signup" ? "/auth/signup" : "/auth/login";
      const response = await apiClient.post<AuthResponse>(path, { email, password });
      const session: Session = {
        apiKey: response.api_key,
        tenantId: response.tenant_id,
        role: response.role,
      };
      login(session);
      navigate("/ingest");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <Navbar />
      <div className="flex flex-1 items-center justify-center py-16">
        <Card className="w-full max-w-sm">
          <PageHeader
            title={mode === "signup" ? "Create an account" : "Sign in"}
            subtitle="Access your Neuralgram tenant"
          />
          {!error && sessionEndedReason && (
            <p className="mb-4 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              {sessionEndedReason}
            </p>
          )}
          {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input label="Email" type="email" value={email} onChange={setEmail} required />
            <Input
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              required
            />
            <Button type="submit" disabled={loading}>
              {loading ? "Please wait..." : mode === "signup" ? "Sign up" : "Sign in"}
            </Button>
          </form>
          <button
            type="button"
            onClick={() => setMode(mode === "signup" ? "login" : "signup")}
            className="mt-4 text-sm text-slate-500 hover:text-slate-700"
          >
            {mode === "signup" ? "Already have an account? Sign in" : "Need an account? Sign up"}
          </button>
        </Card>
      </div>
      <Footer />
    </div>
  );
}
