"use client";

import { BadgeCheck, Building2, Check, FileText, Fingerprint, Landmark, ScanLine, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/format";

// A looping, illustrative story of one onboarding: read a document -> verify in parallel -> go live.
const LOOP_MS = 9500;
const READ_END = 2800;
const VERIFY_START = 3000;
const LIVE_AT = 6200;
const FIRST_FRAME = LIVE_AT + 1500;

const FIELDS = [
  { at: 700, label: "Name", value: "Ravi Kumar" },
  { at: 1300, label: "PAN", value: "BQXPK••••M" },
  { at: 1900, label: "GSTIN", value: "29BQXPK••••1ZY" },
];

const TRACKS: { label: string; icon: ReactNode; ms: number }[] = [
  { label: "Identity", icon: <Fingerprint className="h-3.5 w-3.5" />, ms: 1300 },
  { label: "Tax registration", icon: <FileText className="h-3.5 w-3.5" />, ms: 2200 },
  { label: "Bank account", icon: <Landmark className="h-3.5 w-3.5" />, ms: 1700 },
  { label: "Risk", icon: <ShieldCheck className="h-3.5 w-3.5" />, ms: 2700 },
];

function useLoopClock(): number {
  const [t, setT] = useState(FIRST_FRAME);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; // keep the finished frame
    // Continue from the frame already on screen (the pre-rendered "live" state) so nothing jumps on load.
    const start = performance.now() - FIRST_FRAME;
    let raf = 0;
    const tick = (now: number) => {
      setT((now - start) % LOOP_MS);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return t;
}

export function HeroDemo() {
  const t = useLoopClock();
  const reading = t < READ_END;
  const live = t >= LIVE_AT;
  const phase = reading ? "Reading documents" : live ? "Live" : "Verifying in parallel";
  const scan = Math.min(1, t / READ_END);

  return (
    <div className="relative animate-fade-in">
      {/* soft glow */}
      <div aria-hidden className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-maple-100 via-orange-50 to-emerald-50 opacity-80 blur-2xl" />

      <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white/90 shadow-xl shadow-zinc-200/60 backdrop-blur">
        {/* header */}
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-maple-50 text-maple-600">
              <Building2 className="h-4 w-4" />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-zinc-900">Kumar Chai Corner</div>
              <div className="text-xs text-zinc-500">New merchant · Bengaluru</div>
            </div>
          </div>
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition-colors duration-500",
              live ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : reading ? "bg-maple-50 text-maple-700 ring-maple-200" : "bg-sky-50 text-sky-700 ring-sky-200",
            )}
          >
            {phase}
          </span>
        </div>

        <div className="grid gap-5 p-5 sm:grid-cols-[9.5rem_1fr]">
          {/* the document being read */}
          <div className="relative mx-auto h-28 w-40 overflow-hidden rounded-xl border border-zinc-200 bg-gradient-to-br from-amber-50 to-white p-3 sm:mx-0 sm:w-auto">
            <div className="flex gap-2">
              <div className="h-10 w-8 rounded-md bg-zinc-200/80" />
              <div className="flex-1 space-y-1.5 pt-0.5">
                <div className="h-1.5 w-full rounded bg-zinc-300/80" />
                <div className="h-1.5 w-4/5 rounded bg-zinc-200" />
                <div className="h-1.5 w-3/5 rounded bg-zinc-200" />
              </div>
            </div>
            <div className="mt-3 space-y-1.5">
              <div className="h-1.5 w-11/12 rounded bg-zinc-200" />
              <div className="h-1.5 w-2/3 rounded bg-zinc-200" />
            </div>
            <div className="absolute bottom-2 left-3 text-[10px] font-medium uppercase tracking-wider text-zinc-400">PAN card</div>
            {reading && (
              <div
                aria-hidden
                className="absolute inset-x-0 h-8 bg-gradient-to-b from-transparent via-maple-400/30 to-maple-500/50"
                style={{ top: `${scan * 100 - 20}%` }}
              >
                <div className="absolute inset-x-0 bottom-0 h-px bg-maple-500" />
              </div>
            )}
            {!reading && (
              <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-emerald-600 text-white">
                <Check className="h-3 w-3" />
              </span>
            )}
          </div>

          {/* what the AI read */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              {reading ? <ScanLine className="h-3.5 w-3.5 text-maple-500" /> : <Sparkles className="h-3.5 w-3.5 text-maple-500" />}
              {reading ? "AI is reading the document" : "Read by AI, nothing typed"}
            </div>
            {FIELDS.map((f) => {
              const shown = t >= f.at;
              return (
                <div
                  key={f.label}
                  className={cn(
                    "flex items-center justify-between rounded-lg border px-3 py-1.5 text-sm transition-all duration-500",
                    shown ? "translate-y-0 border-zinc-200 bg-white opacity-100" : "translate-y-1 border-transparent opacity-0",
                  )}
                >
                  <span className="text-zinc-500">{f.label}</span>
                  <span className="font-medium text-zinc-900">{f.value}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* parallel verification */}
        <div className="border-t border-zinc-100 px-5 py-4">
          <div className="mb-3 text-xs font-medium text-zinc-500">Four checks, all at once</div>
          <div className="grid grid-cols-2 gap-x-5 gap-y-3">
            {TRACKS.map((tr) => {
              const p = Math.max(0, Math.min(1, (t - VERIFY_START) / tr.ms));
              const done = p >= 1;
              return (
                <div key={tr.label}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className={cn("flex items-center gap-1.5", p > 0 ? "text-zinc-700" : "text-zinc-400")}>
                      {tr.icon}
                      {tr.label}
                    </span>
                    {done && <Check className="h-3.5 w-3.5 text-emerald-600" />}
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
                    <div className={cn("h-full rounded-full", done ? "bg-emerald-500" : "bg-sky-500")} style={{ width: `${p * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* outcome */}
        <div
          className={cn(
            "flex items-center gap-3 border-t px-5 py-4 transition-colors duration-500",
            live ? "border-emerald-100 bg-emerald-50/70" : "border-zinc-100 bg-zinc-50/60",
          )}
        >
          <span
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all duration-500",
              live ? "scale-100 bg-emerald-600 text-white" : "scale-90 bg-zinc-200 text-zinc-400",
            )}
          >
            <BadgeCheck className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className={cn("text-sm font-semibold", live ? "text-emerald-800" : "text-zinc-400")}>
              {live ? "Approved and live" : "Decision in progress"}
            </div>
            <div className="text-xs text-zinc-500">{live ? "Ready to accept payments" : "The agent decides once every check is in"}</div>
          </div>
          <div
            className={cn(
              "rounded-lg border border-dashed px-2.5 py-1 text-right transition-all duration-500",
              live ? "border-emerald-300 opacity-100" : "border-transparent opacity-0",
            )}
          >
            <div className="text-[10px] uppercase tracking-wider text-emerald-700/70">Merchant ID</div>
            <div className="font-mono text-sm font-semibold text-emerald-700">MLN 4821 3907</div>
          </div>
        </div>
      </div>
    </div>
  );
}
