"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { api, clearSession, loadUser, saveSession, type User } from "@/lib/api";

type AuthState = {
  user: User | null;
  ready: boolean;
  signIn: (token: string, user: User) => void;
  signOut: () => void;
  demo: (role: User["role"]) => Promise<User>;
};

const AuthContext = createContext<AuthState | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Session lives in localStorage, so it can only be read in the browser after hydration.
    setUser(loadUser()); // eslint-disable-line react-hooks/set-state-in-effect
    setReady(true);
  }, []);

  const signIn = useCallback((token: string, u: User) => {
    saveSession(token, u);
    setUser(u);
  }, []);

  const signOut = useCallback(() => {
    clearSession();
    setUser(null);
  }, []);

  const demo = useCallback(
    async (role: User["role"]) => {
      const r = await api<{ access_token: string; user: User }>("/auth/demo", { method: "POST", json: { role } });
      signIn(r.access_token, r.user);
      return r.user;
    },
    [signIn],
  );

  return <AuthContext.Provider value={{ user, ready, signIn, signOut, demo }}>{children}</AuthContext.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 1000 } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}

export function homeFor(role: User["role"]) {
  return role === "merchant" ? "/merchant/" : role === "admin" ? "/ops/" : "/ops/";
}
