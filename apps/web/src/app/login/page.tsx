"use client";

import { ShieldCheck, Store, UserCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { Logo } from "@/components/logo";
import { homeFor, useAuth } from "@/components/providers";
import { Button, Card, Input, Label, PageLoader } from "@/components/ui";
import { api, type User } from "@/lib/api";
import { IS_DEMO } from "@/lib/mode";

function LoginForm() {
  const { signIn, demo } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  function done(u: User) {
    router.replace(next && next.startsWith("/") ? next : homeFor(u.role));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy("form");
    try {
      const r = await api<{ access_token: string; user: User }>("/auth/login", { method: "POST", json: { email, password } });
      signIn(r.access_token, r.user);
      done(r.user);
    } catch (err) {
      toast.error((err as Error).message);
      setBusy(null);
    }
  }

  async function quick(role: User["role"]) {
    setBusy(role);
    try {
      const u = await demo(role);
      router.replace(homeFor(u.role));
    } catch (err) {
      toast.error((err as Error).message);
      setBusy(null);
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
          <p className="mt-1 text-sm text-zinc-500">{IS_DEMO ? "Pick a demo account or use your own." : "Welcome back."}</p>
          {IS_DEMO && (
          <>
          <div className="mt-5 grid gap-2">
            {[
              { role: "merchant" as const, icon: <Store className="h-4 w-4" />, label: "Demo merchant", sub: "Apply and track onboarding" },
              { role: "operator" as const, icon: <UserCheck className="h-4 w-4" />, label: "Demo operator", sub: "Review queue and exceptions" },
              { role: "admin" as const, icon: <ShieldCheck className="h-4 w-4" />, label: "Demo admin", sub: "Policy and scenario lab" },
            ].map((d) => (
              <button
                key={d.role}
                onClick={() => quick(d.role)}
                disabled={!!busy}
                className="flex items-center gap-3 rounded-lg border border-zinc-200 px-4 py-3 text-left transition-colors hover:border-maple-300 hover:bg-maple-50/40 disabled:opacity-60"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-100 text-zinc-600">{d.icon}</span>
                <span>
                  <span className="block text-sm font-medium text-zinc-900">{d.label}</span>
                  <span className="block text-xs text-zinc-500">{d.sub}</span>
                </span>
                {busy === d.role && <span className="ml-auto text-xs text-zinc-400">Signing in…</span>}
              </button>
            ))}
          </div>
          <div className="my-6 flex items-center gap-3 text-xs text-zinc-400">
            <div className="h-px flex-1 bg-zinc-200" /> or <div className="h-px flex-1 bg-zinc-200" />
          </div>
          </>
          )}
          <form onSubmit={submit} className={IS_DEMO ? "space-y-4" : "mt-5 space-y-4"}>
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <Button type="submit" className="w-full" loading={busy === "form"} disabled={!!busy}>
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
