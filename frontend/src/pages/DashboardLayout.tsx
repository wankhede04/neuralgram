import { Navigate, Outlet } from "react-router-dom";
import { Footer } from "../components/Footer";
import { Navbar } from "../components/Navbar";
import { useAuth } from "../context/AuthContext";

const heroGradient = {
  background: "linear-gradient(135deg, #eef6f8 0%, #f4f9fb 40%, #eaf3f6 100%)",
};

export function DashboardLayout() {
  const { session } = useAuth();

  if (!session) {
    return <Navigate to="/" replace />;
  }

  return (
    <div style={heroGradient} className="flex min-h-screen flex-col">
      <Navbar />
      <main className="mx-auto max-w-4xl w-full flex-1 px-6 py-8">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
