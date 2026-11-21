"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, ArrowUpRight, FlaskConical, Search, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppShell, PageTitle } from "@/components/shell";
import { RiskBadge, StatusBadge } from "@/components/status";
import { Badge, Button, Card, Empty, Input, PageLoader, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, duration } from "@/lib/format";
import { IS_DEMO } from "@/lib/mode";
import type { OpsRow } from "@/lib/types";

type Overview = {
  by_status: Record<string, number>;
  open_exceptions: number;
  open_reviews: number;
  decided: number;
  auto_decided: number;
  auto_approval_rate: number | null;
  median_minutes_to_decision: number | null;
  duplicate_callbacks_ignored: number;
  late_callbacks: number;
  exception_rate: number | null;
};

const FILTERS = [
  { key: "attention", label: "Needs attention" },
  { key: "all", label: "All" },
  { key: "MANUAL_REVIEW", label: "In review" },
  { key: "SUBMITTED,PROCESSING_DOCUMENTS,VERIFYING,DECISIONING", label: "In progress" },
  { key: "AWAITING_MERCHANT", label: "Waiting on merchant" },
  { key: "LIVE", label: "Live" },
  { key: "REJECTED,WITHDRAWN", label: "Closed" },
] as const;

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs font-medium text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-zinc-900">{value}</div>
      {hint && <div className="text-xs text-zinc-400">{hint}</div>}
    </Card>
  );
}

function Queue() {
  const router = useRouter();
  const [filter, setFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/ops/overview"), refetchInterval: 5000 });
  const rows = useQuery({
    queryKey: ["queue", filter],
    queryFn: () => {
      const p = new URLSearchParams();
      if (filter === "attention") p.set("attention", "true");
      else if (filter !== "all") p.set("status", filter);
      return api<OpsRow[]>(`/ops/applications?${p}`);
    },
    refetchInterval: 4000,
  });
  const o = overview.data;
  const list = (rows.data ?? []).filter((r) => !q || `${r.reference} ${r.legal_name} ${r.trade_name}`.toLowerCase().includes(q.toLowerCase()));
  const live = o?.by_status?.LIVE ?? 0;
  const total = o ? Object.entries(o.by_status).filter(([k]) => k !== "DRAFT").reduce((s, [, v]) => s + v, 0) : 0;

  return (
    <>
      <PageTitle
        title="Onboarding queue"
        subtitle="Everything the platform couldn't finish on its own, plus a live view of the rest."
        action={
          IS_DEMO && (
            <Link href="/admin/lab/">
              <Button variant="outline">
                <FlaskConical className="h-4 w-4" /> Run a demo scenario
              </Button>
            </Link>
          )
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        <Stat label="Applications" value={total} hint={`${live} live`} />
        <Stat label="Open reviews" value={o?.open_reviews ?? "-"} />
        <Stat label="Open exceptions" value={o?.open_exceptions ?? "-"} hint={o?.exception_rate != null ? `${Math.round(o.exception_rate * 100)}% of apps hit one` : undefined} />
        <Stat label="Auto-decided" value={o?.auto_approval_rate != null ? `${Math.round(o.auto_approval_rate * 100)}%` : "-"} hint={o ? `${o.auto_decided} of ${o.decided}` : undefined} />
        <Stat label="Time to decision" value={duration(o?.median_minutes_to_decision)} hint="median" />
        <Stat label="Callbacks absorbed" value={(o?.duplicate_callbacks_ignored ?? 0) + (o?.late_callbacks ?? 0)} hint="duplicate or late" />
      </div>

      <Card>
        <div className="flex flex-col gap-3 px-4 pt-3 xl:flex-row xl:items-center">
          <div className="min-w-0 flex-1">
            <Tabs tabs={FILTERS.map((f) => ({ key: f.key, label: f.label }))} value={filter} onChange={setFilter} />
          </div>
          <div className="relative w-full xl:w-64">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input placeholder="Search name or reference" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        {rows.isLoading ? (
          <PageLoader />
        ) : list.length === 0 ? (
          <Empty icon={<Users className="h-10 w-10" />} title={filter === "attention" ? "Nothing needs you right now" : "No applications here"}>
            {IS_DEMO
              ? "Run a demo scenario from the lab or apply as the demo merchant to see applications flow through."
              : "New applications appear here as merchants submit them."}
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-100 text-left text-xs font-medium uppercase tracking-wide text-zinc-400">
                  <th className="px-4 py-3">Merchant</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Attention</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">In state</th>
                  <th className="px-4 py-3">Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {list.map((r) => (
                  <tr key={r.id} className="cursor-pointer hover:bg-zinc-50" onClick={() => router.push(`/ops/application/?id=${r.id}`)}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900">{r.trade_name || r.legal_name || "-"}</div>
                      <div className="text-xs text-zinc-500">
                        {r.reference} · {r.business_type_label} · {r.category_label}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} label={r.status_label} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {r.review && (
                          <Badge tone={r.review.recommendation === "reject" ? "red" : "amber"}>
                            {r.review.kind === "post_live" ? "post-live review" : r.review.recommendation === "review" ? "needs review" : `review · AI says ${r.review.recommendation}`}
                          </Badge>
                        )}
                        {r.open_exceptions > 0 && (
                          <Badge tone="red">
                            <AlertOctagon className="h-3 w-3" /> {r.open_exceptions}
                          </Badge>
                        )}
                        {r.open_duplicates > 0 && <Badge tone="violet">possible duplicate</Badge>}
                        {r.payouts_on_hold && <Badge tone="amber">payouts held</Badge>}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge score={r.risk_score} band={r.risk_band} />
                    </td>
                    <td className="px-4 py-3 tabular-nums text-zinc-600">{duration(r.minutes_in_state)}</td>
                    <td className="px-4 py-3 text-zinc-500">{ago(r.updated_at)}</td>
                    <td className="px-4 py-3 text-zinc-300">
                      <ArrowUpRight className="h-4 w-4" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export default function OpsPage() {
  return (
    <AppShell roles={["operator", "admin"]} wide>
      <Queue />
    </AppShell>
  );
}
