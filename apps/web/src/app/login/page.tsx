"use client";

import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { Logo } from "@/components/logo";
import { homeFor, useAuth } from "@/components/providers";
import { Button, Card, Input, Label, PageLoader, Select } from "@/components/ui";
import { api, type User } from "@/lib/api";
import { IS_DEMO } from "@/lib/mode";
import type { Meta } from "@/lib/types";

const ROLE_LABEL: Record<string, string> = {
  merchant: "Demo merchant · apply and track onboarding",
  operator: "Demo operator · review queue and exceptions",
  admin: "Demo admin · policy and scenario lab",
};

function LoginForm() {
  const { signIn } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [account, setAccount] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), enabled: IS_DEMO });
  const accounts = meta.data?.demo_accounts ?? [];

  function pick(role: string) {
    setAccount(role);
    const a = accounts.find((x) => x.role === role);
    setEmail(a?.email ?? "");
    setPassword(a?.password ?? "");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ access_token: string; user: User }>("/auth/login", { method: "POST", json: { email, password } });
      signIn(r.access_token, r.user);
      router.replace(next && next.startsWith("/") ? next : homeFor(r.user.role));
    } catch (err) {
      toast.error((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 py-12">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex justify-center">
          <Logo />
        </Link>
        <Card className="p-6">
          <h1 className="text-lg font-semibold text-zinc-900">Sign in</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {IS_DEMO ? "Choose a demo account to fill in its details, or use your own." : "Welcome back."}
          </p>
          <form onSubmit={submit} className="mt-5 space-y-4">
            {IS_DEMO && (
              <div>
                <Label htmlFor="account">Demo account</Label>
                <Select id="account" value={account} onChange={(e) => pick(e.target.value)} disabled={!accounts.length}>
                  <option value="">{meta.isLoading ? "Loading accounts…" : "Choose an account…"}</option>
                  {accounts.map((a) => (
                    <option key={a.role} value={a.role}>
                      {ROLE_LABEL[a.role] ?? a.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <Button type="submit" className="w-full" loading={busy} disabled={busy}>
              Sign in
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-zinc-500">
            New merchant?{" "}
            <Link href="/signup/" className="font-medium text-maple-700 hover:underline">
              Create an account
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<PageLoader />}>
      <LoginForm />
    </Suspense>
  );
}
