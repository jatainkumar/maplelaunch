"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play, RotateCcw, Skull } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/providers";
import { AppShell, PageTitle } from "@/components/shell";
import { Badge, Button, Card, CardHeader, PageLoader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, humanize } from "@/lib/format";
import { IS_DEMO } from "@/lib/mode";
import type { AppSummary, Persona } from "@/lib/types";

type Scenarios = {
  behaviors: Record<string, string[]>;
  pending_callbacks: number;
  scenarios: { provider: string; reference_id: string | null; behavior: string; updated_at: string }[];
};

const BEHAVIOR_HELP: Record<string, string> = {
  auto: "Outcome from the data (magic test values)",
  success: "Always pass",
  fail: "Always fail (provider-specific reason)",
  duplicate: "Send the final callback 3×",
  late: "Callback after the 45 s timeout, every time",
  late_once: "First attempt late, retries on time",
  outage: "Return 503 on every request",
  no_callback: "Accept but never call back",
  out_of_order: "Send a stale 'pending' after the result",
  fail_3: "Fail 3 times, then succeed",
  timeout: "Create the MID but respond too slowly",
};

function DeadJobs() {
  const dead = useQuery({ queryKey: ["dead"], queryFn: () => api<{ id: string; type: string; application_id: string | null; attempts: number; last_error: string; updated_at: string }[]>("/admin/jobs") });
  return (
    <Card>
      <CardHeader title="Dead-lettered jobs" icon={<Skull className="h-4 w-4" />} />
      <div className="divide-y divide-zinc-100">
        {(dead.data ?? []).length === 0 && <p className="px-5 py-4 text-sm text-zinc-500">None. Every background job succeeded or is retrying.</p>}
        {(dead.data ?? []).map((j) => (
          <div key={j.id} className="space-y-1 px-5 py-3 text-sm">
            <div className="flex justify-between">
              <span className="font-medium">{j.type}</span>
              <span className="text-xs text-zinc-400">{ago(j.updated_at)}</span>
            </div>
            <p className="line-clamp-2 text-xs text-zinc-500">{j.last_error}</p>
            <Button size="sm" variant="ghost" onClick={() => api(`/admin/jobs/${j.id}/replay`, { method: "POST" }).then(() => dead.refetch())}>
              Replay
            </Button>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Lab() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const router = useRouter();
  const qc = useQueryClient();
  const [running, setRunning] = useState<string | null>(null);
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/demo/personas") });
  const scen = useQuery({ queryKey: ["scenarios"], queryFn: () => api<Scenarios>("/admin/scenarios"), refetchInterval: 5000, retry: 0 });

  async function run(key: string) {
    setRunning(key);
    try {
      const app = await api<AppSummary>(`/demo/personas/${key}/run`, { method: "POST" });
      toast.success(`Started ${app.reference}`, { action: { label: "Open", onClick: () => router.push(`/ops/application/?id=${app.id}`) } });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRunning(null);
    }
  }

  async function setBehavior(provider: string, behavior: string) {
    try {
      await api("/admin/scenarios", { method: "PUT", json: { provider, behavior } });
      toast.success(`${provider}: ${behavior}`);
      qc.invalidateQueries({ queryKey: ["scenarios"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function resetDemo() {
    if (!confirm("Delete every application, document and audit entry and restore the default policy? Users are kept.")) return;
    try {
      await api("/admin/reset-demo", { method: "POST" });
      toast.success("Demo data cleared");
      qc.invalidateQueries();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const global = Object.fromEntries((scen.data?.scenarios ?? []).filter((s) => !s.reference_id).map((s) => [s.provider, s.behavior]));

  return (
    <>
      <PageTitle
        title="Scenario lab"
        subtitle="Run end-to-end demo merchants and inject provider failures to see how MapleLaunch copes."
        action={isAdmin && <Button variant="outline" onClick={resetDemo}>Reset demo data</Button>}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Demo merchants</h2>
          {!personas.data ? (
            <PageLoader />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {personas.data.map((p) => (
                <Card key={p.key} className="flex flex-col p-5">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-zinc-900">{p.title}</h3>
                    <Badge>{humanize(p.business_type)}</Badge>
                  </div>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-zinc-600">{p.story}</p>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {Object.entries(p.scenarios).map(([prov, b]) => (
                      <Badge key={prov} tone="violet">
                        {prov}: {b}
                      </Badge>
                    ))}
                    {Object.keys(p.fix_files).length > 0 && <Badge tone="blue">has sample fix</Badge>}
                  </div>
                  <Button className="mt-4" variant="secondary" size="sm" onClick={() => run(p.key)} loading={running === p.key}>
                    <Play className="h-3.5 w-3.5" /> Run as demo merchant
                  </Button>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Provider behaviour"
              subtitle={isAdmin ? "Applies to every new request" : "Admins can change these"}
              icon={<FlaskConical className="h-4 w-4" />}
              action={
                isAdmin && (
                  <Button size="sm" variant="ghost" onClick={() => api("/admin/scenarios", { method: "DELETE" }).then(() => qc.invalidateQueries({ queryKey: ["scenarios"] }))}>
                    <RotateCcw className="h-3.5 w-3.5" /> Reset
                  </Button>
                )
              }
            />
            {scen.isError ? (
              <p className="p-5 text-sm text-red-600">Mock providers unreachable. They may be waking up.</p>
            ) : !scen.data ? (
              <PageLoader />
            ) : (
              <div className="space-y-4 p-5">
                {Object.entries(scen.data.behaviors).map(([prov, list]) => (
                  <div key={prov}>
                    <div className="mb-1 text-sm font-medium text-zinc-800">{prov === "MID" ? "Merchant-ID service" : `${prov} provider`}</div>
                    <Select value={global[prov] ?? "auto"} disabled={!isAdmin} onChange={(e) => setBehavior(prov, e.target.value)}>
                      {list.map((b) => (
                        <option key={b} value={b}>
                          {b}: {BEHAVIOR_HELP[b] ?? ""}
                        </option>
                      ))}
                    </Select>
                  </div>
                ))}
                <p className="text-xs text-zinc-500">
                  {scen.data.pending_callbacks} callback(s) queued · {scen.data.scenarios.filter((s) => s.reference_id).length} per-application overrides
                </p>
              </div>
            )}
          </Card>
          <Card>
            <CardHeader title="Magic test values" subtitle="Work with behaviour = auto" />
            <ul className="space-y-1.5 p-5 text-sm text-zinc-600">
              <li>PAN digits <code className="font-mono">0000</code> → invalid · <code className="font-mono">9999</code> → deactivated</li>
              <li>GSTIN 13th char <code className="font-mono">9</code> → cancelled · <code className="font-mono">8</code> → not found</li>
              <li>Account ending <code className="font-mono">0000</code> → invalid · <code className="font-mono">1111</code> → name mismatch</li>
              <li>Category gaming / crypto → high risk</li>
            </ul>
          </Card>
          <DeadJobs />
        </div>
      </div>
    </>
  );
}

export default function LabPage() {
  return (
    <AppShell roles={["operator", "admin"]} wide>
      {IS_DEMO ? (
        <Lab />
      ) : (
        <>
          <PageTitle title="Background jobs" subtitle="Jobs that failed every retry. Replay them once the cause is fixed." />
          <div className="max-w-xl">
            <DeadJobs />
          </div>
        </>
      )}
    </AppShell>
  );
}
