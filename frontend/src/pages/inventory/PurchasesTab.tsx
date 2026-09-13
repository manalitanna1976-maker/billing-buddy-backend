import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";

import { Product, Supplier } from "../../api/inventory";
import { PurchaseInput, PurchaseLineItemInput, createPurchase, listPurchases } from "../../api/purchases";
import ProductAutocomplete from "../../components/ProductAutocomplete";
import SupplierAutocomplete from "../../components/SupplierAutocomplete";
import { getErrorMessage } from "../../lib/apiError";
import {
  cardClass,
  cardTitleClass,
  inputClass,
  labelClass,
  primaryButtonClass,
} from "../../styles";

interface FormValues {
  invoice_no: string;
  invoice_date: string;
  po_no: string;
  shipping_total: string;
  other_charges: string;
  round_off: string;
  line_items: PurchaseLineItemInput[];
}

const emptyLineItem: PurchaseLineItemInput = {
  product_id: undefined,
  product_name: "",
  qty: "1",
  price: "0",
  discount: "0",
  gst_rate: "0",
};

const emptyValues: FormValues = {
  invoice_no: "",
  invoice_date: "",
  po_no: "",
  shipping_total: "0",
  other_charges: "0",
  round_off: "0",
  line_items: [emptyLineItem],
};

function moneyFmt(value: string | number): string {
  const n = typeof value === "number" ? value : parseFloat(value);
  return isFinite(n)
    ? n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value);
}

function computeLineTotal(li: PurchaseLineItemInput): number {
  const qty = parseFloat(li.qty || "0");
  const price = parseFloat(li.price || "0");
  const discount = parseFloat(li.discount || "0");
  const taxable = qty * price - discount;
  return isFinite(taxable) ? taxable : 0;
}

function computeLineTax(li: PurchaseLineItemInput): number {
  const taxable = computeLineTotal(li);
  const rate = parseFloat(li.gst_rate || "0");
  return isFinite(rate) ? (taxable * rate) / 100 : 0;
}

export default function PurchasesTab() {
  const queryClient = useQueryClient();
  const [selectedProducts, setSelectedProducts] = useState<Record<number, Product | null>>({});
  const [supplier, setSupplier] = useState<Supplier | null>(null);

  const { data: purchases = [], isLoading } = useQuery({
    queryKey: ["purchases", "list"],
    queryFn: () => listPurchases(),
  });

  const { register, control, handleSubmit, reset, watch, setValue } = useForm<FormValues>({
    defaultValues: emptyValues,
  });
  const { fields, append, remove } = useFieldArray({ control, name: "line_items" });
  const lineItems = watch("line_items");

  // Computed directly on every render (not memoized on the line_items array
  // reference) -- react-hook-form's watch() mutates that array in place
  // rather than replacing it, so a useMemo keyed on the array itself never
  // saw a dependency change and these totals silently froze at 0.
  const taxable = lineItems.reduce((sum, li) => sum + computeLineTotal(li), 0);
  const tax = lineItems.reduce((sum, li) => sum + computeLineTax(li), 0);
  const totals = { taxable, tax };

  const shipping = parseFloat(watch("shipping_total") || "0") || 0;
  const other = parseFloat(watch("other_charges") || "0") || 0;
  const roundOff = parseFloat(watch("round_off") || "0") || 0;
  const grandTotal = totals.taxable + totals.tax + shipping + other + roundOff;

  const mutation = useMutation({
    mutationFn: createPurchase,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["purchases"] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
      reset(emptyValues);
      setSelectedProducts({});
      setSupplier(null);
    },
  });
  const mutationError =
    mutation.isError && getErrorMessage(mutation.error, "Could not record purchase.");

  function onSubmit(values: FormValues) {
    if (!supplier) return;
    const body: PurchaseInput = {
      supplier_id: supplier.id,
      invoice_no: values.invoice_no || null,
      invoice_date: values.invoice_date || null,
      po_no: values.po_no || null,
      shipping_total: values.shipping_total || "0",
      other_charges: values.other_charges || "0",
      round_off: values.round_off || "0",
      line_items: values.line_items.map((li) => ({
        product_id: li.product_id || undefined,
        product_name: li.product_id ? undefined : li.product_name || undefined,
        hsn_sac: li.hsn_sac || undefined,
        qty: li.qty,
        uom: li.uom || undefined,
        price: li.price,
        discount: li.discount || "0",
        gst_rate: li.gst_rate || "0",
      })),
    };
    mutation.mutate(body);
  }

  return (
    <div className="space-y-6">
      <div className={cardClass}>
        <h2 className={cardTitleClass}>Purchase history</h2>
        {isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : purchases.length === 0 ? (
          <p className="text-sm text-ink-muted">No purchases recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Supplier</th>
                  <th className="py-2 pr-3 font-medium">Invoice no</th>
                  <th className="py-2 pr-3 font-medium">Date</th>
                  <th className="py-2 pr-3 font-medium">Origin</th>
                  <th className="py-2 pr-3 font-medium">Grand total</th>
                </tr>
              </thead>
              <tbody>
                {purchases.map((p) => (
                  <tr key={p.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 font-medium">{p.supplier_name ?? "—"}</td>
                    <td className="py-2 pr-3">{p.invoice_no ?? "—"}</td>
                    <td className="py-2 pr-3">{p.invoice_date ?? "—"}</td>
                    <td className="py-2 pr-3 capitalize">{p.origin}</td>
                    <td className="py-2 pr-3 tabular-nums">{moneyFmt(p.grand_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className={cardClass}>
        <h2 className={cardTitleClass}>Record purchase</h2>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2">
            <label className={labelClass}>Supplier</label>
            <SupplierAutocomplete value={supplier} onChange={setSupplier} />
          </div>
          <div>
            <label className={labelClass}>Invoice no</label>
            <input {...register("invoice_no")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Invoice date</label>
            <input type="date" {...register("invoice_date")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>PO no</label>
            <input {...register("po_no")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Shipping</label>
            <input {...register("shipping_total")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Other charges</label>
            <input {...register("other_charges")} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Round off</label>
            <input {...register("round_off")} className={inputClass} />
          </div>
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-ink-muted">
                <th className="py-2 pr-2 font-medium">Product</th>
                <th className="py-2 pr-2 font-medium">HSN</th>
                <th className="py-2 pr-2 font-medium">Qty</th>
                <th className="py-2 pr-2 font-medium">UOM</th>
                <th className="py-2 pr-2 font-medium">Price</th>
                <th className="py-2 pr-2 font-medium">Discount</th>
                <th className="py-2 pr-2 font-medium">GST %</th>
                <th className="py-2 pr-2 font-medium">Line total</th>
                <th className="py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field, index) => (
                <tr key={field.id} className="border-b border-border last:border-0">
                  <td className="py-2 pr-2 min-w-[180px]">
                    <ProductAutocomplete
                      value={selectedProducts[index] ?? null}
                      freeTextValue={lineItems[index]?.product_name ?? ""}
                      onSelect={(product) => {
                        setSelectedProducts((cur) => ({ ...cur, [index]: product }));
                        setValue(`line_items.${index}.product_id`, product.id);
                        setValue(`line_items.${index}.product_name`, product.name);
                        if (product.hsn_sac) setValue(`line_items.${index}.hsn_sac`, product.hsn_sac);
                        if (product.uom) setValue(`line_items.${index}.uom`, product.uom);
                        if (product.default_purchase_price) {
                          setValue(`line_items.${index}.price`, product.default_purchase_price);
                        }
                      }}
                      onFreeTextChange={(name) => {
                        setSelectedProducts((cur) => ({ ...cur, [index]: null }));
                        setValue(`line_items.${index}.product_id`, undefined);
                        setValue(`line_items.${index}.product_name`, name);
                      }}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.hsn_sac`)} className={inputClass + " w-20"} />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.qty`)} className={inputClass + " w-20"} />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.uom`)} className={inputClass + " w-16"} />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.price`)} className={inputClass + " w-24"} />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.discount`)} className={inputClass + " w-20"} />
                  </td>
                  <td className="py-2 pr-2">
                    <input {...register(`line_items.${index}.gst_rate`)} className={inputClass + " w-16"} />
                  </td>
                  <td className="py-2 pr-2 tabular-nums">{moneyFmt(computeLineTotal(lineItems[index] ?? field))}</td>
                  <td className="py-2">
                    {fields.length > 1 && (
                      <button
                        type="button"
                        onClick={() => remove(index)}
                        className="text-sm text-danger hover:underline"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            onClick={() => append(emptyLineItem)}
            className="mt-2 text-sm font-medium text-primary hover:underline"
          >
            + Add line
          </button>
        </div>

        <div className="mt-4 flex flex-col items-end gap-1 text-sm">
          <div>Taxable total: <span className="tabular-nums font-medium">{moneyFmt(totals.taxable)}</span></div>
          <div>Tax total: <span className="tabular-nums font-medium">{moneyFmt(totals.tax)}</span></div>
          <div className="text-base font-semibold">
            Grand total: <span className="tabular-nums">{moneyFmt(grandTotal)}</span>
          </div>
        </div>

        {mutationError && <p className="mt-3 text-sm text-danger">{mutationError}</p>}
        {!supplier && <p className="mt-3 text-sm text-ink-muted">Select a supplier to record this purchase.</p>}
        <div className="mt-4">
          <button type="submit" disabled={!supplier || mutation.isPending} className={primaryButtonClass}>
            {mutation.isPending ? "Saving…" : "Record purchase"}
          </button>
        </div>
      </form>
    </div>
  );
}
