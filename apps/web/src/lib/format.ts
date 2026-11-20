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
