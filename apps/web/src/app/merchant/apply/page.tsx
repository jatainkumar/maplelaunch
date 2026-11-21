"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Building2, Check, CheckCircle2, FileUp, Landmark, Loader2, Sparkles, Store, Users } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/shell";
import { WithdrawButton } from "@/components/withdraw";
import { ConfidenceBadge } from "@/components/status";
import { Badge, Button, Card, Input, Label, PageLoader, Select } from "@/components/ui";
import { API_URL, api, upload } from "@/lib/api";
import { cn, FIELD_LABELS, prettyValue } from "@/lib/format";
import { IS_DEMO } from "@/lib/mode";
import type { AppSummary, Doc, MerchantDetail, Meta, Persona } from "@/lib/types";

const STEPS = ["Business", "Documents", "Details", "Bank account", "Submit"];
const TYPE_ICONS: Record<string, React.ReactNode> = {
  proprietorship: <Store className="h-5 w-5" />,
  partnership: <Users className="h-5 w-5" />,
  private_limited: <Building2 className="h-5 w-5" />,
};
const TYPE_HELP: Record<string, string> = {
  proprietorship: "One owner. Uses the owner's personal PAN.",
  partnership: "Registered firm with a partnership deed.",
  private_limited: "Company registered with the RoC (has a CIN).",
};
const DETAIL_FIELDS = ["legal_name", "trade_name", "contact_name", "phone", "email", "address", "city", "state", "pincode", "monthly_volume", "pan", "gstin", "cin"];
const BANK_FIELDS = ["account_number", "ifsc", "account_holder_name"];
const REQUIRED = new Set(["legal_name", "contact_name", "phone", "address", "city", "state", "pincode", "pan", "account_number", "ifsc", "account_holder_name"]);

type Form = Record<string, string>;

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-8 flex items-center gap-2">
      {STEPS.map((s, i) => (
        <li key={s} className="flex flex-1 items-center gap-2">
          <span
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
              i < step ? "bg-maple-600 text-white" : i === step ? "bg-zinc-900 text-white" : "bg-zinc-200 text-zinc-500",
            )}
          >
            {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
          </span>
          <span className={cn("hidden text-sm font-medium sm:block", i === step ? "text-zinc-900" : "text-zinc-500")}>{s}</span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px flex-1 bg-zinc-200" />}
        </li>
      ))}
    </ol>
  );
}

function FieldRow({ name, form, setForm, detail, type = "text" }: { name: string; form: Form; setForm: (f: Form) => void; detail?: MerchantDetail; type?: string }) {
  const af = detail?.autofill?.[name];
  const usingAi = af && String(af.value) === form[name];
  const low = usingAi && af.confidence < 0.75;
  return (
    <div>
      <Label
        htmlFor={name}
        hint={
          usingAi ? (
            <span className="flex items-center gap-1.5 text-xs font-normal text-zinc-500">
              <Sparkles className="h-3 w-3 text-maple-500" /> from {af.source.toLowerCase()} <ConfidenceBadge value={af.confidence} />
            </span>
          ) : null
        }
      >
        {FIELD_LABELS[name] ?? name}
        {REQUIRED.has(name) && <span className="text-maple-600"> *</span>}
      </Label>
      <Input
        id={name}
        type={type}
        value={form[name] ?? ""}
        onChange={(e) => setForm({ ...form, [name]: e.target.value })}
        className={cn(low && "border-amber-400 bg-amber-50/40")}
      />
      {low && <p className="mt-1 text-xs text-amber-700">The AI wasn&apos;t sure about this one. Please double-check it.</p>}
    </div>
  );
}

function DocSlot({ slot, meta, doc, uploading, onFile }: { slot: string; meta: Meta; doc?: Doc; uploading: boolean; onFile: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const ext = doc?.extraction;
  const reading = !!doc && !ext && !uploading; // uploaded, AI still reading it in the background
  const q = ext?.quality;
  const bad = ext?.error || (q && (q.legible === false || (q.score ?? 1) < 0.6)) || (doc?.detected_type && doc.detected_type !== slot);
  return (
    <Card className={cn("overflow-hidden", bad && "border-amber-300")}>
      <div className="flex items-center gap-4 p-4">
        <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", doc ? (bad ? "bg-amber-50 text-amber-600" : "bg-emerald-50 text-emerald-600") : "bg-zinc-100 text-zinc-400")}>
          {uploading || reading ? <Loader2 className="h-5 w-5 animate-spin" /> : doc ? bad ? <AlertTriangle className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" /> : <FileUp className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-medium text-zinc-900">{meta.documents[slot]?.label}</div>
          <div className="truncate text-sm text-zinc-500">
            {uploading ? "Uploading…" : reading ? `${doc.filename} · reading with AI…` : doc ? doc.filename : meta.documents[slot]?.hint}
          </div>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        />
        <Button variant={doc ? "outline" : "secondary"} size="sm" onClick={() => inputRef.current?.click()} disabled={uploading}>
          {doc ? "Replace" : "Upload"}
        </Button>
      </div>
      {doc && ext && !uploading && (
        <div className="border-t border-zinc-100 bg-zinc-50/60 px-4 py-3">
          {ext.error ? (
            <p className="text-sm text-amber-700">We couldn&apos;t read this automatically ({ext.error}). You can still continue; a person will check it.</p>
          ) : (
            <>
              {bad && (
                <p className="mb-2 text-sm text-amber-700">
                  {doc.detected_type && doc.detected_type !== slot
                    ? `This looks like a ${meta.documents[doc.detected_type]?.label ?? "different document"}.`
                    : `Image quality is low${q?.notes ? `: ${q.notes}` : ""}. A clearer photo will speed things up.`}
                </p>
              )}
              <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
                {Object.entries(ext.fields).map(([k, f]) => (
                  <div key={k} className="flex items-start justify-between gap-3 text-sm">
                    <span className="min-w-0 text-zinc-500">{FIELD_LABELS[k] ?? k}</span>
                    <span className="flex min-w-0 items-start justify-end gap-2 text-right">
                      <span className="font-medium text-zinc-800 [overflow-wrap:anywhere]">{prettyValue(k, f.value)}</span>
                      {f.value && <ConfidenceBadge value={f.confidence} />}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-zinc-400">Read by {ext.model}{ext.latency_ms ? ` in ${(ext.latency_ms / 1000).toFixed(1)}s` : ""}</p>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function Wizard() {
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const id = params.get("id");
  const [step, setStep] = useState(id ? 1 : 0);
  const [type, setType] = useState("proprietorship");
  const [category, setCategory] = useState("retail");
  const [form, setForm] = useState<Form>({});
  const [uploading, setUploading] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [persona, setPersona] = useState("");
  const [ifscInfo, setIfscInfo] = useState<{ found: boolean | null; bank?: string; branch?: string } | null>(null);
  const initialised = useRef(false);

  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/demo/personas"), enabled: IS_DEMO });
  const detail = useQuery({
    queryKey: ["app", id],
    queryFn: () => api<MerchantDetail>(`/applications/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.documents.some((x) => !x.extraction) ? 1500 : false),
  });
  const d = detail.data;

  useEffect(() => {
    if (d && d.application.status !== "DRAFT") router.replace(`/merchant/application/?id=${d.application.id}`);
  }, [d, router]);

  // Seed the form once from saved data, then AI autofill for anything still empty.
  useEffect(() => {
    if (!d || initialised.current) return;
    initialised.current = true;
    const next: Form = {};
    for (const k of [...DETAIL_FIELDS, ...BANK_FIELDS]) {
      const v = d.data[k];
      if (v !== null && v !== undefined && typeof v !== "object") next[k] = String(v);
    }
    for (const [k, af] of Object.entries(d.autofill)) if (!next[k]) next[k] = String(af.value);
    setForm(next);
  }, [d]);

  const docsBySlot = useMemo(() => Object.fromEntries((d?.documents ?? []).map((x) => [x.slot, x])), [d]);
  const required = d?.required_documents ?? [];
  const allDocs = required.every((s) => docsBySlot[s]);
  const matchingPersonas = (personas.data ?? []).filter((p) => p.business_type === d?.application.business_type);

  // Documents are read in the background; whenever new values arrive, fill the fields that are still empty.
  useEffect(() => {
    if (!d || !initialised.current) return;
    setForm((f) => {
      let changed = false;
      const n = { ...f };
      for (const [k, af] of Object.entries(d.autofill)) {
        if (!n[k]) {
          n[k] = String(af.value);
          changed = true;
        }
      }
      return changed ? n : f;
    });
  }, [d]);

  async function create() {
    setBusy(true);
    try {
      const app = await api<AppSummary>("/applications", { method: "POST", json: { business_type: type, category } });
      router.replace(`/merchant/apply/?id=${app.id}`);
      setStep(1);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile(slot: string, file: File) {
    setUploading((u) => ({ ...u, [slot]: true }));
    try {
      const fd = new FormData();
      fd.append("slot", slot);
      fd.append("file", file);
      await upload(`/applications/${id}/documents`, fd);
      await qc.invalidateQueries({ queryKey: ["app", id] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading((u) => ({ ...u, [slot]: false }));
    }
  }

  async function useSamples() {
    const p = matchingPersonas.find((x) => x.key === persona);
    if (!p) return;
    await Promise.all(
      Object.entries(p.files)
        .filter(([slot]) => required.includes(slot))
        .map(async ([slot, filename]) => {
          const res = await fetch(`${API_URL}/demo/samples/${p.key}/${filename}`);
          const blob = await res.blob();
          await uploadFile(slot, new File([blob], filename, { type: blob.type }));
        }),
    );
    // Fields that aren't on any document (contact details, volume) come from the persona.
    setForm((f) => {
      const n = { ...f };
      for (const k of ["contact_name", "phone", "email", "city", "pincode", "monthly_volume", "address", "state"]) {
        if (!n[k] && p.form[k] !== undefined) n[k] = String(p.form[k]);
      }
      return n;
    });
    if (p.category !== d?.application.category) await api(`/applications/${id}`, { method: "PATCH", json: { category: p.category } });
    toast.success(`Sample documents for “${p.title}” uploaded`);
  }

  async function save(fields: string[]) {
    const body: Record<string, string | number> = {};
    for (const k of fields) {
      if (form[k] === undefined || form[k] === "") continue;
      body[k] = k === "monthly_volume" ? Number(String(form[k]).replace(/[^\d]/g, "")) || 0 : form[k];
    }
    await api(`/applications/${id}`, { method: "PATCH", json: body });
    await qc.invalidateQueries({ queryKey: ["app", id] });
  }

  async function next(fields: string[]) {
    const missing = fields.filter((k) => REQUIRED.has(k) && !form[k]);
    if (d?.application.business_type === "private_limited" && fields.includes("cin") && !form.cin) missing.push("cin");
    if (missing.length) {
      toast.error(`Please fill in: ${missing.map((m) => FIELD_LABELS[m] ?? m).join(", ")}`);
      return;
    }
    setBusy(true);
    try {
      await save(fields);
      setStep((s) => s + 1);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function checkIfsc(code: string) {
    if (code.length !== 11) return setIfscInfo(null);
    try {
      setIfscInfo(await api(`/ifsc/${code}`));
    } catch {
      setIfscInfo({ found: null });
    }
  }

  async function submit() {
    setBusy(true);
    try {
      await api(`/applications/${id}/submit`, { method: "POST", json: { consent } });
      toast.success("Application submitted. Verification has started");
      // The status page shares this cache entry; drop the draft copy so it never flashes "Draft".
      qc.removeQueries({ queryKey: ["app", id] });
      qc.invalidateQueries({ queryKey: ["my-apps"] });
      router.replace(`/merchant/application/?id=${id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  }

  if (!meta.data || (id && !d)) return <PageLoader />;
  const m = meta.data;

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm text-zinc-500">
        <span>{d ? `${d.application.reference} · draft saved automatically` : "New application"}</span>
        {d && (
          <WithdrawButton
            appId={d.application.id}
            status={d.application.status}
            onDone={() => {
              qc.invalidateQueries({ queryKey: ["my-apps"] });
              router.push("/merchant/");
            }}
          />
        )}
      </div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-zinc-900">Get your business onboarded</h1>
      <Stepper step={step} />

      {step === 0 && (
        <Card className="animate-fade-in p-6">
          <h2 className="font-semibold text-zinc-900">What kind of business is it?</h2>
          <p className="mt-1 text-sm text-zinc-500">This decides which documents we need.</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {Object.entries(m.business_types).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setType(k)}
                className={cn(
                  "rounded-xl border p-4 text-left transition-all",
                  type === k ? "border-maple-500 bg-maple-50/50 ring-2 ring-maple-100" : "border-zinc-200 hover:border-zinc-300",
                )}
              >
                <div className={cn("mb-3", type === k ? "text-maple-600" : "text-zinc-400")}>{TYPE_ICONS[k]}</div>
                <div className="text-sm font-medium text-zinc-900">{label}</div>
                <div className="mt-1 text-xs text-zinc-500">{TYPE_HELP[k]}</div>
              </button>
            ))}
          </div>
          <div className="mt-6 max-w-sm">
            <Label htmlFor="category">What do you sell?</Label>
            <Select id="category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {Object.entries(m.categories).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            {m.high_risk_categories.includes(category) && (
              <p className="mt-2 text-xs text-amber-700">This category always gets a quick human review before approval.</p>
            )}
          </div>
          <div className="mt-6 rounded-lg bg-zinc-50 p-4 text-sm text-zinc-600">
            You&apos;ll need: {m.required_documents[type]?.map((s) => m.documents[s]?.label).join(" · ")}
          </div>
          <div className="mt-6 flex justify-end">
            <Button onClick={create} loading={busy}>
              Continue <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      )}

      {step === 1 && d && (
        <div className="animate-fade-in space-y-4">
          {IS_DEMO && (
          <Card className="flex flex-wrap items-center gap-3 border-dashed bg-maple-50/30 p-4">
            <Sparkles className="h-5 w-5 text-maple-600" />
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-medium text-zinc-900">No documents handy?</div>
              <div className="text-zinc-500">Load a synthetic sample set. Each one triggers a different scenario.</div>
            </div>
            <Select className="w-auto max-w-xs" value={persona} onChange={(e) => setPersona(e.target.value)}>
              <option value="">Choose a sample…</option>
              {matchingPersonas.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.title}
                </option>
              ))}
            </Select>
            <Button variant="outline" size="sm" disabled={!persona || Object.values(uploading).some(Boolean)} onClick={useSamples}>
              Use sample
            </Button>
          </Card>
          )}
          {required.map((slot) => (
            <DocSlot key={slot} slot={slot} meta={m} doc={docsBySlot[slot]} uploading={!!uploading[slot]} onFile={(f) => uploadFile(slot, f)} />
          ))}
          <div className="flex justify-between pt-2">
            <span className="text-sm text-zinc-500">PNG, JPG or PDF · up to 8 MB each</span>
            <Button onClick={() => setStep(2)} disabled={!allDocs || Object.values(uploading).some(Boolean)}>
              Continue <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {step === 2 && d && (
        <Card className="animate-fade-in p-6">
          <h2 className="font-semibold text-zinc-900">Check your details</h2>
          <p className="mt-1 text-sm text-zinc-500">
            We filled in what we could from your documents. Fields marked <Sparkles className="inline h-3 w-3 text-maple-500" /> came from the AI. Please confirm them.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {DETAIL_FIELDS.filter((k) => k !== "cin" || d.application.business_type === "private_limited").map((k) => (
              <div key={k} className={cn(k === "address" && "sm:col-span-2")}>
                <FieldRow name={k} form={form} setForm={setForm} detail={d} type={k === "email" ? "email" : "text"} />
              </div>
            ))}
          </div>
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <Button onClick={() => next(DETAIL_FIELDS)} loading={busy}>
              Continue <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      )}

      {step === 3 && d && (
        <Card className="animate-fade-in p-6">
          <h2 className="flex items-center gap-2 font-semibold text-zinc-900">
            <Landmark className="h-5 w-5 text-zinc-400" /> Where should we send your settlements?
          </h2>
          <p className="mt-1 text-sm text-zinc-500">We&apos;ll confirm the account with a ₹1 penny-drop. The account name should match your business.</p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <FieldRow name="account_number" form={form} setForm={setForm} detail={d} />
            <div>
              <FieldRow
                name="ifsc"
                form={form}
                detail={d}
                setForm={(f) => {
                  setForm({ ...f, ifsc: (f.ifsc ?? "").toUpperCase() });
                  checkIfsc((f.ifsc ?? "").toUpperCase());
                }}
              />
              {ifscInfo && (
                <p className={cn("mt-1 text-xs", ifscInfo.found ? "text-emerald-700" : ifscInfo.found === false ? "text-red-600" : "text-zinc-500")}>
                  {ifscInfo.found ? `${ifscInfo.bank} · ${ifscInfo.branch}` : ifscInfo.found === false ? "This IFSC doesn't exist" : "Couldn't look up this IFSC right now"}
                </p>
              )}
            </div>
            <div className="sm:col-span-2">
              <FieldRow name="account_holder_name" form={form} setForm={setForm} detail={d} />
            </div>
          </div>
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <Button onClick={() => next(BANK_FIELDS)} loading={busy}>
              Continue <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      )}

      {step === 4 && d && (
        <Card className="animate-fade-in p-6">
          <h2 className="font-semibold text-zinc-900">Review and submit</h2>
          <div className="mt-5 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
            {[...DETAIL_FIELDS, ...BANK_FIELDS]
              .filter((k) => form[k])
              .map((k) => (
                <div key={k} className="flex justify-between gap-3 border-b border-zinc-100 pb-2">
                  <span className="text-zinc-500">{FIELD_LABELS[k]}</span>
                  <span className="truncate text-right font-medium text-zinc-900">{form[k]}</span>
                </div>
              ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {required.map((s) => (
              <Badge key={s} tone="green">
                <Check className="h-3 w-3" /> {m.documents[s]?.label}
              </Badge>
            ))}
          </div>
          <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-lg border border-zinc-200 p-4 text-sm text-zinc-700">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-maple-600" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              I confirm these details are correct and I consent to MapleLaunch verifying my PAN, GST registration and bank
              account with third-party providers, and running a risk assessment. My identifiers are stored encrypted and
              used only for onboarding.
            </span>
          </label>
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(3)}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <Button onClick={submit} loading={busy} disabled={!consent}>
              Submit application
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function ApplyPage() {
  return (
    <AppShell roles={["merchant"]}>
      <Suspense fallback={<PageLoader />}>
        <Wizard />
      </Suspense>
    </AppShell>
  );
}
