import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";

import { listBankAccounts } from "../api/bankAccounts";
import { getBusiness } from "../api/business";
import { Customer, getCustomer, updateCustomer } from "../api/customers";
import {
  Invoice,
  InvoiceInput,
  InvoiceLineItemInput,
  createInvoice,
  downloadInvoicePdf,
  getInvoice,
  updateInvoice,
} from "../api/invoices";
import AppShell from "../components/AppShell";
import CustomerAutocomplete from "../components/CustomerAutocomplete";
import InfoTooltip from "../components/InfoTooltip";
import { amountInWords } from "../lib/amountInWords";
import { computeInvoiceTotalsPreview, lineTaxableValue } from "../lib/gst";
import {
  cardClass,
  cardTitleClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../styles";

const REVERSE_CHARGE_HELP =
  "Reverse charge: GST liability shifts from the buyer to the seller's customer — the buyer pays " +
  "and reports the GST directly instead of the seller collecting it. Applies to specific notified " +
  "goods/services, or when the seller is unregistered.";

const GST_RATES = ["0", "5", "12", "18", "28"];

interface CustomerFormValues {
  name: string;
  address: string | null;
  contact_person: string | null;
  phone: string | null;
  gstin: string | null;
  pan: string | null;
  place_of_supply: string | null;
  reverse_charge: boolean;
  ship_to: string | null;
}

interface FormValues extends Omit<InvoiceInput, "line_items" | "customer_id"> {
  customer: CustomerFormValues;
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

const emptyCustomer: CustomerFormValues = {
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

const defaultValues: FormValues = {
  customer: emptyCustomer,
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

const nullableSelect = {
  setValueAs: (v: string) => (v ? v : null),
};

function moneyFmt(value: number): string {
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function PaymentPill({
  type,
  active,
  onClick,
}: {
  type: "credit" | "cash" | "cheque" | "online";
  active: boolean;
  onClick: () => void;
}) {
  const styles: Record<string, { filled: string; outline: string; label: string }> = {
    credit: { filled: "bg-gold text-gold-fg border-gold", outline: "border-gold text-gold", label: "Credit" },
    cash: { filled: "bg-success text-white border-success", outline: "border-success text-success", label: "Cash" },
    cheque: {
      filled: "bg-ink-muted text-surface border-ink-muted",
      outline: "border-border text-ink-muted",
      label: "Cheque",
    },
    online: {
      filled: "bg-online text-white border-online",
      outline: "border-online text-online",
      label: "Online",
    },
  };
  const s = styles[type];
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full border px-4 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors",
        active ? s.filled : "bg-transparent " + s.outline,
      ].join(" ")}
    >
      {s.label}
    </button>
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
  const { data: bankAccounts = [] } = useQuery({
    queryKey: ["bank-accounts"],
    queryFn: listBankAccounts,
  });
  const { data: existingInvoice } = useQuery<Invoice>({
    queryKey: ["invoice", id],
    queryFn: () => getInvoice(id as string),
    enabled: isEdit,
  });

  const { register, control, handleSubmit, reset, setValue, watch } = useForm<FormValues>({
    defaultValues,
  });
  const { fields, append, remove } = useFieldArray({ control, name: "line_items" });

  useEffect(() => {
    if (!existingInvoice) return;
    (async () => {
      const customer = await getCustomer(existingInvoice.customer_id);
      setSelectedCustomer(customer);
      reset({
        customer: {
          name: customer.name,
          address: customer.address,
          contact_person: customer.contact_person,
          phone: customer.phone,
          gstin: customer.gstin,
          pan: customer.pan,
          place_of_supply: customer.place_of_supply,
          reverse_charge: customer.reverse_charge,
          ship_to: customer.ship_to,
        },
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
          // The API returns gst_rate as a Decimal-formatted string (e.g. "18.00"),
          // which doesn't match any <option value="18"> in the GST % <select> —
          // that left the dropdown showing blank/unselected on every saved
          // invoice. Normalize to match the option values exactly.
          gst_rate: String(Number(li.gst_rate)),
        })),
      });
    })();
  }, [existingInvoice, reset]);

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      if (!selectedCustomer) {
        throw new Error("Select or create a customer before saving.");
      }
      await updateCustomer(selectedCustomer.id, values.customer);
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { customer, ...invoiceFields } = values;
      const payload: InvoiceInput = { ...invoiceFields, customer_id: selectedCustomer.id };
      return isEdit ? updateInvoice(id as string, payload) : createInvoice(payload);
    },
    onSuccess: (invoice) => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      queryClient.setQueryData(["invoice", invoice.id], invoice);
      navigate(`/invoices/${invoice.id}/edit`, { replace: true });
    },
  });

  function handleCustomerChange(customer: Customer) {
    setCustomerError(null);
    setSelectedCustomer(customer);
    setValue("customer", {
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

  const lineItems = watch("line_items");
  const discountType = watch("discount_type");
  const discountValue = watch("discount_value");
  const tcs = watch("tcs");
  const roundOff = watch("round_off");
  const paymentType = watch("payment_type");

  const totals = computeInvoiceTotalsPreview(lineItems, discountType, discountValue, tcs, roundOff);

  function onSubmit(values: FormValues) {
    if (!selectedCustomer) {
      setCustomerError("Select or create a customer before saving.");
      return;
    }
    saveMutation.mutate(values);
  }

  async function handleDownload() {
    if (!existingInvoice) return;
    await downloadInvoicePdf(existingInvoice.id, existingInvoice.invoice_no);
  }

  return (
    <AppShell title={isEdit ? `Edit Invoice ${existingInvoice?.invoice_no ?? ""}` : "Create Sale Invoice"}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 pb-16">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className={cardClass}>
            <h2 className={cardTitleClass}>Customer Information</h2>
            <div className="space-y-3">
              <div>
                <label className={labelClass}>M/S *</label>
                <CustomerAutocomplete value={selectedCustomer} onChange={handleCustomerChange} />
                {customerError && <p className="mt-1 text-sm text-danger">{customerError}</p>}
              </div>
              <div>
                <label className={labelClass}>Address</label>
                <textarea {...register("customer.address", nullableText)} rows={2} className={inputClass} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>Contact person</label>
                  <input {...register("customer.contact_person", nullableText)} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Phone no.</label>
                  <input {...register("customer.phone", nullableText)} className={inputClass} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>GSTIN</label>
                  <input
                    {...register("customer.gstin", nullableText)}
                    maxLength={15}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>PAN</label>
                  <input
                    {...register("customer.pan", nullableText)}
                    maxLength={10}
                    className={inputClass}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>
                    Rev. charge
                    <InfoTooltip text={REVERSE_CHARGE_HELP} />
                  </label>
                  <select
                    {...register("customer.reverse_charge", {
                      setValueAs: (v) => v === "true" || v === true,
                    })}
                    className={inputClass}
                  >
                    <option value="false">No</option>
                    <option value="true">Yes</option>
                  </select>
                </div>
                <div>
                  <label className={labelClass}>Place of supply *</label>
                  <input
                    {...register("customer.place_of_supply", { ...nullableText, required: true })}
                    className={inputClass}
                  />
                </div>
              </div>
              <div>
                <label className={labelClass}>Ship to</label>
                <input {...register("customer.ship_to", nullableText)} className={inputClass} />
              </div>
            </div>
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
                    {...register("invoice_date", { required: true })}
                    type="date"
                    className={inputClass}
                  />
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
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>L.R. no.</label>
                  <input {...register("lr_no", nullableText)} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>E-Way no.</label>
                  <input {...register("eway_no", nullableText)} className={inputClass} />
                </div>
              </div>
              <div>
                <label className={labelClass}>Delivery mode</label>
                <select {...register("delivery_mode", nullableSelect)} className={inputClass}>
                  <option value="">Select delivery mode</option>
                  <option value="Road">Road</option>
                  <option value="Rail">Rail</option>
                  <option value="Air">Air</option>
                  <option value="Sea">Sea</option>
                  <option value="Courier">Courier</option>
                  <option value="Hand Delivery">Hand Delivery</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className={cardClass}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className={cardTitleClass + " mb-0"}>Product Items</h2>
            <div className="flex items-center gap-1 rounded-md border border-border p-0.5 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setValue("discount_type", "Rs")}
                className={["rounded px-2 py-1", discountType === "Rs" ? "bg-primary text-primary-fg" : "text-ink-muted"].join(" ")}
              >
                Rs
              </button>
              <button
                type="button"
                onClick={() => setValue("discount_type", "%")}
                className={["rounded px-2 py-1", discountType === "%" ? "bg-primary text-primary-fg" : "text-ink-muted"].join(" ")}
              >
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
                  <tr key={field.id} className="border-b border-border">
                    <td className="py-2 pr-2 text-ink-muted">{index + 1}</td>
                    <td className="py-2 pr-2 min-w-[180px]">
                      <input
                        {...register(`line_items.${index}.product_name`, { required: true })}
                        placeholder="Enter product name"
                        className={inputClass}
                      />
                    </td>
                    <td className="py-2 pr-2 w-24">
                      <input
                        {...register(`line_items.${index}.hsn_sac`, nullableText)}
                        className={inputClass}
                      />
                    </td>
                    <td className="py-2 pr-2 w-20">
                      <input {...register(`line_items.${index}.qty`)} className={inputClass} />
                    </td>
                    <td className="py-2 pr-2 w-20">
                      <input {...register(`line_items.${index}.uom`, nullableText)} className={inputClass} />
                    </td>
                    <td className="py-2 pr-2 w-24">
                      <input {...register(`line_items.${index}.price`)} className={inputClass} />
                    </td>
                    <td className="py-2 pr-2 w-24">
                      <input {...register(`line_items.${index}.discount`)} className={inputClass} />
                    </td>
                    <td className="py-2 pr-2 w-20">
                      <select {...register(`line_items.${index}.gst_rate`)} className={inputClass}>
                        {GST_RATES.map((r) => (
                          <option key={r} value={r}>
                            {r}%
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 pr-2 text-right font-medium">
                      {moneyFmt(lineTaxableValue(lineItems?.[index] ?? emptyLineItem))}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => fields.length > 1 && remove(index)}
                        className="text-danger disabled:opacity-30"
                        disabled={fields.length <= 1}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-highlight font-semibold">
                  <td colSpan={8} className="py-2 pr-2 text-right">
                    Total Inv. Val.
                  </td>
                  <td className="py-2 pr-2 text-right">{moneyFmt(totals.subtotal)}</td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
          <button
            type="button"
            onClick={() => append(emptyLineItem)}
            className="mt-3 text-sm font-medium text-primary hover:underline"
          >
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
                <label className={labelClass}>Terms & conditions — title</label>
                <input {...register("terms_title", nullableText)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>Terms & conditions — detail</label>
                <textarea {...register("terms_detail", nullableText)} rows={3} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>Notes</label>
                <textarea {...register("notes", nullableText)} rows={2} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>
                  Document note / Remarks <span className="normal-case text-ink-muted">(not visible on print)</span>
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
                <span className="text-ink-muted">Total Tax</span>
                <span className="tabular-nums">{moneyFmt(totals.taxTotal)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink-muted">TCS</span>
                <input {...register("tcs")} className={inputClass + " w-28 text-right"} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink-muted">
                  Discount {discountType === "%" ? "(%)" : "(Rs)"}
                </span>
                <input {...register("discount_value")} className={inputClass + " w-28 text-right"} />
              </div>
              <label className="flex items-center justify-between">
                <span className="text-ink-muted">Round off</span>
                <input type="checkbox" {...register("round_off")} className="h-4 w-4" />
              </label>
              <div className="flex justify-between rounded-md bg-highlight px-3 py-2 text-base font-semibold text-gold">
                <span>Grand Total</span>
                <span className="tabular-nums">₹ {moneyFmt(totals.grandTotal)}</span>
              </div>
              <p className="font-serif text-xs italic text-ink-muted">
                {amountInWords(totals.grandTotal)}
              </p>

              <div className="pt-2">
                <label className={labelClass}>Payment type *</label>
                <div className="flex flex-wrap gap-2">
                  {(["credit", "cash", "cheque", "online"] as const).map((type) => (
                    <PaymentPill
                      key={type}
                      type={type}
                      active={paymentType === type}
                      onClick={() => setValue("payment_type", type)}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {saveMutation.isError && (
          <p className="text-sm text-danger">
            {saveMutation.error instanceof Error
              ? saveMutation.error.message
              : "Could not save the invoice. Please check the form and try again."}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button type="submit" disabled={saveMutation.isPending} className={primaryButtonClass}>
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
          {isEdit && existingInvoice && (
            <button type="button" onClick={handleDownload} className={secondaryButtonClass}>
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
