"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/auth";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/users", label: "Users" },
  { href: "/servers", label: "Servers" },
  { href: "/routing", label: "Routing" },
  { href: "/payments", label: "Payments" },
  { href: "/audit-logs", label: "Audit logs" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  return (
    <aside className="w-56 shrink-0 border-r border-neutral-200 dark:border-neutral-800 flex flex-col h-full">
      <div className="px-4 py-5 text-lg font-semibold">VPN Admin</div>
      <nav className="flex-1 px-2 space-y-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`block rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                  : "text-neutral-700 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="px-4 py-4 border-t border-neutral-200 dark:border-neutral-800">
        <button
          onClick={handleLogout}
          className="w-full text-left text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-white"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
