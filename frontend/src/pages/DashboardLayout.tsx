import { Navigate, Outlet } from "react-router-dom";
import { Footer } from "../components/Footer";
import { Navbar } from "../components/Navbar";
import { useAuth } from "../context/AuthContext";

export function DashboardLayout() {
  const { session } = useAuth();

  if (!session) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <Navbar />
      <main className="mx-auto max-w-4xl w-full flex-1 px-6 py-8">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
