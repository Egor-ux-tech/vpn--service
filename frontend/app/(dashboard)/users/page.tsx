"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import { StatusBadge } from "@/components/StatusBadge";
import type { UserRead, UserStatus } from "@/lib/types";

export default function UsersPage() {
  const [search, setSearch] = useState("");
  const { data, error, loading, reload } = useApiData(() =>
    api.get<UserRead[]>("/api/v1/users?limit=200"),
  );
  const [busyId, setBusyId] = useState<number | null>(null);

  const filtered = (data ?? []).filter((user) => {
    if (!search.trim()) return true;
    const needle = search.toLowerCase();
    return (
      user.username?.toLowerCase().includes(needle) ||
      String(user.telegram_id).includes(needle) ||
      String(user.id).includes(needle)
    );
  });

  async function toggleBlock(user: UserRead) {
    const nextStatus: UserStatus = user.status === "active" ? "blocked" : "active";
    setBusyId(user.id);
    try {
      await api.patch(`/api/v1/users/${user.id}/status`, { status: nextStatus });
      reload();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Users</h1>
        <input
          placeholder="Search by username, telegram id, or id..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-72 rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
        />
      </div>

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">ID</th>
                <th className="px-4 py-2 font-medium">Telegram ID</th>
                <th className="px-4 py-2 font-medium">Username</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Joined</th>
                <th className="px-4 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((user) => (
                <tr key={user.id} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="px-4 py-2">{user.id}</td>
                  <td className="px-4 py-2">{user.telegram_id}</td>
                  <td className="px-4 py-2">{user.username ? `@${user.username}` : "—"}</td>
                  <td className="px-4 py-2">
                    <StatusBadge status={user.status} />
                  </td>
                  <td className="px-4 py-2">{new Date(user.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => toggleBlock(user)}
                      disabled={busyId === user.id}
                      className="text-sm font-medium text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white disabled:opacity-50"
                    >
                      {user.status === "active" ? "Block" : "Unblock"}
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-neutral-500">
                    No users found.
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
