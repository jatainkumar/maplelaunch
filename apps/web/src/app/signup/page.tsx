"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Logo } from "@/components/logo";
import { useAuth } from "@/components/providers";
import { Button, Card, Input, Label } from "@/components/ui";
import { api, type User } from "@/lib/api";

export default function SignupPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ access_token: string; user: User }>("/auth/signup", { method: "POST", json: form });
      signIn(r.access_token, r.user);
      router.replace("/merchant/");
    } catch (err) {
      toast.error((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 py-12">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex justify-center">
          <Logo />
        </Link>
        <Card className="p-6">
          <h1 className="text-lg font-semibold text-zinc-900">Create your merchant account</h1>
          <p className="mt-1 text-sm text-zinc-500">It takes a minute. You can save your application and come back.</p>
          <form onSubmit={submit} className="mt-5 space-y-4">
            <div>
              <Label htmlFor="name">Your name</Label>
              <Input id="name" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="email">Work email</Label>
              <Input id="email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="password" hint={<span className="text-xs font-normal text-zinc-400">min. 8 characters</span>}>
                Password
              </Label>
              <Input id="password" type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
            <Button type="submit" className="w-full" loading={busy}>
              Create account
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-zinc-500">
            Already registered?{" "}
            <Link href="/login/" className="font-medium text-maple-700 hover:underline">
              Sign in
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
