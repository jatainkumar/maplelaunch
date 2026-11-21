export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "-";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

// "in about 23 hours", "in 40 min"; null once the moment has passed.
export function until(iso: string | null | undefined, now: number = Date.now()): string | null {
  if (!iso) return null;
  const s = (new Date(iso).getTime() - now) / 1000;
  if (s <= 0) return null;
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))} min`;
  const h = Math.round(s / 3600);
  return h < 48 ? `in about ${h} hour${h === 1 ? "" : "s"}` : `in about ${Math.round(h / 24)} days`;
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function duration(minutes: number | null | undefined): string {
  if (minutes == null) return "-";
  if (minutes < 1) return `${Math.round(minutes * 60)}s`;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "";
  return code.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const FIELD_LABELS: Record<string, string> = {
  legal_name: "Legal name",
  trade_name: "Trade name",
  contact_name: "Contact person",
  phone: "Mobile number",
  email: "Email",
  address: "Business address",
  city: "City",
  state: "State",
  pincode: "PIN code",
  monthly_volume: "Expected monthly volume (₹)",
  pan: "PAN",
  gstin: "GSTIN",
  cin: "CIN",
  account_number: "Account number",
  ifsc: "IFSC",
  account_holder_name: "Account holder name",
  bank_name: "Bank",
  pan_number: "PAN",
  name: "Name",
  date_of_birth: "Date of birth / incorporation",
  constitution: "Constitution",
  registration_date: "Registration date",
  company_name: "Company name",
  incorporation_date: "Incorporation date",
  firm_name: "Firm name",
  partners: "Partners",
  execution_date: "Executed on",
  bank: "Bank details",
};

// ---- Displaying values read from documents ----------------------------------------------------------------------
const DATE_FIELDS = new Set(["date_of_birth", "registration_date", "incorporation_date", "execution_date"]);
const ID_FIELDS = new Set(["pan_number", "pan", "gstin", "ifsc", "cin", "account_number"]);
const SMALL_WORDS = new Set(["of", "and", "the", "for", "in", "at", "on", "to", "by"]);
const KEEP_UPPER = new Set(["ICICI", "HDFC", "SBI", "IDFC", "IDBI", "PNB", "UCO", "AU", "RBL", "LLP", "HUF", "MG", "NH", "UPI"]);

function capWord(word: string): string {
  const lower = word.toLowerCase();
  if (/^\d/.test(lower)) return lower; // 5TH -> 5th
  return lower.replace(/[a-z]/, (c) => c.toUpperCase());
}

/** 'KUMAR CHAI CORNER' -> 'Kumar Chai Corner'. Mixed-case text and well-known acronyms are left alone. */
export function prettyText(value: string): string {
  if (!value || value !== value.toUpperCase() || !/[A-Z]/.test(value)) return value;
  return value
    .split(/\s+/)
    .map((w, i) => {
      const letters = w.replace(/[^A-Za-z]/g, "");
      if (KEEP_UPPER.has(letters)) return w;
      if (i > 0 && SMALL_WORDS.has(letters.toLowerCase())) return w.toLowerCase();
      return capWord(w);
    })
    .join(" ");
}

/** Format an extracted value for display: readable dates, IDs in capitals, names and addresses in normal case. */
export function prettyValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  const v = String(value);
  if (ID_FIELDS.has(field)) return v.toUpperCase();
  if (DATE_FIELDS.has(field) && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
    const d = new Date(`${v}T00:00:00`);
    return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  }
  return prettyText(v);
}
