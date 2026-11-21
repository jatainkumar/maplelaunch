"use client";

import { ArrowRight, Bot, CheckCircle2, FileSearch, Fingerprint, Loader2, Radio, ShieldCheck, Store, UserCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Logo } from "@/components/logo";
import { homeFor, useAuth } from "@/components/providers";
import { Button } from "@/components/ui";
import type { User } from "@/lib/api";
import { IS_DEMO } from "@/lib/mode";

const FEATURES = [
  { icon: <FileSearch className="h-5 w-5" />, title: "Reads documents for you", body: "Upload PAN, GST and bank proof. Multimodal AI fills the form and shows how sure it is about every field." },
  { icon: <Radio className="h-5 w-5" />, title: "Resilient verification", body: "PAN, GST, penny-drop and risk checks run in parallel. Duplicate, late and out-of-order callbacks are handled safely." },
  { icon: <Bot className="h-5 w-5" />, title: "AI decides routine cases", body: "An agent approves clean applications inside hard policy guardrails, and it can never reject on its own." },
  { icon: <UserCheck className="h-5 w-5" />, title: "Humans where it matters", body: "Risky, uncertain or duplicate cases go to reviewers with an AI briefing, side-by-side evidence and one-click actions." },
  { icon: <Fingerprint className="h-5 w-5" />, title: "Private by design", body: "Identifiers are encrypted at rest, masked everywhere, and every reveal is audited in a tamper-evident log." },
  { icon: <ShieldCheck className="h-5 w-5" />, title: "Durable workflow", body: "A LangGraph state machine with Postgres checkpoints survives restarts, retries and provider outages." },
];

const STEPS = [
  ["Documents read", "PASSED"],
  ["PAN verified", "PASSED"],
  ["GST verified", "PASSED"],
  ["Bank penny-drop", "PENDING"],
  ["Risk assessment", "PENDING"],
];

export default function Landing() {
  const { user, demo } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  async function go(role: User["role"], to?: string) {
    setBusy(role);
    try {
      const u = await demo(role);
      router.push(to ?? homeFor(u.role));
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        {user ? (
          <Link href={homeFor(user.role)}>
            <Button variant="outline" size="sm">
              Open dashboard <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        ) : (
          <Link href="/login/" className="text-sm font-medium text-zinc-600 hover:text-zinc-900">
            Sign in
          </Link>
        )}
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-16 pt-10 lg:grid-cols-2 lg:pt-16">
        <div className="animate-fade-in">
          <span className="inline-flex items-center gap-2 rounded-full bg-maple-50 px-3 py-1 text-xs font-medium text-maple-700 ring-1 ring-maple-200">
            Autonomous merchant onboarding
          </span>
          <h1 className="mt-5 text-4xl font-semibold leading-[1.1] tracking-tight text-zinc-900 sm:text-5xl">
            From application to <span className="text-maple-600">live merchant</span> in minutes.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-zinc-600">
            MapleLaunch reads documents, coordinates identity, tax, bank and risk checks, handles every exception, and
            only asks a human when it genuinely needs one.
          </p>
          {IS_DEMO ? (
            <>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button size="lg" onClick={() => go("merchant", "/merchant/apply/")} loading={busy === "merchant"}>
                  <Store className="h-4 w-4" /> Apply as a merchant
                </Button>
                <Button size="lg" variant="outline" onClick={() => go("operator")} loading={busy === "operator"}>
                  <UserCheck className="h-4 w-4" /> Open the ops console
                </Button>
              </div>
              <p className="mt-4 text-sm text-zinc-500">
                One-click demo accounts, or{" "}
                <button onClick={() => go("admin")} className="font-medium text-zinc-700 underline-offset-4 hover:underline">
                  sign in as admin
                </button>{" "}
                to edit policy and run failure scenarios.
              </p>
            </>
          ) : (
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/signup/">
                <Button size="lg">
                  <Store className="h-4 w-4" /> Apply as a merchant
                </Button>
              </Link>
              <Link href="/login/">
                <Button size="lg" variant="outline">
                  Sign in <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          )}
        </div>

        <div className="animate-fade-in rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl shadow-zinc-200/50">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-medium uppercase tracking-wide text-zinc-400">ML-7Q2KXP</div>
              <div className="mt-1 font-semibold text-zinc-900">Kumar Chai Corner</div>
            </div>
            <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 ring-1 ring-sky-200">Verifying</span>
          </div>
          <ol className="mt-6 space-y-4">
            {STEPS.map(([label, s]) => (
              <li key={label} className="flex items-center gap-3">
                {s === "PASSED" ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                ) : (
                  <Loader2 className="h-5 w-5 animate-spin text-sky-500" />
                )}
                <span className="text-sm text-zinc-700">{label}</span>
                <span className="ml-auto text-xs text-zinc-400">{s === "PASSED" ? "callback received" : "waiting for provider"}</span>
              </li>
            ))}
          </ol>
          <div className="mt-6 rounded-lg bg-zinc-50 p-3 text-xs leading-relaxed text-zinc-600">
            <span className="font-medium text-zinc-800">Agent:</span> PAN and GST passed. Waiting for the penny-drop and
            risk callbacks before deciding. Auto-approval allowed if risk ≤ 30.
          </div>
        </div>
      </section>

      <section className="border-t border-zinc-200 bg-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-6 py-16 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title}>
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-maple-50 text-maple-600">{f.icon}</div>
              <h3 className="mt-4 font-semibold text-zinc-900">{f.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-zinc-600">{f.body}</p>
            </div>
          ))}
        </div>
      </section>
      <footer className="border-t border-zinc-200 py-8 text-center text-xs text-zinc-400">
        MapleLaunch · Jatain Kumar · IIT KGP
      </footer>
    </div>
  );
}
