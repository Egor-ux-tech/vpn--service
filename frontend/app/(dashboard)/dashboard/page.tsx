"use client";

import { api } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import { StatCard } from "@/components/StatCard";
import type { DashboardStats } from "@/lib/types";

export default function DashboardPage() {
  const { data, error, loading } = useApiData(() =>
    api.get<DashboardStats>("/api/v1/admin/dashboard"),
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total users" value={data.total_users} />
          <StatCard label="Active subscriptions" value={data.active_subscriptions} />
          <StatCard label="Active devices" value={data.active_devices} />
          <StatCard label="Online servers" value={data.online_servers} />
          <StatCard label="Online peers" value={data.online_peers} />
          <StatCard label="Revenue (30d)" value={`${data.revenue_last_30d.toFixed(2)} RUB`} />
          <StatCard label="Open support tickets" value={data.open_support_tickets} />
        </div>
      )}
    </div>
  );
}
