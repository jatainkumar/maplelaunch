"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon, ArrowLeft, Bot, CheckCircle2, Cpu, Eye, FileText, Fingerprint, Link2, Lock, Radio, RotateCcw, ShieldAlert,
  ShieldCheck, Store, ThumbsDown, ThumbsUp, User, XCircle,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/shell";
import { CheckBadge, CheckIcon, ConfidenceBadge, RiskBadge, StatusBadge } from "@/components/status";
import { Badge, Button, Card, CardHeader, Empty, Input, Label, Modal, PageLoader, Tabs, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, cn, dateTime, FIELD_LABELS, humanize, prettyValue, time } from "@/lib/format";
import type { Doc, OpsDetail } from "@/lib/types";

const WAITING: Record<string, string> = {
  checks: "provider callbacks",
  merchant: "the merchant",
  review: "a reviewer (you)",
  ops: "ops to retry provisioning",
  post_live: "post-go-live events",
};
const PII_KEYS = ["pan", "gstin", "cin", "account_number", "phone", "email"] as const;
const CHECK_NAMES: Record<string, string> = { PAN: "PAN", GST: "GST registration", BANK: "Bank penny-drop", RISK: "Risk assessment" };

function actorIcon(actor: string) {
  if (actor.startsWith("provider:")) return <Radio className="h-3.5 w-3.5" />;
  if (actor === "agent") return <Bot className="h-3.5 w-3.5" />;
  if (actor === "rules-engine" || actor === "system") return <Cpu className="h-3.5 w-3.5" />;
  if (actor.startsWith("merchant")) return <Store className="h-3.5 w-3.5" />;
  return <User className="h-3.5 w-3.5" />;
}

function describe(a: OpsDetail["audit"][number]): { text: string; tone?: "good" | "bad" | "warn" } {
  const d = a.details as Record<string, unknown>;
  const s = (k: string) => (d[k] == null ? "" : String(d[k]));
  switch (a.action) {
    case "state_changed":
      return { text: `${humanize(s("from"))} → ${humanize(s("to"))}${d.reason ? ` · ${s("reason")}` : ""}` };
    case "document_uploaded":
      return { text: `Uploaded ${humanize(s("slot"))}` };
    case "document_extracted":
      return d.error ? { text: `Couldn't read ${humanize(s("slot"))}: ${s("error")}`, tone: "warn" } : { text: `Read ${humanize(s("slot"))} with ${s("model")} (quality ${s("quality")})` };
    case "validation_completed": {
      const b = (d.blocking as string[]) ?? [];
      const f = (d.flags as string[]) ?? [];
      return { text: `Validation: ${b.length ? `${b.length} blocking (${b.join(", ")})` : "no blocking issues"}${f.length ? ` · flags: ${f.join(", ")}` : ""}`, tone: b.length ? "warn" : "good" };
    }
    case "duplicate_check_completed": {
      const m = (d.matches as unknown[]) ?? [];
      return { text: m.length ? `Possible duplicate: ${m.length} match(es)` : "No duplicates found", tone: m.length ? "warn" : undefined };
    }
    case "check_dispatched":
      return { text: `${s("check")} check sent to provider (attempt ${s("attempt")})` };
    case "callback_applied":
      return { text: `${s("check")} callback: ${s("status")}${d.reason ? ` · ${s("reason")}` : ""}${d.late ? " · late result accepted" : ""}`, tone: s("status") === "PASSED" ? "good" : s("status") === "FAILED" ? "bad" : undefined };
    case "callback_duplicate_ignored":
      return { text: `Duplicate callback ignored (${s("event_id")})`, tone: "warn" };
    case "callback_stale_ignored":
      return { text: `Late ${s("check")} result for superseded attempt ${s("attempt")} recorded, not applied`, tone: "warn" };
    case "callback_out_of_order_ignored":
      return { text: `Out-of-order ${s("check")} callback ignored (${s("reported")} after ${s("current")})`, tone: "warn" };
    case "check_timed_out":
      return { text: `${s("check")} check timed out waiting for callback (attempt ${s("attempt")})`, tone: "warn" };
    case "check_provider_error":
      return { text: `${s("check")} provider unavailable: ${s("reason")}`, tone: "bad" };
    case "check_invalidated":
      return { text: `${s("check")} result invalidated: ${humanize(s("reason"))}`, tone: "warn" };
    case "decision_made":
      return { text: `Decision: ${humanize(s("action"))}. ${s("reason")}${d.rules_engine_would && d.rules_engine_would !== d.action ? ` (rules engine would: ${s("rules_engine_would")})` : ""}` };
    case "mid_attempt_failed":
      return { text: `Merchant ID attempt ${s("attempt")} failed: ${s("error")}`, tone: "bad" };
    case "review_decision":
      return { text: `Reviewer decision: ${humanize(s("decision"))}${d.note ? `: “${s("note")}”` : ""}` };
    case "pii_revealed":
      return { text: `Revealed ${s("field")}, reason: “${s("reason")}”`, tone: "warn" };
    case "merchant_responded":
      return { text: `Merchant responded${(d.changed_fields as string[])?.length ? ` · changed ${(d.changed_fields as string[]).join(", ")}` : ""}` };
    case "bank_details_changed":
      return { text: `Bank details changed while ${humanize(s("status"))}`, tone: "warn" };
    case "payouts_on_hold":
      return { text: "Payouts put on hold", tone: "warn" };
    case "payouts_released":
      return { text: "Payouts released", tone: "good" };
    default:
      return { text: humanize(a.action) };
  }
}

function DocViewer({ appId, doc, onClose }: { appId: string; doc: Doc | null; onClose: () => void }) {
  const url = useQuery({
    queryKey: ["doc-url", doc?.id],
    queryFn: () => api<{ url: string; mime: string }>(`/applications/${appId}/documents/${doc!.id}/url`),
    enabled: !!doc,
    staleTime: 30_000,
  });
  return (
    <Modal open={!!doc} onClose={onClose} title={doc?.label ?? ""} wide>
      {doc && (
        <div className="grid gap-5 md:grid-cols-5">
          <div className="md:col-span-3">
            {!url.data ? (
              <PageLoader label="Fetching a 60-second secure link…" />
            ) : url.data.mime === "application/pdf" ? (
              <iframe src={url.data.url} className="h-[60vh] w-full rounded-lg border" title={doc.label} />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={url.data.url} alt={doc.label} className="w-full rounded-lg border" />
            )}
            <p className="mt-2 flex items-center gap-1 text-xs text-zinc-400">
              <Lock className="h-3 w-3" /> Private storage · link expires in 60 s · this view is audit-logged
            </p>
          </div>
          <div className="md:col-span-2">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">Extracted (masked)</div>
            {doc.extraction?.error && <p className="text-sm text-amber-700">{doc.extraction.error}</p>}
            <div className="space-y-2">
              {Object.entries(doc.extraction?.fields ?? {}).map(([k, f]) => (
                <div key={k} className="flex items-center justify-between gap-2 border-b border-zinc-100 pb-1.5 text-sm">
                  <span className="text-zinc-500">{FIELD_LABELS[k] ?? k}</span>
                  <span className="flex items-center gap-2">
                    <span className="break-words text-right font-medium">{prettyValue(k, f.value)}</span>
                    {f.value && <ConfidenceBadge value={f.confidence} />}
                  </span>
                </div>
              ))}
            </div>
            {doc.extraction?.quality && (
              <div className="mt-4 rounded-lg bg-zinc-50 p-3 text-xs text-zinc-600">
                Quality {doc.extraction.quality.score ?? "-"} · blur {doc.extraction.quality.blur ?? "-"}
                {doc.extraction.quality.notes ? ` · ${doc.extraction.quality.notes}` : ""}
                <br />
                Model: {doc.extraction.model}
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

function DecisionPanel({ d, onDone }: { d: OpsDetail; onDone: () => void }) {
  const [mode, setMode] = useState<null | "approve" | "reject" | "request_info" | "retry_check">(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [items, setItems] = useState<Record<string, boolean>>({});
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const docSlots = Array.from(new Set(d.documents.filter((x) => x.is_active).map((x) => x.slot)));
  const options = [
    ...docSlots.map((s) => ({ id: `document:${s}`, kind: "document", key: s, label: `New ${humanize(s)}` })),
    { id: "field:gstin", kind: "field", key: "gstin", label: "Corrected GSTIN" },
    { id: "field:bank", kind: "field", key: "bank", label: "Different bank account" },
    { id: "confirm:legal_name", kind: "confirm", key: "legal_name", label: "Confirm legal name" },
  ];

  async function send() {
    setBusy(true);
    try {
      await api(`/ops/applications/${d.application.id}/decision`, {
        method: "POST",
        json: {
          decision: mode,
          note,
          message: message || null,
          version: d.application.version,
          items: options.filter((o) => items[o.id]).map((o) => ({ kind: o.kind, key: o.key, label: o.label, reason: note || "Requested by reviewer" })),
          checks: Object.keys(checks).filter((k) => checks[k]),
        },
      });
      toast.success("Decision recorded. The workflow is resuming");
      setMode(null);
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Button variant="success" onClick={() => setMode("approve")}>
          <ThumbsUp className="h-4 w-4" /> Approve
        </Button>
        <Button variant="danger" onClick={() => setMode("reject")}>
          <ThumbsDown className="h-4 w-4" /> Reject
        </Button>
        <Button variant="outline" onClick={() => setMode("request_info")}>
          Request info
        </Button>
        <Button variant="outline" onClick={() => setMode("retry_check")}>
          <RotateCcw className="h-4 w-4" /> Re-run checks
        </Button>
      </div>
      <Modal
        open={!!mode}
        onClose={() => setMode(null)}
        title={mode === "approve" ? "Approve merchant" : mode === "reject" ? "Reject application" : mode === "request_info" ? "Ask the merchant for more" : "Re-run verification checks"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMode(null)}>
              Cancel
            </Button>
            <Button variant={mode === "reject" ? "danger" : "primary"} onClick={send} loading={busy}>
              Confirm
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {mode === "request_info" && (
            <div className="space-y-2">
              <Label>What do you need?</Label>
              {options.map((o) => (
                <label key={o.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="h-4 w-4 accent-maple-600" checked={!!items[o.id]} onChange={(e) => setItems({ ...items, [o.id]: e.target.checked })} />
                  {o.label}
                </label>
              ))}
              <div className="pt-2">
                <Label hint={<span className="text-xs font-normal text-zinc-400">leave empty to let AI draft it</span>}>Message to merchant</Label>
                <Textarea value={message} onChange={(e) => setMessage(e.target.value)} />
              </div>
            </div>
          )}
          {mode === "retry_check" && (
            <div className="space-y-2">
              {["PAN", "GST", "BANK", "RISK"].map((c) => (
                <label key={c} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="h-4 w-4 accent-maple-600" checked={!!checks[c]} onChange={(e) => setChecks({ ...checks, [c]: e.target.checked })} />
                  {CHECK_NAMES[c]}
                </label>
              ))}
            </div>
          )}
          <div>
            <Label>{mode === "reject" ? "Reason (shared with the merchant)" : "Note for the audit log"}</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={mode === "approve" ? "e.g. Bank letter confirms the account belongs to the company" : ""} />
          </div>
          {mode === "approve" && <p className="text-xs text-zinc-500">Approving starts merchant-ID creation immediately.</p>}
        </div>
      </Modal>
    </>
  );
}

function Detail() {
  const id = useSearchParams().get("id")!;
  const qc = useQueryClient();
  const [tab, setTab] = useState<"overview" | "documents" | "timeline" | "audit">("overview");
  const [viewDoc, setViewDoc] = useState<Doc | null>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [revealing, setRevealing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const q = useQuery({ queryKey: ["ops-app", id], queryFn: () => api<OpsDetail>(`/ops/applications/${id}`), refetchInterval: 2500 });
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops-app", id] });

  const checksByType = useMemo(() => {
    const m: Record<string, OpsDetail["checks"]> = {};
    for (const c of d?.checks ?? []) (m[c.type] ??= []).push(c);
    return m;
  }, [d]);

  if (!d) return <PageLoader />;
  const a = d.application;
  const openReview = d.reviews.find((r) => r.status === "open");
  const canDecide = a.status === "MANUAL_REVIEW" && d.waiting_for === "review";

  async function doReveal() {
    try {
      const r = await api<{ value: string }>(`/ops/applications/${id}/reveal`, { method: "POST", json: { field: revealing, reason } });
      setRevealed({ ...revealed, [revealing!]: r.value ?? "-" });
      setRevealing(null);
      setReason("");
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function post(path: string, body: unknown = {}, ok = "Done") {
    try {
      await api(path, { method: "POST", json: body });
      toast.success(ok);
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/ops/" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> Queue
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">{a.trade_name || a.legal_name}</h1>
            <StatusBadge status={a.status} label={a.status_label} />
            {a.payouts_on_hold && <Badge tone="amber">payouts on hold</Badge>}
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            {a.reference} · {a.business_type_label} · {a.category_label} · submitted {ago(a.submitted_at)}
            {a.mid && <span className="font-medium text-emerald-700"> · MID {a.mid}</span>}
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            Workflow {d.waiting_for ? <>waiting for <span className="font-medium text-zinc-600">{WAITING[d.waiting_for] ?? d.waiting_for}</span></> : "running or finished"}
            {" · "}entered this state {ago(a.status_changed_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canDecide && <DecisionPanel d={d} onDone={refresh} />}
          {a.status === "PROVISIONING_FAILED" && (
            <Button onClick={() => post(`/ops/applications/${id}/retry-provisioning`, {}, "Retrying merchant-ID creation")}>
              <RotateCcw className="h-4 w-4" /> Retry provisioning
            </Button>
          )}
          {a.status === "LIVE" && a.payouts_on_hold && (
            <Button variant="outline" onClick={() => post(`/ops/applications/${id}/release-hold`, { note: "Verified by operator" }, "Payouts released")}>
              Release payout hold
            </Button>
          )}
        </div>
      </div>

      {openReview && (
        <Card className={cn("border-l-4", openReview.recommendation === "reject" ? "border-l-red-500" : "border-l-amber-400")}>
          <div className="flex flex-wrap items-start gap-4 p-5">
            <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", openReview.recommendation === "reject" ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-600")}>
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-zinc-900">{openReview.kind === "post_live" ? "Post-go-live review" : "Why this needs you"}</span>
                <Badge tone={openReview.recommendation === "reject" ? "red" : openReview.recommendation === "approve" ? "green" : "amber"}>
                  AI recommends: {openReview.recommendation}
                </Badge>
                {openReview.priority === "high" && <Badge tone="red">high priority</Badge>}
                <span className="text-xs text-zinc-400">opened {ago(openReview.created_at)}</span>
              </div>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-zinc-700">{openReview.summary}</p>
            </div>
          </div>
        </Card>
      )}

      <Tabs
        tabs={[
          { key: "overview", label: "Overview" },
          { key: "documents", label: `Documents (${d.documents.filter((x) => x.is_active).length})` },
          { key: "timeline", label: "Timeline" },
          { key: "audit", label: "Audit log" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "overview" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card>
              <CardHeader title="Verification checks" subtitle="All attempts, including superseded ones" />
              <div className="divide-y divide-zinc-100">
                {["PAN", "GST", "BANK", "RISK"].map((t) => {
                  const list = checksByType[t] ?? [];
                  const cur = list.find((c) => c.is_current);
                  return (
                    <div key={t} className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <CheckIcon status={cur?.status} />
                        <span className="font-medium text-zinc-900">{CHECK_NAMES[t]}</span>
                        {cur && <CheckBadge status={cur.status} />}
                        {cur?.reason_code && <span className="text-sm text-red-600">{humanize(cur.reason_code)}</span>}
                        {cur?.late && <Badge tone="amber">late result</Badge>}
                      </div>
                      {list.length > 0 && (
                        <div className="ml-8 mt-2 space-y-1">
                          {list.map((c) => (
                            <div key={c.id} className={cn("flex flex-wrap gap-x-3 text-xs", c.is_current ? "text-zinc-600" : "text-zinc-400 line-through decoration-zinc-300")}>
                              <span className="font-mono">#{c.attempt}</span>
                              <span>{c.status.toLowerCase()}</span>
                              <span>sent {time(c.requested_at)}</span>
                              {c.completed_at && <span>done {time(c.completed_at)}</span>}
                              {c.result?.beneficiary_name ? <span>beneficiary “{String(c.result.beneficiary_name)}”</span> : null}
                              {c.result?.name_match_score != null ? <span>name match {String(c.result.name_match_score)}%</span> : null}
                              {c.result?.registration_status ? <span>GST {String(c.result.registration_status)}</span> : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card>
              <CardHeader title="Validation" subtitle="Deterministic rules on documents and form" />
              <div className="divide-y divide-zinc-100">
                {d.validations.length === 0 && <p className="px-5 py-4 text-sm text-zinc-500">Not run yet.</p>}
                {[...d.validations]
                  .sort((x, y) => ["fail", "warn", "pass"].indexOf(x.outcome) - ["fail", "warn", "pass"].indexOf(y.outcome))
                  .map((v, i) => (
                    <div key={i} className="flex items-start gap-3 px-5 py-2.5 text-sm">
                      {v.outcome === "pass" ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-500" /> : v.outcome === "warn" ? <ShieldAlert className="mt-0.5 h-4 w-4 text-amber-500" /> : <XCircle className="mt-0.5 h-4 w-4 text-red-500" />}
                      <span className="text-zinc-700">{v.message}</span>
                    </div>
                  ))}
              </div>
            </Card>

            <Card>
              <CardHeader title="Decision trail" subtitle="What the agent (or rules engine) decided and why" icon={<Bot className="h-4 w-4" />} />
              <div className="divide-y divide-zinc-100">
                {d.decisions.length === 0 && <p className="px-5 py-4 text-sm text-zinc-500">No decisions yet.</p>}
                {d.decisions.map((x, i) => (
                  <div key={i} className="px-5 py-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={x.action.includes("approve") ? "green" : x.action.includes("reject") ? "red" : x.action.includes("escalate") ? "amber" : "blue"}>{humanize(x.action.replace("human:", "reviewer: "))}</Badge>
                      <span className="text-xs text-zinc-500">{x.model}{x.used_fallback && x.model !== "human" ? " · deterministic fallback" : ""}</span>
                      <span className="ml-auto text-xs text-zinc-400">{time(x.at)}</span>
                    </div>
                    {x.reasoning && <p className="mt-1.5 text-zinc-700">{x.reasoning}</p>}
                    {x.rules_action && x.rules_action !== x.action && x.model !== "human" && <p className="mt-1 text-xs text-zinc-500">Rules engine would have chosen: {humanize(x.rules_action)}</p>}
                    {(x.guardrail?.refusals ?? []).map((r, j) => (
                      <p key={j} className="mt-1 flex items-center gap-1 text-xs text-red-600">
                        <ShieldCheck className="h-3 w-3" /> Guardrail blocked {r.tool}: {r.error}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader title="Merchant details" subtitle="Identifiers are masked" icon={<Fingerprint className="h-4 w-4" />} />
              <div className="space-y-2.5 p-5 text-sm">
                {["legal_name", "trade_name", "contact_name", ...PII_KEYS, "ifsc", "account_holder_name", "bank_name", "address", "city", "pincode", "monthly_volume"].map((k) => {
                  const v = revealed[k] ?? d.data[k];
                  if (v == null || v === "") return null;
                  return (
                    <div key={k} className="flex items-start justify-between gap-3">
                      <span className="shrink-0 text-zinc-500">{FIELD_LABELS[k] ?? k}</span>
                      <span className="flex items-center gap-1.5 text-right font-medium text-zinc-900">
                        <span className={cn((PII_KEYS as readonly string[]).includes(k) && "font-mono")}>{String(v)}</span>
                        {(PII_KEYS as readonly string[]).includes(k) && !revealed[k] && (
                          <button onClick={() => setRevealing(k)} className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700" title="Reveal (audited)">
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card>
              <CardHeader title="Risk" action={<RiskBadge score={d.risk.score} band={d.risk.band} />} />
              <div className="space-y-3 p-5 text-sm">
                {d.risk.explanation && <p className="leading-relaxed text-zinc-700">{d.risk.explanation}</p>}
                {(d.risk.signals ?? []).map((s) => (
                  <div key={s.code} className="flex justify-between text-zinc-600">
                    <span>{humanize(s.code)}</span>
                    <span className="font-mono text-zinc-500">+{s.weight}</span>
                  </div>
                ))}
                {d.risk.score == null && <p className="text-zinc-500">Waiting for the risk provider.</p>}
              </div>
            </Card>

            {d.duplicates.length > 0 && (
              <Card className="border-violet-200">
                <CardHeader title="Possible duplicates" icon={<Link2 className="h-4 w-4" />} />
                <div className="divide-y divide-zinc-100">
                  {d.duplicates.map((m) => (
                    <div key={m.id} className="space-y-2 px-5 py-3 text-sm">
                      <div className="flex items-center justify-between">
                        <Link href={`/ops/application/?id=${m.matched_application_id}`} className="font-medium text-maple-700 hover:underline">
                          {m.matched_reference}
                        </Link>
                        <StatusBadge status={m.matched_status} />
                      </div>
                      <div className="text-xs text-zinc-500">
                        Matched on {m.matched_on.map(humanize).join(", ")} · score {Math.round(m.score * 100)}%
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => post(`/ops/duplicates/${m.id}`, { status: "cleared" }, "Marked as not a duplicate")}>
                          Not a duplicate
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => post(`/ops/duplicates/${m.id}`, { status: "confirmed" }, "Confirmed duplicate")}>
                          Confirm
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {d.exceptions.filter((e) => e.status === "open").length > 0 && (
              <Card className="border-red-200">
                <CardHeader title="Exceptions" icon={<AlertOctagon className="h-4 w-4 text-red-500" />} />
                <div className="divide-y divide-zinc-100">
                  {d.exceptions
                    .filter((e) => e.status === "open")
                    .map((e) => (
                      <div key={e.id} className="space-y-2 px-5 py-3 text-sm">
                        <div className="font-medium text-zinc-900">{humanize(e.kind)}</div>
                        <div className="text-zinc-600">{e.message}</div>
                        <Button size="sm" variant="ghost" onClick={() => post(`/ops/exceptions/${e.id}/resolve`, { note: "Resolved from console" }, "Exception resolved")}>
                          Mark resolved
                        </Button>
                      </div>
                    ))}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}

      {tab === "documents" && (
        <Card>
          <div className="divide-y divide-zinc-100">
            {d.documents.length === 0 && <Empty title="No documents" />}
            {d.documents.map((doc) => (
              <div key={doc.id} className={cn("flex flex-wrap items-center gap-4 px-5 py-4", !doc.is_active && "opacity-50")}>
                <FileText className="h-5 w-5 text-zinc-400" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-medium text-zinc-900">
                    {doc.label} {!doc.is_active && <Badge>superseded</Badge>}
                    {doc.detected_type && doc.detected_type !== doc.slot && <Badge tone="red">looks like {humanize(doc.detected_type)}</Badge>}
                  </div>
                  <div className="text-xs text-zinc-500">
                    {doc.filename} · uploaded {dateTime(doc.uploaded_at)} · quality {doc.quality ?? "-"} · {doc.extraction?.model ?? "not read"}
                  </div>
                </div>
                <Button size="sm" variant="outline" onClick={() => setViewDoc(doc)}>
                  <Eye className="h-4 w-4" /> View
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "timeline" && (
        <Card>
          <ol className="relative space-y-0 p-5">
            {d.audit.map((e) => {
              const { text, tone } = describe(e);
              return (
                <li key={e.id} className="flex gap-3 pb-4">
                  <div className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", tone === "good" ? "bg-emerald-50 text-emerald-600" : tone === "bad" ? "bg-red-50 text-red-600" : tone === "warn" ? "bg-amber-50 text-amber-600" : "bg-zinc-100 text-zinc-500")}>
                    {actorIcon(e.actor)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-zinc-800">{text}</div>
                    <div className="text-xs text-zinc-400">
                      {time(e.at)} · {e.actor}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>
      )}

      {tab === "audit" && (
        <Card>
          <CardHeader
            title="Tamper-evident audit log"
            subtitle="Each entry stores a SHA-256 hash of the previous one"
            action={
              <Badge tone={d.audit_chain.valid ? "green" : "red"}>
                {d.audit_chain.valid ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
                {d.audit_chain.valid ? `chain verified · ${d.audit_chain.entries} entries` : `chain broken at #${d.audit_chain.broken_at}`}
              </Badge>
            }
          />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-100 text-left uppercase tracking-wide text-zinc-400">
                  <th className="px-4 py-2">#</th>
                  <th className="px-4 py-2">Time</th>
                  <th className="px-4 py-2">Actor</th>
                  <th className="px-4 py-2">Action</th>
                  <th className="px-4 py-2">Details</th>
                  <th className="px-4 py-2">Hash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-50 font-mono">
                {d.audit.map((e) => (
                  <tr key={e.id}>
                    <td className="px-4 py-1.5 text-zinc-400">{e.id}</td>
                    <td className="whitespace-nowrap px-4 py-1.5 text-zinc-500">{time(e.at)}</td>
                    <td className="whitespace-nowrap px-4 py-1.5">{e.actor}</td>
                    <td className="whitespace-nowrap px-4 py-1.5 text-zinc-900">{e.action}</td>
                    <td className="max-w-md truncate px-4 py-1.5 text-zinc-500" title={JSON.stringify(e.details)}>
                      {JSON.stringify(e.details)}
                    </td>
                    <td className="px-4 py-1.5 text-zinc-400">{e.hash}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <DocViewer appId={id} doc={viewDoc} onClose={() => setViewDoc(null)} />
      <Modal
        open={!!revealing}
        onClose={() => setRevealing(null)}
        title={`Reveal ${FIELD_LABELS[revealing ?? ""] ?? revealing}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevealing(null)}>
              Cancel
            </Button>
            <Button onClick={doReveal} disabled={reason.trim().length < 5}>
              <Eye className="h-4 w-4" /> Reveal
            </Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-zinc-600">Full identifiers are only shown with a reason. This is recorded in the audit log with your name.</p>
        <Label>Reason</Label>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Comparing with bank letter" autoFocus />
      </Modal>
    </div>
  );
}

export default function OpsApplicationPage() {
  return (
    <AppShell roles={["operator", "admin"]} wide>
      <Suspense fallback={<PageLoader />}>
        <Detail />
      </Suspense>
    </AppShell>
  );
}
