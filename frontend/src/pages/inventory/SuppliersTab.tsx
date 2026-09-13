import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Supplier, SupplierInput, createSupplier, listSuppliers, updateSupplier } from "../../api/inventory";
import { getErrorMessage } from "../../lib/apiError";
import {
  cardClass,
  cardTitleClass,
  inputClass,
  labelClass,
  linkClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../../styles";

const emptyValues: SupplierInput = {
  name: "",
  gstin: null,
  phone: null,
  email: null,
  address: null,
  state_code: null,
};

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-sm text-danger">{message}</p>;
}

export default function SuppliersTab() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data: suppliers = [], isLoading } = useQuery({
    queryKey: ["suppliers", "list", debounced],
    queryFn: () => listSuppliers({ q: debounced || undefined }),
    placeholderData: (prev) => prev,
  });

  const { register, handleSubmit, reset, formState: { errors } } = useForm<SupplierInput>({
    defaultValues: emptyValues,
  });

  const onDone = () => {
    queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    setEditingId(null);
    reset(emptyValues);
  };

  const createMutation = useMutation({ mutationFn: createSupplier, onSuccess: onDone });
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<SupplierInput> }) =>
      updateSupplier(id, body),
    onSuccess: onDone,
  });
  const mutationError =
    (createMutation.isError && getErrorMessage(createMutation.error, "Could not add supplier.")) ||
    (updateMutation.isError && getErrorMessage(updateMutation.error, "Could not save supplier.")) ||
    null;

  function startEdit(supplier: Supplier) {
    setEditingId(supplier.id);
    reset({ ...supplier });
  }
  function cancelEdit() {
    setEditingId(null);
    reset(emptyValues);
  }

  return (
    <div className="space-y-6">
      <div className={cardClass}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className={cardTitleClass}>All suppliers</h2>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name…"
            className={inputClass + " max-w-xs"}
          />
        </div>
        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : suppliers.length === 0 ? (
          <p className="text-sm text-ink-muted">No suppliers found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Name</th>
                  <th className="py-2 pr-3 font-medium">GSTIN</th>
                  <th className="py-2 pr-3 font-medium">Phone</th>
                  <th className="py-2 pr-3 font-medium">State</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {suppliers.map((s) => (
                  <tr key={s.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 font-medium">{s.name}</td>
                    <td className="py-2 pr-3 tabular-nums">{s.gstin ?? "—"}</td>
                    <td className="py-2 pr-3">{s.phone ?? "—"}</td>
                    <td className="py-2 pr-3">{s.state_code ?? "—"}</td>
                    <td className="py-2 text-right">
                      <button type="button" onClick={() => startEdit(s)} className={linkClass}>
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
          if (editingId) updateMutation.mutate({ id: editingId, body: values });
          else createMutation.mutate(values);
        })}
        className={cardClass}
      >
        <h2 className={cardTitleClass}>{editingId ? "Edit supplier" : "Add supplier"}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Name</label>
            <input {...register("name", { required: "Name is required" })} className={inputClass} />
            <FieldError message={errors.name?.message} />
          </div>
          <div>
            <label className={labelClass}>GSTIN</label>
            <input {...register("gstin")} maxLength={15} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Phone</label>
            <input {...register("phone")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Email</label>
            <input {...register("email")} className={inputClass} />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClass}>Address</label>
            <textarea {...register("address")} rows={2} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>State code</label>
            <input {...register("state_code")} maxLength={2} className={inputClass} />
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
              : createMutation.isPending ? "Adding…" : "Add supplier"}
          </button>
          {editingId && (
            <button type="button" onClick={cancelEdit} className={secondaryButtonClass}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
