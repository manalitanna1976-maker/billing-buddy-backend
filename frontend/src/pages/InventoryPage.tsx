import { useState } from "react";

import AppShell from "../components/AppShell";
import ProductsTab from "./inventory/ProductsTab";
import PurchasesTab from "./inventory/PurchasesTab";
import SuppliersTab from "./inventory/SuppliersTab";

type Tab = "products" | "suppliers" | "purchases";

const TABS: { key: Tab; label: string }[] = [
  { key: "products", label: "Products" },
  { key: "suppliers", label: "Suppliers" },
  { key: "purchases", label: "Purchases" },
];

export default function InventoryPage() {
  const [tab, setTab] = useState<Tab>("products");

  return (
    <AppShell title="Inventory">
      <div className="mb-5 flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={[
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-ink-muted hover:text-ink",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "products" && <ProductsTab />}
      {tab === "suppliers" && <SuppliersTab />}
      {tab === "purchases" && <PurchasesTab />}
    </AppShell>
  );
}
