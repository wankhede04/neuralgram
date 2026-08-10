import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LandingPage } from "./pages/LandingPage";
import { AuthPage } from "./pages/AuthPage";
import { DashboardLayout } from "./pages/DashboardLayout";
import { IngestPage } from "./pages/IngestPage";
import { SearchPage } from "./pages/SearchPage";
import { SummariesPage } from "./pages/SummariesPage";
import { AuditPage } from "./pages/AuditPage";
import { AuthProvider } from "./context/AuthContext";
import { useAuth } from "./context/AuthContext";
import { Card } from "./components/Card";
import { PageHeader } from "./components/PageHeader";

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  if (session?.role !== "admin") {
    return (
      <Card>
        <PageHeader title="Access denied" subtitle="You don't have access to this page." />
      </Card>
    );
  }
  return <>{children}</>;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<AuthPage />} />
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
