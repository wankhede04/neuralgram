import { Link, useNavigate } from "react-router-dom";

const GITHUB_URL = "https://github.com/wankhede04/neuralgram";
const DOCS_URL = "https://github.com/wankhede04/neuralgram/blob/main/docs/integration-guide.md";
const LICENSE_URL = "https://github.com/wankhede04/neuralgram/blob/main/LICENSE";

const STEPS = [
  { title: "Ingest", body: "Send conversation history (Slack-shaped export today) via one API call; it's chunked, compressed, and stored per-tenant." },
  { title: "Search", body: "Query it back with keyword, semantic, or hybrid search — real embeddings, not string matching." },
  { title: "Summarize", body: "As data accumulates, Neuralgram automatically rolls it up into AI-written summaries — per conversation, per topic, per day." },
  { title: "Connect", body: "Call it from your own chatbot's backend before each LLM call, so responses are grounded in what was actually said before." },
];

const heroGradient = {
  background: "linear-gradient(135deg, #eef6f8 0%, #f4f9fb 40%, #eaf3f6 100%)",
};

export function LandingPage() {
  const navigate = useNavigate();

  return (
    <div style={heroGradient} className="min-h-screen font-sans text-[#1a1a1a]">
      {/* Navbar */}
      <nav className="flex items-center justify-between px-8 py-6 max-w-5xl mx-auto">
        <span className="text-2xl italic" style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#17594f" }}>
          ◆ Neuralgram
        </span>
        <div className="flex items-center gap-6 text-sm">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            GitHub
          </a>
          <a href={DOCS_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            Docs
          </a>
          <button
            onClick={() => navigate("/login")}
            className="rounded-full px-5 py-2 text-white text-sm"
            style={{ backgroundColor: "#17594f" }}
          >
            Try a Demo
          </button>
        </div>
      </nav>

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
          onClick={() => navigate("/login")}
          className="rounded-full px-8 py-3 text-white font-medium"
          style={{ backgroundColor: "#17594f" }}
        >
          Try a Demo
        </button>
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {STEPS.map((step, i) => (
            <div
              key={step.title}
              className="rounded-[10px] p-5"
              style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
            >
              <div className="text-sm font-semibold mb-1" style={{ color: "#17594f" }}>
                {i + 1}. {step.title}
              </div>
              <div className="text-sm" style={{ color: "#5b6a6c" }}>
                {step.body}
              </div>
            </div>
          ))}
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div
            className="rounded-[10px] p-5"
            style={{ backgroundColor: "#fbfdfd", border: "1px solid #dfe8e9" }}
          >
            <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: "#9aa5a6" }}>
              Without Neuralgram
            </div>
            <p className="text-sm leading-relaxed" style={{ color: "#5b6a6c" }}>
              Your chatbot starts every session from zero. It can't recall what a
              customer said last week, so it either asks them to repeat themselves
              or answers with a generic, ungrounded guess.
            </p>
          </div>
          <div
            className="rounded-[10px] p-5"
            style={{ backgroundColor: "#fbfdfd", border: `1px solid #17594f` }}
          >
            <div className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: "#17594f" }}>
              With Neuralgram
            </div>
            <p className="text-sm leading-relaxed" style={{ color: "#3f4d4e" }}>
              Before replying, your chatbot asks Neuralgram what's relevant from
              everything said before — then answers grounded in the real history,
              not a guess.
            </p>
          </div>
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

      {/* Footer */}
      <footer className="max-w-3xl mx-auto px-8 py-10 text-sm" style={{ color: "#7a8a8c" }}>
        <div className="flex gap-6 mb-3">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            GitHub
          </a>
          <a href={LICENSE_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            License (Elastic License 2.0)
          </a>
          <Link to="/login" className="hover:underline" style={{ color: "#17594f" }}>
            Try a Demo
          </Link>
        </div>
        <p>© 2026 Neuralgram. Source available under the Elastic License 2.0.</p>
      </footer>
    </div>
  );
}
