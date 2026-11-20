"use client";

import { XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Label, Modal, Textarea } from "@/components/ui";
import { api } from "@/lib/api";

// A merchant can withdraw any time before approval (mirrors MERCHANT_WITHDRAWABLE in the API).
export const WITHDRAWABLE = new Set(["DRAFT", "SUBMITTED", "PROCESSING_DOCUMENTS", "AWAITING_MERCHANT", "VERIFYING", "DECISIONING", "MANUAL_REVIEW"]);

export function WithdrawButton({ appId, status, onDone }: { appId: string; status: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const draft = status === "DRAFT";
  if (!WITHDRAWABLE.has(status)) return null;

  async function confirm() {
    setBusy(true);
    try {
      await api(`/applications/${appId}/withdraw`, { method: "POST", json: { reason: reason || null } });
      toast.success(draft ? "Draft discarded" : "Application withdrawn");
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
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} className="text-zinc-500 hover:text-red-700">
        <XCircle className="h-4 w-4" /> {draft ? "Discard draft" : "Withdraw application"}
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={draft ? "Discard this draft?" : "Withdraw this application?"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={confirm} loading={busy}>
              {draft ? "Discard draft" : "Withdraw"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm leading-relaxed text-zinc-600">
            {draft
              ? "Your answers and uploaded documents for this draft will be discarded."
              : "We'll stop all verification and close the application. This can't be undone, but you can start a new application any time."}
          </p>
          {!draft && (
            <div>
              <Label>Reason (optional)</Label>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Tell us why, so we can improve" />
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
