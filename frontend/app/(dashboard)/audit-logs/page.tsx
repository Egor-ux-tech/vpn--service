"use client";

import { api } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import type { AuditLogRead } from "@/lib/types";

export default function AuditLogsPage() {
  const { data, error, loading } = useApiData(() =>
    api.get<AuditLogRead[]>("/api/v1/admin/audit-logs?limit=200"),
  );

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Audit logs</h1>

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Time</th>
                <th className="px-4 py-2 font-medium">Admin</th>
                <th className="px-4 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">Target</th>
                <th className="px-4 py-2 font-medium">Metadata</th>
              </tr>
            </thead>
            <tbody>
              {data.map((log) => (
                <tr key={log.id} className="border-t border-neutral-200 dark:border-neutral-800 align-top">
                  <td className="px-4 py-2 whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">{log.admin_id ? `#${log.admin_id}` : "system"}</td>
                  <td className="px-4 py-2 font-mono text-xs">{log.action}</td>
                  <td className="px-4 py-2">
                    {log.target_type}
                    {log.target_id ? ` #${log.target_id}` : ""}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-neutral-500">
                    {Object.keys(log.metadata_json).length > 0
                      ? JSON.stringify(log.metadata_json)
                      : "—"}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-neutral-500">
                    No audit log entries yet.
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
