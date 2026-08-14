"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import { StatusBadge } from "@/components/StatusBadge";
import type { VPNServerRead, VPNServerStatus } from "@/lib/types";

const STATUS_OPTIONS: VPNServerStatus[] = ["online", "degraded", "offline", "maintenance"];

export default function ServersPage() {
  const { data, error, loading, reload } = useApiData(() =>
    api.get<VPNServerRead[]>("/api/v1/servers"),
  );
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function updateStatus(server: VPNServerRead, status: VPNServerStatus) {
    await api.patch(`/api/v1/servers/${server.id}`, { status });
    reload();
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);

    try {
      await api.post("/api/v1/servers", {
        name: form.get("name"),
        country: form.get("country"),
        city: form.get("city") || null,
        hostname: form.get("hostname"),
        agent_base_url: form.get("agent_base_url"),
        public_key: form.get("public_key"),
        endpoint: form.get("endpoint"),
        internal_network: form.get("internal_network"),
        capacity: Number(form.get("capacity")),
      });
      setShowForm(false);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create server");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Servers</h1>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-neutral-900 dark:bg-white dark:text-neutral-900 text-white px-3 py-1.5 text-sm font-medium"
        >
          {showForm ? "Cancel" : "Add server"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 grid grid-cols-2 gap-3"
        >
          <Field name="name" label="Name" required />
          <Field name="country" label="Country" required />
          <Field name="city" label="City" />
          <Field name="hostname" label="Hostname" required />
          <Field name="agent_base_url" label="Agent base URL" required placeholder="https://1.2.3.4:8800" />
          <Field name="public_key" label="Server public key" required />
          <Field name="endpoint" label="WireGuard endpoint" required placeholder="1.2.3.4:51820" />
          <Field name="internal_network" label="Internal network" required placeholder="10.66.0.0/24" />
          <Field name="capacity" label="Capacity" type="number" defaultValue="100" required />
          <div className="col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-neutral-900 dark:bg-white dark:text-neutral-900 text-white px-4 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create"}
            </button>
            {formError && <p className="text-sm text-red-600">{formError}</p>}
          </div>
        </form>
      )}

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {data && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Location</th>
                <th className="px-4 py-2 font-medium">Endpoint</th>
                <th className="px-4 py-2 font-medium">Load</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((server) => (
                <tr key={server.id} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="px-4 py-2">{server.name}</td>
                  <td className="px-4 py-2">
                    {server.country}
                    {server.city ? `, ${server.city}` : ""}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{server.endpoint}</td>
                  <td className="px-4 py-2">
                    {server.current_load}/{server.capacity}
                  </td>
                  <td className="px-4 py-2">
                    <select
                      value={server.status}
                      onChange={(e) => updateStatus(server, e.target.value as VPNServerStatus)}
                      className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-2 py-1 text-xs"
                    >
                      {STATUS_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                    <span className="ml-2 align-middle">
                      <StatusBadge status={server.status} />
                    </span>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-neutral-500">
                    No servers yet.
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

function Field({
  name,
  label,
  type = "text",
  required = false,
  placeholder,
  defaultValue,
}: {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  placeholder?: string;
  defaultValue?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={name} className="text-xs font-medium text-neutral-500">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        required={required}
        placeholder={placeholder}
        defaultValue={defaultValue}
        className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
      />
    </div>
  );
}
