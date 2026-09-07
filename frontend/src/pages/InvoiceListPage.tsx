import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  cancelInvoice,
  downloadInvoicePdf,
  finalizeInvoice,
  listInvoices,
} from "../api/invoices";
import AppShell from "../components/AppShell";
import { getErrorMessage } from "../lib/apiError";
import { cardClass, dangerLinkClass, inputClass, linkClass, primaryButtonClass } from "../styles";

const PAGE_SIZE = 25;

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
  return isFinite(n) ? n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(value);
}

export default function InvoiceListPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(0);
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(0), [debouncedSearch, statusFilter]);

  const { data, isLoading } = useQuery({
    queryKey: ["invoices", { debouncedSearch, statusFilter, page }],
    queryFn: () =>
      listInvoices({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: statusFilter === "all" ? undefined : statusFilter,
        q: debouncedSearch || undefined,
      }),
    placeholderData: (prev) => prev,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["invoices"] });

  const cancelMutation = useMutation({
    mutationFn: cancelInvoice,
    onSuccess: invalidate,
    onError: (e) => setActionError(getErrorMessage(e, "Could not cancel the invoice.")),
  });
  const finalizeMutation = useMutation({
    mutationFn: finalizeInvoice,
    onSuccess: invalidate,
    onError: (e) => setActionError(getErrorMessage(e, "Could not finalize the invoice.")),
  });

  function handleCancel(id: string, invoiceNo: string) {
    setActionError(null);
    if (window.confirm(`Cancel invoice ${invoiceNo}? A cancelled invoice can't be edited or un-cancelled.`)) {
      cancelMutation.mutate(id);
    }
  }
  function handleFinalize(id: string, invoiceNo: string) {
    setActionError(null);
    if (window.confirm(`Finalize invoice ${invoiceNo}? Once finalized it's locked and can only be cancelled.`)) {
      finalizeMutation.mutate(id);
    }
  }

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

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

        {actionError && <p className="mb-3 text-sm text-danger">{actionError}</p>}

        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-ink-muted">No invoices found.</p>
        ) : (
          <>
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
                  {rows.map((inv) => (
                    <tr key={inv.id} className="border-b border-border last:border-0">
                      <td className="py-2 pr-3 tabular-nums">
                        <Link to={`/invoices/${inv.id}/edit`} className={linkClass}>
                          {inv.invoice_no}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">{inv.customer_name ?? "—"}</td>
                      <td className="py-2 pr-3 tabular-nums">{inv.invoice_date}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">₹ {moneyFmt(inv.grand_total)}</td>
                      <td className="py-2 pr-3">
                        <StatusBadge status={inv.status} />
                      </td>
                      <td className="py-2 text-right">
                        <div className="flex items-center justify-end gap-3">
                          <button type="button" onClick={() => downloadInvoicePdf(inv.id, inv.invoice_no)} className={linkClass}>
                            PDF
                          </button>
                          {inv.status === "draft" && (
                            <button
                              type="button"
                              onClick={() => handleFinalize(inv.id, inv.invoice_no)}
                              disabled={finalizeMutation.isPending}
                              className={linkClass + " disabled:opacity-50"}
                            >
                              Finalize
                            </button>
                          )}
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

            <div className="mt-4 flex items-center justify-between text-sm text-ink-muted">
              <span>
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className={linkClass + " disabled:opacity-40"}
                >
                  ← Prev
                </button>
                <span>Page {page + 1} / {pageCount}</span>
                <button
                  type="button"
                  disabled={page + 1 >= pageCount}
                  onClick={() => setPage((p) => p + 1)}
                  className={linkClass + " disabled:opacity-40"}
                >
                  Next →
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
