import { GITHUB_URL, DOCS_URL, LICENSE_URL } from "../lib/links";

export function Footer() {
  return (
    <footer className="border-t" style={{ borderColor: "#dfe8e9" }}>
      <div className="max-w-5xl mx-auto px-8 py-8 text-sm" style={{ color: "#7a8a8c" }}>
        <div className="flex gap-6 mb-3">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            GitHub
          </a>
          <a href={LICENSE_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            License (Elastic License 2.0)
          </a>
          <a href={DOCS_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            Integration Guide
          </a>
        </div>
        <p>© 2026 Neuralgram. Source available under the Elastic License 2.0.</p>
      </div>
    </footer>
  );
}
