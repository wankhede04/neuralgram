import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthPage } from "./pages/AuthPage";
import { DashboardLayout } from "./pages/DashboardLayout";
import { IngestPage } from "./pages/IngestPage";
import { SearchPage } from "./pages/SearchPage";
import { SummariesPage } from "./pages/SummariesPage";
import { AuditPage } from "./pages/AuditPage";
import { AuthProvider } from "./context/AuthContext";
import { useAuth } from "./context/AuthContext";

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  if (session?.role !== "admin") {
    return <p className="text-slate-500">You don't have access to this page.</p>;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AuthPage />} />
          <Route element={<DashboardLayout />}>
            <Route path="/ingest" element={<IngestPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/summaries" element={<SummariesPage />} />
            <Route
              path="/audit"
              element={
                <RequireAdmin>
                  <AuditPage />
                </RequireAdmin>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
