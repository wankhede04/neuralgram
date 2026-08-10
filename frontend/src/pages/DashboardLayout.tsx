import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_ITEMS = [
  { to: "/ingest", label: "Ingest" },
  { to: "/search", label: "Search" },
  { to: "/summaries", label: "Summaries" },
];

export function DashboardLayout() {
  const { session, logout } = useAuth();

  if (!session) {
    return <Navigate to="/" replace />;
  }

  const navItems =
    session.role === "admin" ? [...NAV_ITEMS, { to: "/audit", label: "Audit" }] : NAV_ITEMS;

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <span className="font-semibold text-slate-900">Neuralgram</span>
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `text-sm font-medium ${isActive ? "text-slate-900" : "text-slate-500 hover:text-slate-700"}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-400">
              {session.apiKey.slice(0, 8)}... ({session.role})
            </span>
            <button onClick={logout} className="text-sm text-slate-500 hover:text-slate-700">
              Logout
            </button>
          </div>
        </div>
      </nav>
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
