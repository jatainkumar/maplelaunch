"use client";

import { AlertTriangle, CheckCircle2, Circle, Clock, Loader2, XCircle } from "lucide-react";

import { Badge, type Tone } from "@/components/ui";

const STATUS_TONE: Record<string, Tone> = {
  DRAFT: "neutral",
  SUBMITTED: "blue",
  PROCESSING_DOCUMENTS: "blue",
  AWAITING_MERCHANT: "amber",
  VERIFYING: "blue",
  DECISIONING: "violet",
  MANUAL_REVIEW: "amber",
  APPROVED: "green",
  PROVISIONING: "green",
  PROVISIONING_FAILED: "red",
  LIVE: "green",
  REJECTED: "red",
  WITHDRAWN: "neutral",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label ?? status.replace(/_/g, " ").toLowerCase()}</Badge>;
}

const CHECK_TONE: Record<string, Tone> = {
  REQUESTED: "blue",
  PENDING: "blue",
  PASSED: "green",
  FAILED: "red",
  TIMED_OUT: "amber",
  ERROR: "amber",
  INVALIDATED: "neutral",
};

export function CheckBadge({ status }: { status: string }) {
  return <Badge tone={CHECK_TONE[status] ?? "neutral"}>{status.replace("_", " ").toLowerCase()}</Badge>;
}

export function CheckIcon({ status, className = "h-5 w-5" }: { status?: string; className?: string }) {
  if (status === "PASSED") return <CheckCircle2 className={`${className} text-emerald-600`} />;
  if (status === "FAILED") return <XCircle className={`${className} text-red-600`} />;
  if (status === "TIMED_OUT" || status === "ERROR") return <AlertTriangle className={`${className} text-amber-500`} />;
  if (status === "REQUESTED" || status === "PENDING") return <Loader2 className={`${className} animate-spin text-sky-500`} />;
  if (status === "WAITING") return <Clock className={`${className} text-amber-500`} />;
  return <Circle className={`${className} text-zinc-300`} />;
}

export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const tone: Tone = value >= 0.9 ? "green" : value >= 0.75 ? "amber" : "red";
  return (
    <Badge tone={tone} className="tabular-nums">
      {pct}% sure
    </Badge>
  );
}

export function RiskBadge({ score, band }: { score: number | null; band: string | null }) {
  if (score == null) return <span className="text-zinc-400">-</span>;
  const tone: Tone = band === "HIGH" ? "red" : band === "MEDIUM" ? "amber" : "green";
  return (
    <Badge tone={tone} className="tabular-nums">
      {score} · {band?.toLowerCase()}
    </Badge>
  );
}
