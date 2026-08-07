import { createContext, useContext, useEffect, useState } from "react";
import { setUnauthorizedHandler } from "../lib/apiClient";

export type Session = {
  apiKey: string;
  tenantId: string;
  role: "reader" | "writer" | "admin";
};

type AuthContextValue = {
  session: Session | null;
  sessionEndedReason: string | null;
  login: (session: Session) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "neuralgram_session";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Session;
    } catch {
      return null;
    }
  });

  const [sessionEndedReason, setSessionEndedReason] = useState<string | null>(null);

  const login = (newSession: Session) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newSession));
    setSession(newSession);
    setSessionEndedReason(null);
  };

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setSessionEndedReason(null);
  };

  const logoutWithReason = (reason: string) => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setSessionEndedReason(reason);
  };

  useEffect(() => {
    setUnauthorizedHandler(() => logoutWithReason("Your session ended. Please sign in again."));
  }, []);

  return (
    <AuthContext.Provider value={{ session, sessionEndedReason, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
