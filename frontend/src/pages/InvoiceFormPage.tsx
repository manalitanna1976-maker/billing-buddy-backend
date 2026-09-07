import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";

import { listBankAccounts } from "../api/bankAccounts";
import { getBusiness } from "../api/business";
import { Customer, getCustomer } from "../api/customers";
import {
  Invoice,
  InvoiceInput,
  InvoiceLineItemInput,
  createInvoice,
  downloadInvoicePdf,
  finalizeInvoice,
  getInvoice,
  updateInvoice,
} from "../api/invoices";
import AppShell from "../components/AppShell";
import CustomerAutocomplete from "../components/CustomerAutocomplete";
import { amountInWords } from "../lib/amountInWords";
import { getErrorMessage } from "../lib/apiError";
import { computeInvoiceTotalsPreview, lineTaxableValue } from "../lib/gst";
import { sameGstState } from "../lib/sameState";
import {
  cardClass,
  cardTitleClass,
  inputClass,
  labelClass,
  linkClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../styles";

const GST_RATES = ["0", "0.25", "1", "1.5", "3", "5", "6", "12", "18", "28"];

interface FormValues extends Omit<InvoiceInput, "line_items" | "customer_id"> {
  line_items: InvoiceLineItemInput[];
}

const emptyLineItem: InvoiceLineItemInput = {
  product_name: "",
  hsn_sac: "",
  qty: "1",
  uom: "",
  price: "0",
  discount: "0",
  gst_rate: "0",
};

const defaultValues: FormValues = {
  invoice_type: null,
  invoice_date: new Date().toISOString().slice(0, 10),
  challan_no: null,
  challan_date: null,
  po_no: null,
  po_date: null,
  lr_no: null,
  eway_no: null,
  delivery_mode: null,
  due_date: null,
  bank_account_id: null,
  discount_type: "Rs",
  discount_value: "0",
  tcs: "0",
  round_off: true,
  terms_title: null,
  terms_detail: null,
  notes: null,
  remarks: null,
  payment_type: "credit",
  line_items: [emptyLineItem],
};

const nullableText = {
  setValueAs: (v: string) => (v && v.trim() !== "" ? v.trim() : null),
};
const nullableSelect = { setValueAs: (v: string) => (v ? v : null) };

function moneyFmt(value: number): string {
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-danger">{message}</p>;
}

function ReadOnly({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className={labelClass}>{label}</div>
      <div className="rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink">
        {value || "—"}
      </div>
    </div>
  );
}

export default function InvoiceFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [customerError, setCustomerError] = useState<string | null>(null);

  const { data: business } = useQuery({ queryKey: ["business"], queryFn: getBusiness });
  const { data: bankAccounts = [] } = useQuery({ queryKey: ["bank-accounts"], queryFn: listBankAccounts });
  const { data: existingInvoice } = useQuery<Invoice>({
    queryKey: ["invoice", id],
    queryFn: () => getInvoice(id as string),
    enabled: isEdit,
  });

  const locked = isEdit && existingInvoice != null && existingInvoice.status !== "draft";

  const {
    register,
    control,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ defaultValues });
  const { fields, append, remove } = useFieldArray({ control, name: "line_items" });

  useEffect(() => {
    if (!existingInvoice) return;
    (async () => {
      try {
        setSelectedCustomer(await getCustomer(existingInvoice.customer_id));
      } catch {
        setSelectedCustomer(null);
      }
      reset({
        invoice_type: existingInvoice.invoice_type,
        invoice_date: existingInvoice.invoice_date,
        challan_no: existingInvoice.challan_no,
        challan_date: existingInvoice.challan_date,
        po_no: existingInvoice.po_no,
        po_date: existingInvoice.po_date,
        lr_no: existingInvoice.lr_no,
        eway_no: existingInvoice.eway_no,
        delivery_mode: existingInvoice.delivery_mode,
        due_date: existingInvoice.due_date,
        bank_account_id: existingInvoice.bank_account_id,
        discount_type: existingInvoice.discount_type as "Rs" | "%",
        discount_value: String(existingInvoice.discount_value),
        tcs: String(existingInvoice.tcs),
        round_off: existingInvoice.round_off,
        terms_title: existingInvoice.terms_title,
        terms_detail: existingInvoice.terms_detail,
        notes: existingInvoice.notes,
        remarks: existingInvoice.remarks,
        payment_type: existingInvoice.payment_type as FormValues["payment_type"],
        line_items: existingInvoice.line_items.map((li) => ({
          product_name: li.product_name,
          hsn_sac: li.hsn_sac,
          qty: String(li.qty),
          uom: li.uom,
          price: String(li.price),
          discount: String(li.discount),
          gst_rate: String(Number(li.gst_rate)),
        })),
      });
    })();
  }, [existingInvoice, reset]);

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      if (!selectedCustomer) throw new Error("Select a customer before saving.");
      const payload: InvoiceInput = { ...values, customer_id: selectedCustomer.id };
      return isEdit ? updateInvoice(id as string, payload) : createInvoice(payload);
    },
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      queryClient.setQueryData(["invoice", invoice.id], invoice);
      navigate(`/invoices/${invoice.id}/edit`, { replace: true });
    },
  });

  const finalizeMutation = useMutation({
    mutationFn: () => finalizeInvoice(id as string),
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      queryClient.setQueryData(["invoice", invoice.id], invoice);
    },
  });

  const lineItems = watch("line_items");
  const discountType = watch("discount_type");
  const discountValue = watch("discount_value");
  const tcs = watch("tcs");
  const roundOff = watch("round_off");
  const paymentType = watch("payment_type");

  const totals = computeInvoiceTotalsPreview(lineItems, discountType, discountValue, tcs, roundOff);
  const intra = sameGstState(business?.state, selectedCustomer?.place_of_supply ?? existingInvoice?.bill_to_state);

  function onSubmit(values: FormValues) {
    if (!selectedCustomer) {
      setCustomerError("Select a customer before saving.");
      return;
    }
    setCustomerError(null);
    saveMutation.mutate(values);
  }

  const billTo = existingInvoice
    ? {
        name: existingInvoice.bill_to_name,
        gstin: existingInvoice.bill_to_gstin,
        pan: existingInvoice.bill_to_pan,
        state: existingInvoice.bill_to_state,
        address: existingInvoice.bill_to_address,
      }
    : selectedCustomer
      ? {
          name: selectedCustomer.name,
          gstin: selectedCustomer.gstin,
          pan: selectedCustomer.pan,
          state: selectedCustomer.place_of_supply,
          address: selectedCustomer.address,
        }
      : null;

  return (
    <AppShell
      title={
        isEdit
          ? `${locked ? "" : "Edit "}Invoice ${existingInvoice?.invoice_no ?? ""}${
              locked ? ` (${existingInvoice?.status})` : ""
            }`
          : "Create Sale Invoice"
      }
    >
      {locked && (
        <p className="mb-4 rounded-md border border-border bg-highlight px-4 py-2 text-sm text-ink">
          This invoice is <strong>{existingInvoice?.status}</strong> and can no longer be edited.
        </p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 pb-16">
        <fieldset disabled={locked} className="space-y-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className={cardClass}>
              <h2 className={cardTitleClass}>Customer</h2>
              {!isEdit && (
                <div className="mb-3">
                  <label className={labelClass}>M/S *</label>
                  <CustomerAutocomplete
                    value={selectedCustomer}
                    onChange={(c) => {
                      setCustomerError(null);
                      setSelectedCustomer(c);
                    }}
                  />
                  {customerError && <p className="mt-1 text-sm text-danger">{customerError}</p>}
                </div>
              )}
              <div className="space-y-3">
                <ReadOnly label="Name" value={billTo?.name} />
                <div className="grid grid-cols-2 gap-3">
                  <ReadOnly label="GSTIN" value={billTo?.gstin} />
                  <ReadOnly label="PAN" value={billTo?.pan} />
                </div>
                <ReadOnly label="Place of supply" value={billTo?.state} />
                <ReadOnly label="Address" value={billTo?.address} />
              </div>
              <p className="mt-3 text-xs text-ink-muted">
                {isEdit
                  ? "Bill-to details are a snapshot taken when the invoice was created — editing the customer later won't change this invoice."
                  : "These come from the customer record. "}
                <Link to="/customers" className={linkClass}>
                  Manage customers →
                </Link>
              </p>
            </div>

            <div className={cardClass}>
              <h2 className={cardTitleClass}>Invoice Detail</h2>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>Invoice type</label>
                    <select {...register("invoice_type", nullableSelect)} className={inputClass}>
                      <option value="">Select type</option>
                      <option value="Tax Invoice">Tax Invoice</option>
                      <option value="Bill of Supply">Bill of Supply</option>
                      <option value="Export Invoice">Export Invoice</option>
                    </select>
                  </div>
                  <div>
                    <label className={labelClass}>Date *</label>
                    <input
                      {...register("invoice_date", { required: "Invoice date is required" })}
                      type="date"
                      className={inputClass}
                    />
                    <FieldError message={errors.invoice_date?.message} />
                  </div>
                </div>
                <div>
                  <label className={labelClass}>Invoice no.</label>
                  <input
                    disabled
                    value={
                      existingInvoice?.invoice_no ??
                      `${business?.invoice_prefix ?? ""}(auto)${business?.invoice_postfix ?? ""}`
                    }
                    className={inputClass}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>Challan no.</label>
                    <input {...register("challan_no", nullableText)} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Challan date</label>
                    <input {...register("challan_date", nullableSelect)} type="date" className={inputClass} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelClass}>P.O. no.</label>
                    <input {...register("po_no", nullableText)} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>P.O. date</label>
                    <input {...register("po_date", nullableSelect)} type="date" className={inputClass} />
                  </div>
                </div>
                <div>
                  <label className={labelClass}>Delivery mode</label>
                  <select {...register("delivery_mode", nullableSelect)} className={inputClass}>
                    <option value="">Select delivery mode</option>
                    {["Road", "Rail", "Air", "Sea", "Courier", "Hand Delivery"].map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <h2 className={cardTitleClass + " mb-0"}>Product Items</h2>
              <div className="flex items-center gap-1 rounded-md border border-border p-0.5 text-xs font-semibold">
                <button type="button" onClick={() => setValue("discount_type", "Rs")}
                  className={["rounded px-2 py-1", discountType === "Rs" ? "bg-primary text-primary-fg" : "text-ink-muted"].join(" ")}>
                  Rs
                </button>
                <button type="button" onClick={() => setValue("discount_type", "%")}
                  className={["rounded px-2 py-1", discountType === "%" ? "bg-primary text-primary-fg" : "text-ink-muted"].join(" ")}>
                  %
                </button>
                <span className="px-1 text-ink-muted">discount mode</span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm tabular-nums">
                <thead>
                  <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                    <th className="py-2 pr-2 font-medium">Sr</th>
                    <th className="py-2 pr-2 font-medium">Product</th>
                    <th className="py-2 pr-2 font-medium">HSN/SAC</th>
                    <th className="py-2 pr-2 font-medium">Qty</th>
                    <th className="py-2 pr-2 font-medium">UOM</th>
                    <th className="py-2 pr-2 font-medium">Price (Rs)</th>
                    <th className="py-2 pr-2 font-medium">Discount</th>
                    <th className="py-2 pr-2 font-medium">GST %</th>
                    <th className="py-2 pr-2 font-medium text-right">Total</th>
                    <th className="py-2 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map((field, index) => (
                    <tr key={field.id} className="border-b border-border align-top">
                      <td className="py-2 pr-2 text-ink-muted">{index + 1}</td>
                      <td className="py-2 pr-2 min-w-[180px]">
                        <input
                          {...register(`line_items.${index}.product_name`, {
                            required: "Required",
                            setValueAs: (v: string) => v.trim(),
                          })}
                          placeholder="Enter product name"
                          className={inputClass}
                        />
                        <FieldError message={errors.line_items?.[index]?.product_name?.message} />
                      </td>
                      <td className="py-2 pr-2 w-24">
                        <input {...register(`line_items.${index}.hsn_sac`, nullableText)} className={inputClass} />
                      </td>
                      <td className="py-2 pr-2 w-20">
                        <input
                          type="number" min="0" step="any"
                          {...register(`line_items.${index}.qty`, {
                            required: "Required",
                            validate: (v) => parseFloat(v) > 0 || "> 0",
                          })}
                          className={inputClass}
                        />
                        <FieldError message={errors.line_items?.[index]?.qty?.message} />
                      </td>
                      <td className="py-2 pr-2 w-20">
                        <input {...register(`line_items.${index}.uom`, nullableText)} className={inputClass} />
                      </td>
                      <td className="py-2 pr-2 w-24">
                        <input
                          type="number" min="0" step="any"
                          {...register(`line_items.${index}.price`, {
                            required: "Required",
                            validate: (v) => parseFloat(v) >= 0 || "≥ 0",
                          })}
                          className={inputClass}
                        />
                        <FieldError message={errors.line_items?.[index]?.price?.message} />
                      </td>
                      <td className="py-2 pr-2 w-24">
                        <input
                          type="number" min="0" step="any"
                          {...register(`line_items.${index}.discount`, {
                            validate: (v) => !v || parseFloat(v) >= 0 || "≥ 0",
                          })}
                          className={inputClass}
                        />
                      </td>
                      <td className="py-2 pr-2 w-24">
                        <select {...register(`line_items.${index}.gst_rate`)} className={inputClass}>
                          {GST_RATES.map((r) => (
                            <option key={r} value={r}>{r}%</option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2 pr-2 text-right font-medium">
                        {moneyFmt(lineTaxableValue(lineItems?.[index] ?? emptyLineItem))}
                      </td>
                      <td className="py-2 text-right">
                        <button type="button" onClick={() => fields.length > 1 && remove(index)}
                          className="text-danger disabled:opacity-30" disabled={fields.length <= 1}>
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={() => append(emptyLineItem)}
              className="mt-3 text-sm font-medium text-primary hover:underline">
              + Add item
            </button>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className={cardClass}>
              <div className="space-y-3">
                <div>
                  <label className={labelClass}>Due date</label>
                  <input {...register("due_date", nullableSelect)} type="date" className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Bank account</label>
                  <select {...register("bank_account_id", nullableSelect)} className={inputClass}>
                    <option value="">Select bank</option>
                    {bankAccounts.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.bank_name} ({b.account_no.slice(-4)})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelClass}>Terms &amp; conditions — title</label>
                  <input {...register("terms_title", nullableText)} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Terms &amp; conditions — detail</label>
                  <textarea {...register("terms_detail", nullableText)} rows={3} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Notes</label>
                  <textarea {...register("notes", nullableText)} rows={2} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>
                    Remarks <span className="normal-case text-ink-muted">(not printed)</span>
                  </label>
                  <input {...register("remarks", nullableText)} className={inputClass} />
                </div>
              </div>
            </div>

            <div className={cardClass}>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-ink-muted">Taxable</span>
                  <span className="tabular-nums">{moneyFmt(totals.taxableTotal)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-ink-muted">
                    {intra ? "CGST + SGST" : "IGST"} (est.)
                  </span>
                  <span className="tabular-nums">{moneyFmt(totals.taxTotal)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-ink-muted">TCS</span>
                  <input type="number" min="0" step="any" {...register("tcs")} className={inputClass + " w-28 text-right"} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-ink-muted">Discount {discountType === "%" ? "(%)" : "(Rs)"}</span>
                  <input type="number" min="0" step="any" {...register("discount_value")} className={inputClass + " w-28 text-right"} />
                </div>
                <label className="flex items-center justify-between">
                  <span className="text-ink-muted">Round off</span>
                  <input type="checkbox" {...register("round_off")} className="h-4 w-4" />
                </label>
                <div className="flex justify-between rounded-md bg-highlight px-3 py-2 text-base font-semibold text-gold">
                  <span>Grand Total</span>
                  <span className="tabular-nums">₹ {moneyFmt(totals.grandTotal)}</span>
                </div>
                <p className="font-serif text-xs italic text-ink-muted">{amountInWords(totals.grandTotal)}</p>
                <p className="text-[11px] text-ink-muted">
                  The exact CGST/SGST/IGST split is computed and shown on the saved invoice and PDF.
                </p>

                <div className="pt-2">
                  <label className={labelClass}>Payment type *</label>
                  <div className="flex flex-wrap gap-2">
                    {(["credit", "cash", "cheque", "online"] as const).map((type) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => setValue("payment_type", type)}
                        className={[
                          "rounded-full border px-4 py-1.5 text-xs font-semibold uppercase tracking-wide",
                          paymentType === type ? "bg-primary text-primary-fg border-primary" : "border-border text-ink-muted",
                        ].join(" ")}
                      >
                        {type}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </fieldset>

        {saveMutation.isError && (
          <p className="text-sm text-danger">
            {getErrorMessage(saveMutation.error, "Could not save the invoice.")}
          </p>
        )}
        {finalizeMutation.isError && (
          <p className="text-sm text-danger">
            {getErrorMessage(finalizeMutation.error, "Could not finalize the invoice.")}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {!locked && (
            <button type="submit" disabled={saveMutation.isPending} className={primaryButtonClass}>
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
          )}
          {isEdit && existingInvoice?.status === "draft" && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm("Finalize this invoice? It will be locked and can only be cancelled.")) {
                  finalizeMutation.mutate();
                }
              }}
              disabled={finalizeMutation.isPending}
              className={secondaryButtonClass}
            >
              {finalizeMutation.isPending ? "Finalizing…" : "Finalize"}
            </button>
          )}
          {isEdit && existingInvoice && (
            <button
              type="button"
              onClick={() => downloadInvoicePdf(existingInvoice.id, existingInvoice.invoice_no)}
              className={secondaryButtonClass}
            >
              Download PDF
            </button>
          )}
          <button type="button" onClick={() => navigate("/")} className={secondaryButtonClass}>
            Back
          </button>
        </div>
      </form>
    </AppShell>
  );
}
