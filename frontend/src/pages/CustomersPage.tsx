import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Customer, CustomerInput, createCustomer, listCustomers, updateCustomer } from "../api/customers";
import AppShell from "../components/AppShell";
import InfoTooltip from "../components/InfoTooltip";
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

export default function CustomersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data: customers = [], isLoading } = useQuery({
    queryKey: ["customers", "list"],
    queryFn: listCustomers,
  });

  const { register, handleSubmit, reset } = useForm<CustomerInput>({ defaultValues: emptyValues });

  const createMutation = useMutation({
    mutationFn: createCustomer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] });
      reset(emptyValues);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<CustomerInput> }) =>
      updateCustomer(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] });
      setEditingId(null);
      reset(emptyValues);
    },
  });

  function startEdit(customer: Customer) {
    setEditingId(customer.id);
    reset({
      name: customer.name,
      address: customer.address,
      contact_person: customer.contact_person,
      phone: customer.phone,
      gstin: customer.gstin,
      pan: customer.pan,
      place_of_supply: customer.place_of_supply,
      reverse_charge: customer.reverse_charge,
      ship_to: customer.ship_to,
    });
  }

  function cancelEdit() {
    setEditingId(null);
    reset(emptyValues);
  }

  useEffect(() => {
    // Reset editing state if the app navigates away and back.
    return () => setEditingId(null);
  }, []);

  const filtered = customers.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()));

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
          ) : filtered.length === 0 ? (
            <p className="text-sm text-ink-muted">No customers found.</p>
          ) : (
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
                  {filtered.map((c) => (
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
          )}
        </div>

        <form
          onSubmit={handleSubmit((values) => {
            if (editingId) {
              updateMutation.mutate({ id: editingId, body: values });
            } else {
              createMutation.mutate(values);
            }
          })}
          className={cardClass}
        >
          <h2 className={cardTitleClass}>{editingId ? "Edit customer" : "Add customer"}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={labelClass}>Name (M/S)</label>
              <input {...register("name", { required: true })} className={inputClass} />
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
              <input {...register("place_of_supply")} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>GSTIN</label>
              <input {...register("gstin")} maxLength={15} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>PAN</label>
              <input {...register("pan")} maxLength={10} className={inputClass} />
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
          <div className="mt-4 flex gap-3">
            <button
              type="submit"
              disabled={createMutation.isPending || updateMutation.isPending}
              className={primaryButtonClass}
            >
              {editingId
                ? updateMutation.isPending
                  ? "Saving…"
                  : "Save changes"
                : createMutation.isPending
                  ? "Adding…"
                  : "Add customer"}
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
