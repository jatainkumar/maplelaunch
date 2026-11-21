"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Bell, Check, CheckCircle2, FileUp, Landmark, Loader2, PartyPopper, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/shell";
import { StatusBadge } from "@/components/status";
import { Badge, Button, Card, CardHeader, Input, Label, Modal, PageLoader, Textarea } from "@/components/ui";
import { WithdrawButton } from "@/components/withdraw";
import { api, upload } from "@/lib/api";
import { ago, cn, dateTime, FIELD_LABELS } from "@/lib/format";
import { IS_DEMO } from "@/lib/mode";
import type { InfoItem, MerchantDetail, Persona } from "@/lib/types";

const MESSAGES: Record<string, [string, string]> = {
  SUBMITTED: ["Application received", "We're getting started on your verification."],
  PROCESSING_DOCUMENTS: ["Reading your documents", "Our AI is extracting and cross-checking your details."],
  AWAITING_MERCHANT: ["We need something from you", "Please take a look at the request below so we can continue."],
  VERIFYING: ["Verifying your business", "We're checking your PAN, GST and bank account with our partners. This usually takes under a minute."],
  DECISIONING: ["Almost there", "All checks are in. We're making a decision."],
  MANUAL_REVIEW: ["A specialist is reviewing your application", "Some details need a human look. No action is needed from you right now."],
  APPROVED: ["Approved!", "We're creating your merchant ID."],
  PROVISIONING: ["Approved! Setting up your account", "Creating your merchant ID."],
  PROVISIONING_FAILED: ["Approved: merchant ID on its way", "Creating your merchant ID is taking longer than usual. Our team is on it."],
  LIVE: ["You're live!", "You can start accepting payments."],
  REJECTED: ["We couldn't approve this application", "See the reason below. Contact support if you think this is a mistake."],
  WITHDRAWN: ["Application withdrawn", "This application is closed. You can start a new one any time."],
};

type StageState = "done" | "current" | "action" | "failed" | "upcoming";
type Stage = { label: string; state: StageState; note?: string };

// Merchant-facing progress: five plain-language stages instead of the internal checks.
function stages(d: MerchantDetail): Stage[] {
  const s = d.application.status;
  const order = ["SUBMITTED", "PROCESSING_DOCUMENTS", "VERIFYING", "DECISIONING", "MANUAL_REVIEW", "APPROVED", "PROVISIONING", "PROVISIONING_FAILED", "LIVE"];
  const at = order.indexOf(s);
  const past = (status: string) => at > order.indexOf(status);
  const anyCheckFailed = d.checks.some((c) => c.status === "FAILED" || c.status === "TIMED_OUT" || c.status === "ERROR");
  const waitingOnDocs = s === "AWAITING_MERCHANT" && !d.checks.length;
  const waitingAfterChecks = s === "AWAITING_MERCHANT" && d.checks.length > 0;

  const docs: StageState = waitingOnDocs ? "action" : s === "SUBMITTED" || s === "PROCESSING_DOCUMENTS" ? "current" : "done";
  const verified: StageState = waitingAfterChecks
    ? "action"
    : s === "VERIFYING"
      ? "current"
      : past("VERIFYING") || s === "REJECTED"
        ? "done"
        : "upcoming";
  const approval: StageState =
    s === "REJECTED" ? "failed" : s === "DECISIONING" || s === "MANUAL_REVIEW" ? "current" : past("MANUAL_REVIEW") ? "done" : "upcoming";
  const live: StageState = s === "LIVE" ? "done" : s === "APPROVED" || s === "PROVISIONING" || s === "PROVISIONING_FAILED" ? "current" : "upcoming";

  return [
    { label: "Submitted", state: "done" },
    { label: "Documents checked", state: docs, note: waitingOnDocs ? "Action needed" : undefined },
    { label: "Business verified", state: verified, note: waitingAfterChecks || (s === "VERIFYING" && anyCheckFailed) ? "Action needed" : "PAN, GST and bank" },
    { label: "Approval", state: approval, note: s === "MANUAL_REVIEW" ? "Final checks" : undefined },
    { label: "You're live", state: live, note: d.application.mid ?? undefined },
  ];
}

function StageDot({ state, n }: { state: StageState; n: number }) {
  const base = "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold";
  if (state === "done") return <span className={cn(base, "bg-emerald-600 text-white")}><Check className="h-4 w-4" /></span>;
  if (state === "failed") return <span className={cn(base, "bg-red-600 text-white")}><X className="h-4 w-4" /></span>;
  if (state === "action") return <span className={cn(base, "bg-amber-500 text-white")}>!</span>;
  if (state === "current")
    return (
      <span className={cn(base, "bg-maple-600 text-white ring-4 ring-maple-100")}>
        <Loader2 className="h-4 w-4 animate-spin" />
      </span>
    );
  return <span className={cn(base, "border-2 border-zinc-200 bg-white text-zinc-400")}>{n}</span>;
}

function Stages({ d }: { d: MerchantDetail }) {
  const list = stages(d);
  return (
    <ol className="flex flex-col gap-4 border-t border-zinc-100 px-6 py-5 sm:flex-row sm:gap-0">
      {list.map((st, i) => (
        <li key={st.label} className="relative flex items-center gap-3 sm:flex-1 sm:flex-col sm:gap-2 sm:text-center">
          {i < list.length - 1 && (
            <span
              aria-hidden
              className={cn(
                "absolute hidden h-0.5 sm:left-1/2 sm:top-4 sm:block sm:w-full",
                st.state === "done" ? "bg-emerald-500" : "bg-zinc-200",
              )}
            />
          )}
          <StageDot state={st.state} n={i + 1} />
          <span className="min-w-0">
            <span className={cn("block text-sm font-medium", st.state === "upcoming" ? "text-zinc-400" : "text-zinc-900")}>{st.label}</span>
            {st.note && (
              <span className={cn("block text-xs", st.state === "action" ? "font-medium text-amber-700" : st.label === "You're live" ? "font-mono text-emerald-700" : "text-zinc-500")}>
                {st.note}
              </span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

function RequestCard({ d, onDone }: { d: MerchantDetail; onDone: () => void }) {
  const req = d.open_request!;
  const [fields, setFields] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<Record<string, boolean>>({});
  const [uploaded, setUploaded] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/demo/personas"), enabled: IS_DEMO && !!d.application.persona });
  const hasFix = !!personas.data?.find((p) => p.key === d.application.persona && Object.keys(p.fix_files).length);
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});

  async function uploadDoc(slot: string, file: File) {
    setBusy(slot);
    try {
      const fd = new FormData();
      fd.append("slot", slot);
      fd.append("file", file);
      await upload(`/applications/${d.application.id}/documents`, fd);
      setUploaded((u) => ({ ...u, [slot]: file.name }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function send() {
    const missingDocs = req.items.filter((i) => i.kind === "document" && !uploaded[i.key]);
    const missingConfirm = req.items.filter((i) => i.kind === "confirm" && !confirm[i.key] && !fields[i.key]);
    if (missingDocs.length || missingConfirm.length) {
      toast.error("Please complete every item in the request first");
      return;
    }
    setBusy("send");
    try {
      await api(`/applications/${d.application.id}/respond`, {
        method: "POST",
        json: { info_request_id: req.id, fields: Object.fromEntries(Object.entries(fields).filter(([, v]) => v)), confirmations: Object.keys(confirm).filter((k) => confirm[k]) },
      });
      toast.success("Thanks! We're picking things up again.");
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function sampleFix() {
    setBusy("fix");
    try {
      await api(`/demo/applications/${d.application.id}/apply-fix`, { method: "POST" });
      toast.success("Sample fix uploaded");
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const fieldInputs = (item: InfoItem) => {
    if (item.key === "bank")
      return (
        <div className="grid gap-3 sm:grid-cols-3">
          {["account_number", "ifsc", "account_holder_name"].map((k) => (
            <div key={k}>
              <Label>{FIELD_LABELS[k]}</Label>
              <Input value={fields[k] ?? String(d.data[k] ?? "")} onChange={(e) => setFields({ ...fields, [k]: e.target.value })} />
            </div>
          ))}
        </div>
      );
    return (
      <div className="max-w-sm">
        <Label>{FIELD_LABELS[item.key] ?? item.label}</Label>
        <Input value={fields[item.key] ?? String(d.data[item.key] ?? "")} onChange={(e) => setFields({ ...fields, [item.key]: e.target.value })} />
      </div>
    );
  };

  return (
    <Card className="border-amber-300 ring-4 ring-amber-50">
      <CardHeader
        icon={<AlertTriangle className="h-4 w-4 text-amber-500" />}
        title="We need a little more from you"
        subtitle={req.due_at ? `Please respond by ${dateTime(req.due_at)}` : undefined}
        action={
          hasFix ? (
            <Button size="sm" variant="outline" onClick={sampleFix} loading={busy === "fix"}>
              <Sparkles className="h-3.5 w-3.5" /> Use sample fix
            </Button>
          ) : null
        }
      />
      <div className="space-y-5 p-5">
        <p className="whitespace-pre-line text-sm leading-relaxed text-zinc-700">{req.message}</p>
        {req.items.map((item) => (
          <div key={item.kind + item.key} className="rounded-lg border border-zinc-200 p-4">
            <div className="mb-3">
              <div className="text-sm font-medium text-zinc-900">{item.label}</div>
              <div className="text-sm text-zinc-500">{item.reason}</div>
            </div>
            {item.kind === "document" && (
              <div className="flex items-center gap-3">
                <input
                  ref={(el) => {
                    fileRefs.current[item.key] = el;
                  }}
                  type="file"
                  className="hidden"
                  accept="image/png,image/jpeg,image/webp,application/pdf"
                  onChange={(e) => e.target.files?.[0] && uploadDoc(item.key, e.target.files[0])}
                />
                <Button size="sm" variant="secondary" onClick={() => fileRefs.current[item.key]?.click()} loading={busy === item.key}>
                  <FileUp className="h-4 w-4" /> Upload new file
                </Button>
                {uploaded[item.key] && (
                  <span className="flex items-center gap-1 text-sm text-emerald-700">
                    <CheckCircle2 className="h-4 w-4" /> {uploaded[item.key]}
                  </span>
                )}
              </div>
            )}
            {item.kind === "field" && fieldInputs(item)}
            {item.kind === "confirm" && (
              <div className="space-y-3">
                {fieldInputs(item)}
                <label className="flex items-center gap-2 text-sm text-zinc-700">
                  <input type="checkbox" className="h-4 w-4 accent-maple-600" checked={!!confirm[item.key]} onChange={(e) => setConfirm({ ...confirm, [item.key]: e.target.checked })} />
                  The value above is correct as entered
                </label>
              </div>
            )}
          </div>
        ))}
        <div className="flex justify-end">
          <Button onClick={send} loading={busy === "send"}>
            Send response
          </Button>
        </div>
      </div>
    </Card>
  );
}

function BankChange({ d, onDone }: { d: MerchantDetail; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ account_number: "", ifsc: "", account_holder_name: String(d.data.account_holder_name ?? ""), reason: "" });
  const [busy, setBusy] = useState(false);
  const live = d.application.status === "LIVE";
  async function save() {
    setBusy(true);
    try {
      await api(`/applications/${d.application.id}/bank-change`, { method: "POST", json: f });
      toast.success(live ? "Bank change received. Payouts are paused until the new account is verified" : "Bank details updated. Re-verifying now");
      setOpen(false);
      onDone();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Landmark className="h-4 w-4" /> Change bank account
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Change settlement bank account"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} loading={busy}>
              Submit change
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {live && (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
              For your security, payouts pause until we verify the new account with a penny-drop. This usually takes under a minute.
            </p>
          )}
          {(["account_number", "ifsc", "account_holder_name"] as const).map((k) => (
            <div key={k}>
              <Label>{FIELD_LABELS[k]}</Label>
              <Input value={f[k]} onChange={(e) => setF({ ...f, [k]: k === "ifsc" ? e.target.value.toUpperCase() : e.target.value })} />
            </div>
          ))}
          <div>
            <Label>Reason (optional)</Label>
            <Textarea value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          </div>
        </div>
      </Modal>
    </>
  );
}

function Status() {
  const id = useSearchParams().get("id");
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["app", id],
    queryFn: () => api<MerchantDetail>(`/applications/${id}`),
    enabled: !!id,
    refetchInterval: 2500,
  });
  const d = q.data;
  if (!d) return <PageLoader />;
  const a = d.application;
  const [title, sub] = MESSAGES[a.status] ?? [a.status_label, ""];
  const refresh = () => qc.invalidateQueries({ queryKey: ["app", id] });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/merchant/" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800">
        <ArrowLeft className="h-4 w-4" /> All applications
      </Link>
      <Card className="overflow-hidden">
        <div className={cn("px-6 py-6", a.status === "LIVE" ? "bg-gradient-to-r from-emerald-50 to-white" : a.status === "REJECTED" ? "bg-red-50/50" : "bg-gradient-to-r from-maple-50/60 to-white")}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-sm text-zinc-500">
                {a.reference} · {a.business_type_label}
              </div>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-900">{a.trade_name || a.legal_name}</h1>
            </div>
            <div className="flex items-center gap-2">
              {a.payouts_on_hold && <Badge tone="amber">Payouts on hold</Badge>}
              <StatusBadge status={a.status} label={a.status_label} />
            </div>
          </div>
          <div className="mt-5 flex flex-col items-start gap-3 sm:flex-row">
            {a.status === "LIVE" && <PartyPopper className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />}
            <div className="min-w-0 flex-1">
              <div className="font-medium text-zinc-900">{title}</div>
              <div className="text-sm text-zinc-600">{sub}</div>
              {a.status === "REJECTED" && a.decision_reason && <div className="mt-2 text-sm text-red-700">Reason: {a.decision_reason}</div>}
            </div>
            <div className="-ml-3 sm:ml-auto">
              <WithdrawButton appId={a.id} status={a.status} onDone={refresh} />
            </div>
          </div>
          {a.mid && (
            <div className="mt-5 inline-flex items-center gap-3 rounded-lg border border-emerald-200 bg-white px-4 py-2">
              <span className="text-xs uppercase tracking-wide text-zinc-400">Merchant ID</span>
              <span className="font-mono text-lg font-semibold text-emerald-700">{a.mid}</span>
            </div>
          )}
        </div>
        <Stages d={d} />
      </Card>

      {d.open_request && a.status === "AWAITING_MERCHANT" && <RequestCard key={d.open_request.id} d={d} onDone={refresh} />}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader title="Progress" subtitle="Every step is recorded" action={d.can_change_bank ? <BankChange d={d} onDone={refresh} /> : null} />
          <ol className="space-y-3 p-5">
            {d.timeline.map((t, i) => (
              <li key={i} className="flex items-center gap-3 text-sm">
                <span className={cn("h-2 w-2 rounded-full", i === d.timeline.length - 1 ? "bg-maple-500" : "bg-zinc-300")} />
                <span className="text-zinc-800">{t.label}</span>
                <span className="ml-auto text-xs text-zinc-400">{ago(t.at)}</span>
              </li>
            ))}
          </ol>
        </Card>
        <Card>
          <CardHeader title="Messages" icon={<Bell className="h-4 w-4" />} />
          <div className="max-h-80 divide-y divide-zinc-100 overflow-y-auto">
            {d.notifications.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No messages yet.</p>}
            {d.notifications.map((n) => (
              <div key={n.id} className="px-5 py-3">
                <div className="flex justify-between gap-2">
                  <span className="text-sm font-medium text-zinc-900">{n.title}</span>
                  <span className="shrink-0 text-xs text-zinc-400">{ago(n.created_at)}</span>
                </div>
                <p className="mt-1 whitespace-pre-line text-sm text-zinc-600">{n.body}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function ApplicationPage() {
  return (
    <AppShell roles={["merchant"]}>
      <Suspense fallback={<PageLoader />}>
        <Status />
      </Suspense>
    </AppShell>
  );
}
