import { useNavigate } from "react-router-dom";
import { Footer } from "../components/Footer";
import { Navbar } from "../components/Navbar";
import { DOCS_URL } from "../lib/links";

const STEPS = ["Ingest", "Search", "Summarize", "Connect"];

const heroGradient = {
  background: "linear-gradient(135deg, #eef6f8 0%, #f4f9fb 40%, #eaf3f6 100%)",
};

export function LandingPage() {
  const navigate = useNavigate();

  return (
    <div style={heroGradient} className="min-h-screen font-sans text-[#1a1a1a]">
      <Navbar />

      {/* Hero */}
      <section className="max-w-3xl mx-auto px-8 pt-16 pb-20 text-center">
        <h1
          className="text-5xl leading-tight mb-4"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
        >
          Give your AI agent a memory that never forgets.
        </h1>
        <p className="text-lg mb-4" style={{ color: "#4a5a5c" }}>
          An open-source context engine for chatbots and AI agents.
        </p>
        <p className="text-base max-w-xl mx-auto mb-8 leading-relaxed" style={{ color: "#5b6a6c" }}>
          Ingest conversation history, search it with real semantic understanding, and
          get AI-written summaries — plug it into any chatbot you're already building,
          in a few lines of code.
        </p>
        <button
          onClick={() => navigate("/demo")}
          className="rounded-full px-8 py-3 text-white font-medium"
          style={{ backgroundColor: "#17594f" }}
        >
          Try a Demo
        </button>
        <p className="text-sm mt-3" style={{ color: "#7a8a8c" }}>
          Or sign up free — 3 AI calls included, no credit card needed.
        </p>
      </section>

      {/* Problem it solves */}
      <section className="max-w-3xl mx-auto px-8 py-14">
        <h2
          className="text-3xl mb-4"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
        >
          Your chatbot forgets everything the moment the conversation ends.
        </h2>
        <p className="text-base leading-relaxed" style={{ color: "#5b6a6c" }}>
          Every new session starts from zero. Prior context has to be re-explained or
          re-processed at full cost, and there's no way to search "what did we already
          discuss about this" across past conversations. Neuralgram's compression and
          routing pipeline has shown up to 96.9% lower token costs than reprocessing
          raw history every time — without losing the context that actually matters.
        </p>
      </section>

      {/* How it solves it */}
      <section className="max-w-3xl mx-auto px-8 py-14">
        <h2
          className="text-3xl mb-8"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
        >
          Four steps, start to finish.
        </h2>
        <div
          className="rounded-[10px] p-6 overflow-x-auto"
          style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
        >
          <svg viewBox="0 0 620 120" width="100%" height="120" role="img" aria-label="Ingest, then Search, then Summarize, then Connect">
            {STEPS.map((label, i) => {
              const x = 10 + i * 155;
              return (
                <g key={label}>
                  {i > 0 && (
                    <line
                      x1={x - 45}
                      y1="50"
                      x2={x - 5}
                      y2="50"
                      stroke="#17594f"
                      strokeWidth="2"
                      markerEnd="url(#step-arrow)"
                    />
                  )}
                  <circle cx={x + 40} cy="50" r="26" fill={i === 0 ? "#17594f" : "#ffffff"} stroke="#17594f" strokeWidth="2" />
                  <text x={x + 40} y="55" textAnchor="middle" fontSize="14" fontWeight="700" fill={i === 0 ? "#ffffff" : "#17594f"}>
                    {i + 1}
                  </text>
                  <text x={x + 40} y="98" textAnchor="middle" fontSize="13" fontWeight="600" fill="#111">
                    {label}
                  </text>
                </g>
              );
            })}
            <defs>
              <marker id="step-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 Z" fill="#17594f" />
              </marker>
            </defs>
          </svg>
        </div>
      </section>

      {/* Demo limits */}
      <section className="max-w-3xl mx-auto px-8 py-14">
        <h2
          className="text-3xl mb-4"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
        >
          Fair-use limits, so the demo stays open for everyone.
        </h2>
        <div
          className="rounded-[10px] p-6 grid sm:grid-cols-2 gap-6"
          style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
        >
          <div>
            <p className="text-sm font-semibold mb-1" style={{ color: "#111" }}>Try a Demo (no signup)</p>
            <p className="text-sm leading-relaxed" style={{ color: "#5b6a6c" }}>
              8 requests per day per visitor, 3 messages per ingest call. Your demo
              data is private to you — other visitors never see it.
            </p>
          </div>
          <div>
            <p className="text-sm font-semibold mb-1" style={{ color: "#111" }}>Free signup account</p>
            <p className="text-sm leading-relaxed" style={{ color: "#5b6a6c" }}>
              3 AI completion calls + 3 embedding calls, lifetime, on your own private
              tenant. Search by keyword stays unlimited even after that.
            </p>
          </div>
        </div>
      </section>

      {/* Integration */}
      <section className="max-w-3xl mx-auto px-8 py-14">
        <h2
          className="text-3xl mb-4"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#111" }}
        >
          Works with the chatbot you're already building.
        </h2>
        <p className="text-base leading-relaxed mb-6" style={{ color: "#5b6a6c" }}>
          Neuralgram is a backend service, not a replacement chatbot — it's the memory
          layer underneath whatever LLM or framework you're already using.
        </p>
        <div
          className="rounded-[10px] p-6"
          style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
        >
          <svg viewBox="0 0 480 160" width="100%" height="160" role="img" aria-label="Your Chatbot connects to Neuralgram, which grounds the response sent to your LLM">
            <rect x="10" y="55" width="130" height="60" rx="10" fill="#ffffff" stroke="#dfe8e9" />
            <text x="75" y="80" textAnchor="middle" fontSize="12" fill="#111" fontWeight="600">Your Chatbot</text>
            <text x="75" y="98" textAnchor="middle" fontSize="10" fill="#7a8a8c">user asks a question</text>

            <line x1="140" y1="85" x2="180" y2="85" stroke="#17594f" strokeWidth="2" markerEnd="url(#flow-arrow)" />

            <rect x="180" y="45" width="140" height="80" rx="10" fill="#17594f" />
            <text x="250" y="78" textAnchor="middle" fontSize="12" fill="#ffffff" fontWeight="600">◆ Neuralgram</text>
            <text x="250" y="96" textAnchor="middle" fontSize="10" fill="#dfece8">finds relevant memory</text>

            <line x1="320" y1="85" x2="360" y2="85" stroke="#17594f" strokeWidth="2" markerEnd="url(#flow-arrow)" />

            <rect x="360" y="55" width="115" height="60" rx="10" fill="#ffffff" stroke="#dfe8e9" />
            <text x="417" y="80" textAnchor="middle" fontSize="12" fill="#111" fontWeight="600">Your LLM</text>
            <text x="417" y="98" textAnchor="middle" fontSize="10" fill="#7a8a8c">answers, grounded</text>

            <defs>
              <marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 Z" fill="#17594f" />
              </marker>
            </defs>
          </svg>
        </div>
        <a
          href={DOCS_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-block mt-6 text-sm hover:underline"
          style={{ color: "#17594f" }}
        >
          Read the full integration guide →
        </a>
      </section>

      <Footer />
    </div>
  );
}
