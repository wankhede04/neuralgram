import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthPage } from "./pages/AuthPage";
import { DashboardLayout } from "./pages/DashboardLayout";
import { IngestPage } from "./pages/IngestPage";
import { AuthProvider } from "./context/AuthContext";

function Placeholder({ name }: { name: string }) {
  return <p className="text-slate-500">{name} page — coming in a later task.</p>;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AuthPage />} />
          <Route element={<DashboardLayout />}>
            <Route path="/ingest" element={<IngestPage />} />
            <Route path="/search" element={<Placeholder name="Search" />} />
            <Route path="/summaries" element={<Placeholder name="Summaries" />} />
            <Route path="/audit" element={<Placeholder name="Audit" />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
