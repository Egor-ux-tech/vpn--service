"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import type { RoutingCategoryRead, RouteType } from "@/lib/types";

export default function RoutingPage() {
  const { data: categories, error, loading, reload } = useApiData(() =>
    api.get<RoutingCategoryRead[]>("/api/v1/routing/categories"),
  );
  const [categoryForm, setCategoryForm] = useState(false);
  const [ruleForm, setRuleForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleCreateCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api.post("/api/v1/routing/categories", {
        name: form.get("name"),
        description: form.get("description") || null,
      });
      setCategoryForm(false);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create category");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCreateRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api.post("/api/v1/routing/rules", {
        category_id: Number(form.get("category_id")),
        domain: form.get("domain"),
        route_type: form.get("route_type") as RouteType,
      });
      setRuleForm(false);
      (event.target as HTMLFormElement).reset();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to add domain rule");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Smart VPN Routing</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setRuleForm((v) => !v)}
            className="rounded-md border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm font-medium"
          >
            {ruleForm ? "Cancel" : "Add domain rule"}
          </button>
          <button
            onClick={() => setCategoryForm((v) => !v)}
            className="rounded-md bg-neutral-900 dark:bg-white dark:text-neutral-900 text-white px-3 py-1.5 text-sm font-medium"
          >
            {categoryForm ? "Cancel" : "Add category"}
          </button>
        </div>
      </div>

      {formError && <p className="text-sm text-red-600">{formError}</p>}

      {categoryForm && (
        <form
          onSubmit={handleCreateCategory}
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 flex gap-3 items-end"
        >
          <div className="space-y-1 flex-1">
            <label className="text-xs font-medium text-neutral-500">Name</label>
            <input
              name="name"
              required
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
          <div className="space-y-1 flex-1">
            <label className="text-xs font-medium text-neutral-500">Description</label>
            <input
              name="description"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-neutral-900 dark:bg-white dark:text-neutral-900 text-white px-4 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      {ruleForm && categories && (
        <form
          onSubmit={handleCreateRule}
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 flex gap-3 items-end"
        >
          <div className="space-y-1">
            <label className="text-xs font-medium text-neutral-500">Category</label>
            <select
              name="category_id"
              required
              className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            >
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1 flex-1">
            <label className="text-xs font-medium text-neutral-500">Domain</label>
            <input
              name="domain"
              required
              placeholder="youtube.com"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-neutral-500">Route</label>
            <select
              name="route_type"
              defaultValue="vpn"
              className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            >
              <option value="vpn">VPN</option>
              <option value="direct">Direct</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-neutral-900 dark:bg-white dark:text-neutral-900 text-white px-4 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Add
          </button>
        </form>
      )}

      {loading && <p className="text-neutral-500">Loading...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {categories && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {categories.map((category) => (
            <div
              key={category.id}
              className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4"
            >
              <div className="font-medium">{category.name}</div>
              {category.description && (
                <div className="text-sm text-neutral-500">{category.description}</div>
              )}
              <div className="mt-2 text-xs text-neutral-400">
                {category.enabled ? "Enabled" : "Disabled"} catalog category
              </div>
            </div>
          ))}
          {categories.length === 0 && (
            <p className="text-neutral-500 col-span-2">
              No categories yet — add one to start building the Smart VPN catalog.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
