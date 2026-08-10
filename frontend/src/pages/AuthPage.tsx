import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Footer } from "../components/Footer";
import { Navbar } from "../components/Navbar";
import { useAuth } from "../context/AuthContext";
import { apiClient, ApiError } from "../lib/apiClient";
import type { Session } from "../context/AuthContext";

type AuthResponse = {
  api_key: string;
  tenant_id: string;
  role: "reader" | "writer" | "admin";
};

const heroGradient = {
  background: "linear-gradient(135deg, #eef6f8 0%, #f4f9fb 40%, #eaf3f6 100%)",
};

const cardStyle = { backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" };
const headingStyle = { fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" };
const inputStyle = { borderColor: "#dfe8e9" };

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
    <div style={heroGradient} className="flex min-h-screen flex-col font-sans text-[#1a1a1a]">
      <Navbar />
      <div className="flex flex-1 items-center justify-center px-8 py-16">
        <div className="w-full max-w-sm rounded-[10px] p-8" style={cardStyle}>
          <h1 className="text-2xl mb-1" style={headingStyle}>
            {mode === "signup" ? "Create an account" : "Sign in"}
          </h1>
          <p className="text-sm mb-6" style={{ color: "#5b6a6c" }}>
            Access your Neuralgram tenant
          </p>

          {!error && sessionEndedReason && (
            <p
              className="mb-4 rounded-[10px] px-4 py-3 text-sm"
              style={{ backgroundColor: "#fff", border: "1px solid #e2e9ea", color: "#5b6a6c" }}
            >
              {sessionEndedReason}
            </p>
          )}
          {error && (
            <div className="mb-4 flex items-start justify-between rounded-[10px] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <span>{error}</span>
              <button onClick={() => setError(null)} className="ml-4 font-medium text-red-600 hover:text-red-800">
                Dismiss
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className="block text-sm font-medium mb-1" style={{ color: "#3f4d4e" }}>
                Email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-md border px-3 py-2 text-sm focus:outline-none"
                style={inputStyle}
                onFocus={(e) => (e.currentTarget.style.borderColor = "#17594f")}
                onBlur={(e) => (e.currentTarget.style.borderColor = "#dfe8e9")}
              />
            </label>
            <label className="block">
              <span className="block text-sm font-medium mb-1" style={{ color: "#3f4d4e" }}>
                Password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full rounded-md border px-3 py-2 text-sm focus:outline-none"
                style={inputStyle}
                onFocus={(e) => (e.currentTarget.style.borderColor = "#17594f")}
                onBlur={(e) => (e.currentTarget.style.borderColor = "#dfe8e9")}
              />
            </label>
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-full px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50"
              style={{ backgroundColor: "#17594f" }}
            >
              {loading ? "Please wait..." : mode === "signup" ? "Sign up" : "Sign in"}
            </button>
          </form>

          <button
            type="button"
            onClick={() => setMode(mode === "signup" ? "login" : "signup")}
            className="mt-4 text-sm hover:underline"
            style={{ color: "#17594f" }}
          >
            {mode === "signup" ? "Already have an account? Sign in" : "Need an account? Sign up"}
          </button>
        </div>
      </div>
      <Footer />
    </div>
  );
}
