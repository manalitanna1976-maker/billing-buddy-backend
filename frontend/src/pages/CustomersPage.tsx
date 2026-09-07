import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Customer, CustomerInput, createCustomer, listCustomers, updateCustomer } from "../api/customers";
import AppShell from "../components/AppShell";
import InfoTooltip from "../components/InfoTooltip";
import StateSelect from "../components/StateSelect";
import { getErrorMessage } from "../lib/apiError";
import { gstinRule, panRule } from "../lib/validators";
import {
  cardClass,
  cardTitleClass,
  inputClass,
  labelClass,
  linkClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../styles";

const REVERSE_CHARGE_HELP =
  "Reverse charge: GST liability shifts from the buyer to the seller's customer — the buyer pays " +
  "and reports the GST directly instead of the seller collecting it. Applies to specific notified " +
  "goods/services, or when the seller is unregistered.";

const PAGE_SIZE = 25;

const emptyValues: CustomerInput = {
  name: "",
  address: null,
  contact_person: null,
  phone: null,
  gstin: null,
  pan: null,
  place_of_supply: null,
  reverse_charge: false,
  ship_to: null,
};

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-sm text-danger">{message}</p>;
}

export default function CustomersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(0), [debounced]);

  const { data: customers = [], isLoading } = useQuery({
    queryKey: ["customers", "list", { debounced, page }],
    queryFn: () =>
      listCustomers({ limit: PAGE_SIZE + 1, offset: page * PAGE_SIZE, q: debounced || undefined }),
    placeholderData: (prev) => prev,
  });
  const hasNext = customers.length > PAGE_SIZE;
  const rows = customers.slice(0, PAGE_SIZE);

  const {
    register,
    handleSubmit,
    reset,
    control,
    setValue,
    watch,
    formState: { errors },
  } = useForm<CustomerInput>({ defaultValues: emptyValues });
  void control;

  const onDone = () => {
    queryClient.invalidateQueries({ queryKey: ["customers"] });
    setEditingId(null);
    reset(emptyValues);
  };

  const createMutation = useMutation({ mutationFn: createCustomer, onSuccess: onDone });
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<CustomerInput> }) => updateCustomer(id, body),
    onSuccess: onDone,
  });
  const mutationError =
    (createMutation.isError && getErrorMessage(createMutation.error, "Could not add customer.")) ||
    (updateMutation.isError && getErrorMessage(updateMutation.error, "Could not save customer.")) ||
    null;

  function startEdit(customer: Customer) {
    setEditingId(customer.id);
    reset({ ...customer } as CustomerInput);
  }
  function cancelEdit() {
    setEditingId(null);
    reset(emptyValues);
  }

  useEffect(() => () => setEditingId(null), []);

  const placeOfSupply = watch("place_of_supply");

  return (
    <AppShell title="Customers">
      <div className="space-y-6">
        <div className={cardClass}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className={cardTitleClass}>All customers</h2>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name…"
              className={inputClass + " max-w-xs"}
            />
          </div>
          {isLoading ? (
            <p className="text-sm text-ink-muted">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-ink-muted">No customers found.</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                      <th className="py-2 pr-3 font-medium">Name</th>
                      <th className="py-2 pr-3 font-medium">Place of supply</th>
                      <th className="py-2 pr-3 font-medium">GSTIN</th>
                      <th className="py-2 pr-3 font-medium">PAN</th>
                      <th className="py-2 pr-3 font-medium">Rev. charge</th>
                      <th className="py-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3 font-medium">{c.name}</td>
                        <td className="py-2 pr-3">{c.place_of_supply ?? "—"}</td>
                        <td className="py-2 pr-3 tabular-nums">{c.gstin ?? "—"}</td>
                        <td className="py-2 pr-3 tabular-nums">{c.pan ?? "—"}</td>
                        <td className="py-2 pr-3">{c.reverse_charge ? "Yes" : "No"}</td>
                        <td className="py-2 text-right">
                          <button type="button" onClick={() => startEdit(c)} className={linkClass}>
                            Edit
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex justify-end gap-3 text-sm">
                <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className={linkClass + " disabled:opacity-40"}>
                  ← Prev
                </button>
                <span className="text-ink-muted">Page {page + 1}</span>
                <button type="button" disabled={!hasNext} onClick={() => setPage((p) => p + 1)} className={linkClass + " disabled:opacity-40"}>
                  Next →
                </button>
              </div>
            </>
          )}
        </div>

        <form
          onSubmit={handleSubmit((values) => {
            if (editingId) updateMutation.mutate({ id: editingId, body: values });
            else createMutation.mutate(values);
          })}
          className={cardClass}
        >
          <h2 className={cardTitleClass}>{editingId ? "Edit customer" : "Add customer"}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={labelClass}>Name (M/S)</label>
              <input {...register("name", { required: "Name is required" })} className={inputClass} />
              <FieldError message={errors.name?.message} />
            </div>
            <div>
              <label className={labelClass}>Contact person</label>
              <input {...register("contact_person")} className={inputClass} />
            </div>
            <div className="sm:col-span-2">
              <label className={labelClass}>Address</label>
              <textarea {...register("address")} rows={2} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Phone</label>
              <input {...register("phone")} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Place of supply (state)</label>
              <StateSelect value={placeOfSupply} onChange={(v) => setValue("place_of_supply", v)} />
            </div>
            <div>
              <label className={labelClass}>GSTIN</label>
              <input {...register("gstin", gstinRule)} maxLength={15} className={inputClass} />
              <FieldError message={errors.gstin?.message as string | undefined} />
            </div>
            <div>
              <label className={labelClass}>PAN</label>
              <input {...register("pan", panRule)} maxLength={10} className={inputClass} />
              <FieldError message={errors.pan?.message as string | undefined} />
            </div>
            <div>
              <label className={labelClass}>
                Reverse charge
                <InfoTooltip text={REVERSE_CHARGE_HELP} />
              </label>
              <select
                {...register("reverse_charge", { setValueAs: (v) => v === "true" || v === true })}
                className={inputClass}
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
            </div>
            <div>
              <label className={labelClass}>Ship to</label>
              <input {...register("ship_to")} className={inputClass} />
            </div>
          </div>
          {mutationError && <p className="mt-3 text-sm text-danger">{mutationError}</p>}
          <div className="mt-4 flex gap-3">
            <button
              type="submit"
              disabled={createMutation.isPending || updateMutation.isPending}
              className={primaryButtonClass}
            >
              {editingId
                ? updateMutation.isPending ? "Saving…" : "Save changes"
                : createMutation.isPending ? "Adding…" : "Add customer"}
            </button>
            {editingId && (
              <button type="button" onClick={cancelEdit} className={secondaryButtonClass}>
                Cancel
              </button>
            )}
          </div>
        </form>
      </div>
    </AppShell>
  );
}
