"use client";

import { FlaskConical, LayoutDashboard, LogOut, ScrollText, ShieldCheck, Store } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Logo } from "@/components/logo";
import { useAuth } from "@/components/providers";
import { PageLoader } from "@/components/ui";
import type { User } from "@/lib/api";
import { cn } from "@/lib/format";
import { IS_DEMO } from "@/lib/mode";

const NAV: { href: string; label: string; icon: ReactNode; roles: User["role"][] }[] = [
  { href: "/merchant/", label: "My applications", icon: <Store className="h-4 w-4" />, roles: ["merchant"] },
  { href: "/ops/", label: "Onboarding queue", icon: <LayoutDashboard className="h-4 w-4" />, roles: ["operator", "admin"] },
  { href: "/admin/lab/", label: IS_DEMO ? "Scenario lab" : "Background jobs", icon: <FlaskConical className="h-4 w-4" />, roles: ["operator", "admin"] },
  { href: "/admin/policy/", label: "Policy", icon: <ScrollText className="h-4 w-4" />, roles: ["operator", "admin"] },
];

export function DemoBanner() {
  if (!IS_DEMO) return null;
  return (
    <div className="bg-zinc-900 px-4 py-1.5 text-center text-xs text-zinc-300">
      Demo environment · use <span className="font-medium text-white">synthetic documents only</span>. Uploads are
      processed by free-tier AI services. Verification providers are simulated.
    </div>
  );
}

export function AppShell({ roles, children, wide }: { roles: User["role"][]; children: ReactNode; wide?: boolean }) {
  const { user, ready, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace(`/login/?next=${encodeURIComponent(pathname)}`);
    else if (!roles.includes(user.role)) router.replace(user.role === "merchant" ? "/merchant/" : "/ops/");
  }, [ready, user, roles, router, pathname]);

  if (!ready || !user || !roles.includes(user.role)) return <PageLoader />;

  return (
    <div className="flex min-h-screen flex-col">
      <DemoBanner />
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/90 backdrop-blur">
        <div className={cn("mx-auto flex h-14 items-center gap-6 px-4 sm:px-6", wide ? "max-w-7xl" : "max-w-6xl")}>
          <Link href={user.role === "merchant" ? "/merchant/" : "/ops/"}>
            <Logo />
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  pathname.startsWith(n.href.replace(/\/$/, "")) ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:text-zinc-900",
                )}
              >
                {n.icon}
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-sm font-medium leading-tight text-zinc-900">{user.name || user.email}</div>
              <div className="flex items-center justify-end gap-1 text-xs capitalize text-zinc-500">
                {user.role !== "merchant" && <ShieldCheck className="h-3 w-3" />}
                {user.role}
              </div>
            </div>
            <button
              onClick={() => {
                signOut();
                router.replace("/login/");
              }}
              className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-zinc-100 px-4 py-1 md:hidden">
          {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
            <Link key={n.href} href={n.href} className="whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium text-zinc-600">
              {n.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className={cn("mx-auto w-full flex-1 px-4 py-6 sm:px-6 sm:py-8", wide ? "max-w-7xl" : "max-w-6xl")}>{children}</main>
    </div>
  );
}

export function PageTitle({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
