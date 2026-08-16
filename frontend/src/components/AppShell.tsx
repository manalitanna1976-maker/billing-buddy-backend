import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { getBusiness } from "../api/business";
import { useAuthStore } from "../store/authStore";

interface NavItem {
  to: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/business", label: "Business profile" },
  { to: "/bank-accounts", label: "Bank accounts" },
  { to: "/customers", label: "Customers" },
  { to: "/", label: "Invoices" },
];

function navLinkClass({ isActive }: { isActive: boolean }) {
  return [
    "block rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary text-primary-fg"
      : "text-ink-muted hover:bg-primary/10 hover:text-ink",
  ].join(" ");
}

export default function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const navigate = useNavigate();
  const email = useAuthStore((s) => s.email);
  const { data: business } = useQuery({ queryKey: ["business"], queryFn: getBusiness });

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-fg font-serif text-sm font-semibold">
            B
          </div>
          <span className="font-serif text-lg font-semibold text-ink">Billing Buddy</span>
        </div>

        <nav className="flex flex-1 flex-col gap-1 px-3">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={navLinkClass}>
              {item.label}
            </NavLink>
          ))}

          <button
            type="button"
            onClick={() => navigate("/invoices/new")}
            className="mt-3 rounded-md bg-primary px-3 py-2 text-left text-sm font-semibold text-primary-fg hover:opacity-90"
          >
            + New invoice
          </button>
        </nav>

        <button
          type="button"
          onClick={() => navigate("/profile")}
          className="flex items-center gap-2 border-t border-border px-4 py-3 text-left hover:bg-primary/5"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gold text-gold-fg text-xs font-semibold">
            {(email ?? business?.name ?? "?").slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium text-ink">{email ?? "Account"}</div>
            <div className="truncate text-[11px] text-ink-muted">View profile</div>
          </div>
        </button>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-surface px-8 py-4">
          <h1 className="font-serif text-xl font-semibold text-ink">{title}</h1>
          {business && (
            <span className="rounded-full border border-border bg-paper px-3 py-1 text-xs font-medium text-ink-muted">
              {business.name}
            </span>
          )}
        </header>
        <main className="flex-1 px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
