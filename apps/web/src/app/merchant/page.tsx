"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bell, FileText, Plus } from "lucide-react";
import Link from "next/link";

import { AppShell, PageTitle } from "@/components/shell";
import { StatusBadge } from "@/components/status";
import { Button, Card, CardHeader, Empty, PageLoader } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import type { AppSummary, Notification } from "@/lib/types";

function Dashboard() {
  const apps = useQuery({ queryKey: ["my-apps"], queryFn: () => api<AppSummary[]>("/applications"), refetchInterval: 5000 });
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<Notification[]>("/notifications"), refetchInterval: 8000 });

  if (apps.isLoading) return <PageLoader />;
  const list = (apps.data ?? []).filter((a) => a.status !== "WITHDRAWN" || a.submitted_at);

  return (
    <>
      <PageTitle
        title="Your applications"
        subtitle="Start a new application or pick up where you left off."
        action={
          <Link href="/merchant/apply/">
            <Button>
              <Plus className="h-4 w-4" /> New application
            </Button>
          </Link>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {list.length === 0 ? (
            <Card>
              <Empty icon={<FileText className="h-10 w-10" />} title="No applications yet">
                Have your PAN, GST certificate and a cancelled cheque handy. MapleLaunch reads them for you.
                <div className="mt-4">
                  <Link href="/merchant/apply/">
                    <Button>Start application</Button>
                  </Link>
                </div>
              </Empty>
            </Card>
          ) : (
            list.map((a) => (
              <Link key={a.id} href={a.status === "DRAFT" ? `/merchant/apply/?id=${a.id}` : `/merchant/application/?id=${a.id}`}>
                <Card className="group flex items-center gap-4 p-4 transition-shadow hover:shadow-md">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-maple-50 font-semibold text-maple-700">
                    {(a.trade_name || a.legal_name || "?").slice(0, 1).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium text-zinc-900">{a.trade_name || a.legal_name || "Untitled business"}</span>
                      <StatusBadge status={a.status} label={a.status_label} />
                      {a.payouts_on_hold && <StatusBadge status="AWAITING_MERCHANT" label="payouts on hold" />}
                    </div>
                    <div className="mt-0.5 text-sm text-zinc-500">
                      {a.reference} · {a.business_type_label} · updated {ago(a.updated_at)}
                      {a.mid && <span className="ml-1 font-medium text-emerald-700">· MID {a.mid}</span>}
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-zinc-300 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-500" />
                </Card>
              </Link>
            ))
          )}
        </div>
        <Card className="h-fit">
          <CardHeader title="Inbox" icon={<Bell className="h-4 w-4" />} />
          <div className="max-h-[480px] divide-y divide-zinc-100 overflow-y-auto">
            {(inbox.data ?? []).length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No messages yet.</p>}
            {(inbox.data ?? []).slice(0, 20).map((n) => (
              <div key={n.id} className="px-5 py-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-zinc-900">{n.title}</p>
                  <span className="shrink-0 text-xs text-zinc-400">{ago(n.created_at)}</span>
                </div>
                <p className="mt-1 line-clamp-3 whitespace-pre-line text-sm text-zinc-600">{n.body}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}

export default function MerchantHome() {
  return (
    <AppShell roles={["merchant"]}>
      <Dashboard />
    </AppShell>
  );
}
