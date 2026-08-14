"use client";

import { api, ApiError } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import { StatusBadge } from "@/components/StatusBadge";
import type { PaymentRead } from "@/lib/types";
import { useState } from "react";

export default function PaymentsPage() {
  const { data, error, loading, reload } = useApiData(() =>
    api.get<PaymentRead[]>("/api/v1/payments?limit=200"),
  );
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function refund(payment: PaymentRead) {
    setBusyId(payment.id);
    setActionError(null);
    try {
      await api.post(`/api/v1/payments/${payment.id}/refund`);
      reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Refund failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Payments</h1>

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}
      {actionError && <p className="text-red-600">{actionError}</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">ID</th>
                <th className="px-4 py-2 font-medium">User</th>
                <th className="px-4 py-2 font-medium">Provider</th>
                <th className="px-4 py-2 font-medium">Amount</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {data.map((payment) => (
                <tr key={payment.id} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="px-4 py-2">{payment.id}</td>
                  <td className="px-4 py-2">#{payment.user_id}</td>
                  <td className="px-4 py-2">{payment.provider}</td>
                  <td className="px-4 py-2">
                    {payment.amount} {payment.currency}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={payment.status} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    {payment.status === "succeeded" && (
                      <button
                        onClick={() => refund(payment)}
                        disabled={busyId === payment.id}
                        className="text-sm font-medium text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white disabled:opacity-50"
                      >
                        Refund
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-neutral-500">
                    No payments yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
