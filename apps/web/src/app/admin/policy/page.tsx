"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Lock, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/providers";
import { AppShell, PageTitle } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Input, Label, PageLoader } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, cn } from "@/lib/format";
import type { Meta } from "@/lib/types";

type Policy = {
  business_types: Record<string, { required_documents: string[]; required_checks: string[]; pan_holder_type: string }>;
  thresholds: { min_extraction_confidence: number; min_document_quality: number; name_match_min: number; auto_approve_max_risk: number };
  high_risk_categories: string[];
  auto_approve_enabled: boolean;
  check_timeout_seconds: number;
  max_check_retries: number;
  mid_max_attempts: number;
  info_request_expiry_days: number;
};
type PolicyResp = { version: number; data: Policy; history: { version: number; note: string; created_by: string; created_at: string; is_active: boolean }[] };

const CHECKS = ["PAN", "GST", "BANK", "RISK"];

function NumberField({ label, value, onChange, step = 1, hint, disabled }: { label: string; value: number; onChange: (v: number) => void; step?: number; hint?: string; disabled?: boolean }) {
  return (
    <div>
      <Label hint={hint && <span className="text-xs font-normal text-zinc-400">{hint}</span>}>{label}</Label>
      <Input type="number" step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

function Toggle({ on, label, onClick, disabled }: { on: boolean; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn("rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors disabled:cursor-not-allowed", on ? "bg-maple-600 text-white ring-maple-600" : "bg-white text-zinc-600 ring-zinc-200 hover:ring-zinc-300")}
    >
      {label}
    </button>
  );
}

function PolicyEditor() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const q = useQuery({ queryKey: ["policy"], queryFn: () => api<PolicyResp>("/admin/policy") });
  const [p, setP] = useState<Policy | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (q.data) setP(structuredClone(q.data.data)); // eslint-disable-line react-hooks/set-state-in-effect
  }, [q.data]);

  if (!p || !meta.data || !q.data) return <PageLoader />;
  const m = meta.data;
  const t = p.thresholds;
  const setT = (k: keyof Policy["thresholds"], v: number) => setP({ ...p, thresholds: { ...t, [k]: v } });
  const toggleIn = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function save() {
    setBusy(true);
    try {
      const r = await api<{ version: number }>("/admin/policy", { method: "PUT", json: { data: p, note } });
      toast.success(`Policy v${r.version} is now active`);
      setNote("");
      qc.invalidateQueries({ queryKey: ["policy"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageTitle
        title="Approval policy"
        subtitle={<>Active version <Badge tone="maple">v{q.data.version}</Badge> · every automated decision records the version it used.</>}
        action={!isAdmin && <Badge><Lock className="h-3 w-3" /> read-only for operators</Badge>}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Automatic approval guardrails" subtitle="The AI agent can only approve when all of these hold" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <NumberField label="Max risk score for auto-approval" value={t.auto_approve_max_risk} onChange={(v) => setT("auto_approve_max_risk", v)} hint="0-100" disabled={!isAdmin} />
              <NumberField label="Min extraction confidence" value={t.min_extraction_confidence} step={0.05} onChange={(v) => setT("min_extraction_confidence", v)} hint="0-1" disabled={!isAdmin} />
              <NumberField label="Min document quality" value={t.min_document_quality} step={0.05} onChange={(v) => setT("min_document_quality", v)} hint="0-1" disabled={!isAdmin} />
              <NumberField label="Name match threshold (%)" value={t.name_match_min} onChange={(v) => setT("name_match_min", v)} hint="fuzzy" disabled={!isAdmin} />
              <label className="flex items-center gap-2 text-sm text-zinc-700 sm:col-span-2">
                <input type="checkbox" className="h-4 w-4 accent-maple-600" disabled={!isAdmin} checked={p.auto_approve_enabled} onChange={(e) => setP({ ...p, auto_approve_enabled: e.target.checked })} />
                Allow automatic approval (when off, every application goes to a human)
              </label>
            </div>
            <div className="border-t border-zinc-100 p-5">
              <Label>High-risk categories (always reviewed by a human)</Label>
              <div className="flex flex-wrap gap-2">
                {Object.entries(m.categories).map(([k, v]) => (
                  <Toggle key={k} label={v} on={p.high_risk_categories.includes(k)} disabled={!isAdmin} onClick={() => setP({ ...p, high_risk_categories: toggleIn(p.high_risk_categories, k) })} />
                ))}
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Requirements by business type" />
            <div className="divide-y divide-zinc-100">
              {Object.entries(p.business_types).map(([bt, rules]) => (
                <div key={bt} className="space-y-3 p-5">
                  <div className="font-medium text-zinc-900">
                    {m.business_types[bt]} <span className="text-xs font-normal text-zinc-400">· PAN holder type “{rules.pan_holder_type}”</span>
                  </div>
                  <div>
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-zinc-400">Documents</div>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(m.documents).map(([slot, d]) => (
                        <Toggle
                          key={slot}
                          label={d.label}
                          on={rules.required_documents.includes(slot)}
                          disabled={!isAdmin || slot === "PAN_CARD"}
                          onClick={() => setP({ ...p, business_types: { ...p.business_types, [bt]: { ...rules, required_documents: toggleIn(rules.required_documents, slot) } } })}
                        />
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-zinc-400">Verification checks</div>
                    <div className="flex flex-wrap gap-2">
                      {CHECKS.map((c) => (
                        <Toggle
                          key={c}
                          label={c}
                          on={rules.required_checks.includes(c)}
                          disabled={!isAdmin || c === "PAN"}
                          onClick={() => setP({ ...p, business_types: { ...p.business_types, [bt]: { ...rules, required_checks: toggleIn(rules.required_checks, c) } } })}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Resilience" subtitle="Timeouts and retries for asynchronous providers" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <NumberField label="Callback timeout (seconds)" value={p.check_timeout_seconds} onChange={(v) => setP({ ...p, check_timeout_seconds: v })} disabled={!isAdmin} />
              <NumberField label="Max retries per check" value={p.max_check_retries} onChange={(v) => setP({ ...p, max_check_retries: v })} disabled={!isAdmin} />
              <NumberField label="Merchant-ID attempts per run" value={p.mid_max_attempts} onChange={(v) => setP({ ...p, mid_max_attempts: v })} disabled={!isAdmin} />
              <NumberField label="Merchant response deadline (days)" value={p.info_request_expiry_days} onChange={(v) => setP({ ...p, info_request_expiry_days: v })} disabled={!isAdmin} />
            </div>
          </Card>

          {isAdmin && (
            <Card className="flex flex-wrap items-end gap-3 p-5">
              <div className="min-w-64 flex-1">
                <Label>What changed and why?</Label>
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Lower auto-approve risk limit after fraud review" />
              </div>
              <Button onClick={save} loading={busy} disabled={note.trim().length < 3}>
                <Save className="h-4 w-4" /> Publish new version
              </Button>
            </Card>
          )}
        </div>

        <Card className="h-fit">
          <CardHeader title="Version history" icon={<History className="h-4 w-4" />} />
          <ol className="divide-y divide-zinc-100">
            {q.data.history.map((h) => (
              <li key={h.version} className="px-5 py-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium">v{h.version}</span>
                  {h.is_active && <Badge tone="green">active</Badge>}
                  <span className="ml-auto text-xs text-zinc-400">{ago(h.created_at)}</span>
                </div>
                <p className="mt-1 text-zinc-600">{h.note}</p>
                <p className="text-xs text-zinc-400">{h.created_by}</p>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}

export default function PolicyPage() {
  return (
    <AppShell roles={["operator", "admin"]} wide>
      <PolicyEditor />
    </AppShell>
  );
}
