import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { listCustomers } from "../api/customers";
import {
  InvoiceListItem,
  cancelInvoice,
  downloadInvoicePdf,
  getInvoice,
  listInvoices,
} from "../api/invoices";
import AppShell from "../components/AppShell";
import { cardClass, dangerLinkClass, inputClass, linkClass, primaryButtonClass } from "../styles";

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-warning/15 text-warning",
    saved: "bg-success/15 text-success",
    cancelled: "bg-danger/15 text-danger",
  };
  return (
    <span
      className={[
        "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        styles[status] ?? "bg-ink-muted/15 text-ink-muted",
      ].join(" ")}
    >
      {status}
    </span>
  );
}

function moneyFmt(value: string | number): string {
  const n = typeof value === "number" ? value : parseFloat(value);
  return isFinite(n) ? n.toLocaleString("en-IN", { minimumFractionDigits: 2 }) : String(value);
}

export default function InvoiceListPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const queryClient = useQueryClient();

  const { data: invoices = [], isLoading } = useQuery({
    queryKey: ["invoices"],
    queryFn: listInvoices,
  });

  const cancelMutation = useMutation({
    mutationFn: cancelInvoice,
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      queryClient.setQueryData(["invoice", invoice.id], invoice);
    },
  });

  function handleCancel(id: string, invoiceNo: string) {
    if (window.confirm(`Cancel invoice ${invoiceNo}? This cannot be undone.`)) {
      cancelMutation.mutate(id);
    }
  }
  const { data: customers = [] } = useQuery({ queryKey: ["customers", "list"], queryFn: listCustomers });
  const customerNameById = useMemo(() => {
    const map = new Map(customers.map((c) => [c.id, c.name]));
    return map;
  }, [customers]);

  // The list endpoint doesn't include customer_id/name (only invoice_no,
  // date, amount, status) — fetch invoice detail per row to resolve the
  // customer column the design calls for. Fine at v1 scale; would need a
  // backend list-with-customer projection if invoice volume grows.
  const detailQueries = useQueries({
    queries: invoices.map((inv) => ({
      queryKey: ["invoice", inv.id],
      queryFn: () => getInvoice(inv.id),
      staleTime: 60_000,
    })),
  });

  const rows = invoices.map((inv: InvoiceListItem, i: number) => {
    const detail = detailQueries[i]?.data;
    const customerName = detail ? customerNameById.get(detail.customer_id) : undefined;
    return { ...inv, customerName };
  });

  const filtered = rows.filter((r) => {
    const matchesStatus = statusFilter === "all" || r.status === statusFilter;
    const matchesSearch =
      !search ||
      r.invoice_no.toLowerCase().includes(search.toLowerCase()) ||
      (r.customerName ?? "").toLowerCase().includes(search.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  async function handleDownload(id: string, invoiceNo: string) {
    await downloadInvoicePdf(id, invoiceNo);
  }

  return (
    <AppShell title="Sale Invoices">
      <div className={cardClass}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search invoice no. or customer…"
              className={inputClass + " max-w-xs"}
            />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className={inputClass + " w-40"}
            >
              <option value="all">All statuses</option>
              <option value="draft">Draft</option>
              <option value="saved">Saved</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
          <Link to="/invoices/new" className={primaryButtonClass}>
            + New invoice
          </Link>
        </div>

        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-ink-muted">No invoices yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Invoice no.</th>
                  <th className="py-2 pr-3 font-medium">Customer</th>
                  <th className="py-2 pr-3 font-medium">Date</th>
                  <th className="py-2 pr-3 font-medium text-right">Amount</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((inv) => (
                  <tr key={inv.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 tabular-nums">
                      <Link to={`/invoices/${inv.id}/edit`} className={linkClass}>
                        {inv.invoice_no}
                      </Link>
                    </td>
                    <td className="py-2 pr-3">{inv.customerName ?? "…"}</td>
                    <td className="py-2 pr-3 tabular-nums">{inv.invoice_date}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">₹ {moneyFmt(inv.grand_total)}</td>
                    <td className="py-2 pr-3">
                      <StatusBadge status={inv.status} />
                    </td>
                    <td className="py-2 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          type="button"
                          onClick={() => handleDownload(inv.id, inv.invoice_no)}
                          className={linkClass}
                        >
                          Download PDF
                        </button>
                        {inv.status !== "cancelled" && (
                          <button
                            type="button"
                            onClick={() => handleCancel(inv.id, inv.invoice_no)}
                            disabled={cancelMutation.isPending}
                            className={dangerLinkClass + " disabled:opacity-50"}
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
