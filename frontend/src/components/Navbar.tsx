import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { DOCS_URL, GITHUB_URL } from "../lib/links";

const DASHBOARD_NAV_ITEMS = [
  { to: "/ingest", label: "Ingest" },
  { to: "/search", label: "Search" },
  { to: "/summaries", label: "Summaries" },
];

export function Navbar() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();

  const navItems =
    session?.role === "admin"
      ? [...DASHBOARD_NAV_ITEMS, { to: "/audit", label: "Audit" }]
      : DASHBOARD_NAV_ITEMS;

  return (
    <nav className="border-b" style={{ borderColor: "#dfe8e9", backgroundColor: "#fff" }}>
      <div className="flex items-center justify-between gap-3 px-4 sm:px-8 py-3 sm:py-4 max-w-5xl mx-auto flex-wrap">
        <Link
          to="/"
          className="text-lg sm:text-2xl italic whitespace-nowrap"
          style={{ fontFamily: "Georgia, 'Times New Roman', serif", color: "#17594f" }}
        >
          ◆ Neuralgram
        </Link>
        <div className="flex items-center gap-2 sm:gap-6 text-xs sm:text-sm flex-wrap justify-end">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            GitHub
          </a>
          <a href={DOCS_URL} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "#17594f" }}>
            Docs
          </a>

          {session ? (
            <>
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    isActive ? "font-medium" : "hover:underline"
                  }
                  style={({ isActive }) => ({ color: isActive ? "#111" : "#5b6a6c" })}
                >
                  {item.label}
                </NavLink>
              ))}
              <span className="hidden sm:inline text-xs" style={{ color: "#9aa5a6" }}>
                {session.apiKey.slice(0, 8)}... ({session.role})
              </span>
              <button onClick={logout} className="hover:underline" style={{ color: "#5b6a6c" }}>
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="hover:underline whitespace-nowrap" style={{ color: "#17594f" }}>
                Login
              </Link>
              <button
                onClick={() => navigate("/demo")}
                className="rounded-full px-3 sm:px-5 py-1.5 sm:py-2 text-white text-xs sm:text-sm whitespace-nowrap"
                style={{ backgroundColor: "#17594f" }}
              >
                Try a Demo
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
