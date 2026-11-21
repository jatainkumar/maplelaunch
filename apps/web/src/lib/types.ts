export type AppSummary = {
  id: string;
  reference: string;
  status: string;
  status_label: string;
  business_type: string | null;
  business_type_label: string;
  category: string | null;
  category_label: string;
  legal_name: string | null;
  trade_name: string | null;
  risk_score: number | null;
  risk_band: string | null;
  mid: string | null;
  payouts_on_hold: boolean;
  decision: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  persona: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  status_changed_at: string;
  live_at: string | null;
};

export type Field = { value: string | null; confidence: number };

export type Doc = {
  id: string;
  slot: string;
  label: string;
  filename: string;
  mime: string;
  size: number;
  status: string;
  quality: number | null;
  detected_type: string | null;
  is_active: boolean;
  uploaded_at: string;
  extraction: null | {
    fields: Record<string, Field>;
    quality: { score?: number; legible?: boolean; blur?: string; notes?: string; suspicious?: boolean };
    model: string;
    error: string | null;
    latency_ms: number | null;
  };
};

export type InfoItem = { kind: "document" | "field" | "confirm"; key: string; label: string; reason: string; slot?: string };

export type InfoRequest = {
  id: string;
  items: InfoItem[];
  message: string;
  status: string;
  created_by: string;
  due_at: string | null;
  created_at: string;
};

export type Notification = { id: string; title: string; body: string; read: boolean; created_at: string; email_status: string; application_id: string | null };

export type MerchantDetail = {
  application: AppSummary;
  data: Record<string, string | number | null | Record<string, boolean>>;
  required_documents: string[];
  documents: Doc[];
  autofill: Record<string, { value: string; confidence: number; source: string }>;
  checks: { type: string; status: string; attempt: number }[];
  open_request: InfoRequest | null;
  timeline: { at: string; to: string; label: string }[];
  notifications: Notification[];
  can_change_bank: boolean;
};

export type Meta = {
  business_types: Record<string, string>;
  categories: Record<string, string>;
  documents: Record<string, { label: string; hint: string }>;
  required_documents: Record<string, string[]>;
  high_risk_categories: string[];
  status_labels: Record<string, string>;
  demo_accounts?: { role: "merchant" | "operator" | "admin"; name: string; email: string; password: string }[];
  policy_version: number;
};

export type Check = {
  id: string;
  type: string;
  attempt: number;
  status: string;
  is_current: boolean;
  reason_code: string | null;
  result: Record<string, unknown>;
  late: boolean;
  requested_at: string;
  deadline_at: string | null;
  completed_at: string | null;
};

export type OpsRow = AppSummary & {
  open_exceptions: number;
  open_duplicates: number;
  review: null | { priority: string; recommendation: string; kind: string };
  minutes_in_state: number | null;
};

export type OpsDetail = {
  application: AppSummary;
  data: Record<string, string | number | null>;
  risk: { score: number | null; band: string | null; signals: { code: string; weight: number }[]; explanation: string | null };
  documents: Doc[];
  validations: { rule: string; outcome: string; blocking: boolean; field: string | null; slot: string | null; message: string }[];
  checks: Check[];
  callbacks: { provider: string; event_id: string; outcome: string; status: string; duplicates: number; received_at: string }[];
  transitions: { from: string | null; to: string; actor: string; reason: string | null; at: string }[];
  audit: { id: number; actor: string; action: string; details: Record<string, unknown>; at: string; hash: string }[];
  reviews: {
    id: string; kind: string; status: string; summary: string; reason_codes: string[]; recommendation: string;
    priority: string; decision: string | null; decision_note: string | null; assignee: string | null; created_at: string;
  }[];
  decisions: { action: string; reasoning: string; model: string; used_fallback: boolean; rules_action: string | null; at: string; guardrail: { refusals?: { tool: string; error: string }[] } }[];
  duplicates: { id: string; matched_application_id: string; matched_reference: string; matched_status: string; matched_on: string[]; score: number }[];
  info_requests: InfoRequest[];
  exceptions: { id: string; kind: string; severity: string; message: string; status: string; created_at: string }[];
  audit_chain: { valid: boolean; entries: number; head?: string; broken_at?: number };
  waiting_for: string | null;
};

export type Persona = {
  key: string;
  title: string;
  story: string;
  business_type: string;
  category: string;
  form: Record<string, string | number>;
  files: Record<string, string>;
  fix_files: Record<string, string>;
  scenarios: Record<string, string>;
};
