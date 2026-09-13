import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import {
  Product,
  ProductInput,
  adjustStock,
  createProduct,
  listProducts,
  listStockMovements,
  updateProduct,
} from "../../api/inventory";
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

const emptyValues: ProductInput = {
  name: "",
  hsn_sac: null,
  uom: null,
  reorder_level: null,
  default_purchase_price: null,
};

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-sm text-danger">{message}</p>;
}

function AdjustStockRow({ product, onDone }: { product: Product; onDone: () => void }) {
  const [deltaQty, setDeltaQty] = useState("");
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: () => adjustStock(product.id, { delta_qty: deltaQty, note: note || null }),
    onSuccess: () => {
      setDeltaQty("");
      setNote("");
      onDone();
    },
  });
  const error = mutation.isError && getErrorMessage(mutation.error, "Could not adjust stock.");

  return (
    <tr className="border-b border-border bg-paper">
      <td colSpan={6} className="px-3 py-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (deltaQty.trim()) mutation.mutate();
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div>
            <label className={labelClass}>
              Adjust qty (+/-)
            </label>
            <input
              value={deltaQty}
              onChange={(e) => setDeltaQty(e.target.value)}
              placeholder="e.g. -3 or 10"
              className={inputClass + " w-32"}
            />
          </div>
          <div className="flex-1">
            <label className={labelClass}>Note</label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. damaged stock, stock-take correction"
              className={inputClass}
            />
          </div>
          <button type="submit" disabled={mutation.isPending} className={primaryButtonClass}>
            {mutation.isPending ? "Saving…" : "Apply"}
          </button>
        </form>
        {error && <p className="mt-2 text-sm text-danger">{error}</p>}
      </td>
    </tr>
  );
}

function MovementsRow({ productId }: { productId: string }) {
  const { data: movements = [], isLoading } = useQuery({
    queryKey: ["products", productId, "stock-movements"],
    queryFn: () => listStockMovements(productId),
  });
  return (
    <tr className="border-b border-border bg-paper">
      <td colSpan={6} className="px-3 py-3">
        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : movements.length === 0 ? (
          <p className="text-sm text-ink-muted">No stock movements yet.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-ink-muted">
                <th className="py-1 pr-3 font-medium">When</th>
                <th className="py-1 pr-3 font-medium">Delta</th>
                <th className="py-1 pr-3 font-medium">Balance</th>
                <th className="py-1 pr-3 font-medium">Reason</th>
                <th className="py-1 font-medium">Note</th>
              </tr>
            </thead>
            <tbody>
              {movements.map((m) => (
                <tr key={m.id}>
                  <td className="py-1 pr-3 tabular-nums">
                    {new Date(m.created_at).toLocaleString()}
                  </td>
                  <td className="py-1 pr-3 tabular-nums">{m.delta_qty}</td>
                  <td className="py-1 pr-3 tabular-nums">{m.balance_after}</td>
                  <td className="py-1 pr-3">{m.reason}</td>
                  <td className="py-1">{m.note ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </td>
    </tr>
  );
}

export default function ProductsTab() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [adjustingId, setAdjustingId] = useState<string | null>(null);
  const [historyId, setHistoryId] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data: products = [], isLoading } = useQuery({
    queryKey: ["products", "list", debounced],
    queryFn: () => listProducts({ q: debounced || undefined }),
    placeholderData: (prev) => prev,
  });

  const { register, handleSubmit, reset, formState: { errors } } = useForm<ProductInput>({
    defaultValues: emptyValues,
  });

  const onDone = () => {
    queryClient.invalidateQueries({ queryKey: ["products"] });
    setEditingId(null);
    reset(emptyValues);
  };

  const createMutation = useMutation({ mutationFn: createProduct, onSuccess: onDone });
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<ProductInput> }) =>
      updateProduct(id, body),
    onSuccess: onDone,
  });
  const mutationError =
    (createMutation.isError && getErrorMessage(createMutation.error, "Could not add product.")) ||
    (updateMutation.isError && getErrorMessage(updateMutation.error, "Could not save product.")) ||
    null;

  function startEdit(product: Product) {
    setEditingId(product.id);
    setAdjustingId(null);
    setHistoryId(null);
    reset({
      name: product.name,
      hsn_sac: product.hsn_sac,
      uom: product.uom,
      reorder_level: product.reorder_level,
      default_purchase_price: product.default_purchase_price,
    });
  }
  function cancelEdit() {
    setEditingId(null);
    reset(emptyValues);
  }

  function toggleAdjust(id: string) {
    setHistoryId(null);
    setAdjustingId((cur) => (cur === id ? null : id));
  }
  function toggleHistory(id: string) {
    setAdjustingId(null);
    setHistoryId((cur) => (cur === id ? null : id));
  }

  return (
    <div className="space-y-6">
      <div className={cardClass}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className={cardTitleClass}>All products</h2>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name…"
            className={inputClass + " max-w-xs"}
          />
        </div>
        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : products.length === 0 ? (
          <p className="text-sm text-ink-muted">No products found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Name</th>
                  <th className="py-2 pr-3 font-medium">HSN/SAC</th>
                  <th className="py-2 pr-3 font-medium">UOM</th>
                  <th className="py-2 pr-3 font-medium">Qty in stock</th>
                  <th className="py-2 pr-3 font-medium">Reorder level</th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => (
                  <Fragment key={p.id}>
                    <tr className="border-b border-border last:border-0">
                      <td className="py-2 pr-3 font-medium">
                        {p.name}
                        {p.needs_review && (
                          <span className="ml-2 rounded-full bg-gold/20 px-2 py-0.5 text-[10px] font-semibold text-gold-fg">
                            needs review
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{p.hsn_sac ?? "—"}</td>
                      <td className="py-2 pr-3">{p.uom ?? "—"}</td>
                      <td className="py-2 pr-3 tabular-nums">{p.current_qty}</td>
                      <td className="py-2 pr-3 tabular-nums">{p.reorder_level ?? "—"}</td>
                      <td className="py-2 text-right whitespace-nowrap">
                        <button type="button" onClick={() => toggleHistory(p.id)} className={linkClass + " mr-3"}>
                          History
                        </button>
                        <button type="button" onClick={() => toggleAdjust(p.id)} className={linkClass + " mr-3"}>
                          Adjust stock
                        </button>
                        <button type="button" onClick={() => startEdit(p)} className={linkClass}>
                          Edit
                        </button>
                      </td>
                    </tr>
                    {adjustingId === p.id && (
                      <AdjustStockRow
                        key={`${p.id}-adjust`}
                        product={p}
                        onDone={() => {
                          queryClient.invalidateQueries({ queryKey: ["products"] });
                          setAdjustingId(null);
                        }}
                      />
                    )}
                    {historyId === p.id && <MovementsRow key={`${p.id}-history`} productId={p.id} />}
                  </Fragment>
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
        <h2 className={cardTitleClass}>{editingId ? "Edit product" : "Add product"}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Name</label>
            <input {...register("name", { required: "Name is required" })} className={inputClass} />
            <FieldError message={errors.name?.message} />
          </div>
          <div>
            <label className={labelClass}>HSN/SAC</label>
            <input {...register("hsn_sac")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>UOM</label>
            <input {...register("uom")} placeholder="e.g. pcs, kg" className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Reorder level</label>
            <input {...register("reorder_level")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Default purchase price</label>
            <input {...register("default_purchase_price")} className={inputClass} />
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
              : createMutation.isPending ? "Adding…" : "Add product"}
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
