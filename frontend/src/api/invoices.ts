import { apiClient } from "./client";

// Numeric fields the backend sends back (Decimal-backed columns) may
// serialize as either a JSON number or a string depending on pydantic's
// encoder — treat them as opaque and always coerce with String()/Number()
// at the point of use rather than assuming one representation.
export type Decimalish = string | number;

export interface InvoiceLineItemInput {
  product_name: string;
  hsn_sac: string | null;
  qty: string;
  uom: string | null;
  price: string;
  discount: string;
  gst_rate: string;
}

export interface InvoiceLineItemRead {
  id: string;
  sr_no: number;
  product_name: string;
  hsn_sac: string | null;
  qty: Decimalish;
  uom: string | null;
  price: Decimalish;
  discount: Decimalish;
  gst_rate: Decimalish;
  line_total: Decimalish;
}

export interface InvoiceInput {
  customer_id: string;
  invoice_type: string | null;
  invoice_date: string;
  challan_no: string | null;
  challan_date: string | null;
  po_no: string | null;
  po_date: string | null;
  lr_no: string | null;
  eway_no: string | null;
  delivery_mode: string | null;
  due_date: string | null;
  bank_account_id: string | null;
  discount_type: "Rs" | "%";
  discount_value: string;
  tcs: string;
  round_off: boolean;
  terms_title: string | null;
  terms_detail: string | null;
  notes: string | null;
  remarks: string | null;
  payment_type: "credit" | "cash" | "cheque" | "online";
  line_items: InvoiceLineItemInput[];
}

export interface Invoice extends Omit<InvoiceInput, "discount_value" | "tcs" | "line_items"> {
  id: string;
  invoice_no: string;
  discount_value: Decimalish;
  tcs: Decimalish;
  taxable_total: Decimalish;
  tax_total: Decimalish;
  grand_total: Decimalish;
  status: string;
  line_items: InvoiceLineItemRead[];
}

export interface InvoiceListItem {
  id: string;
  invoice_no: string;
  invoice_date: string;
  grand_total: Decimalish;
  status: string;
}

export async function listInvoices(): Promise<InvoiceListItem[]> {
  const { data } = await apiClient.get<InvoiceListItem[]>("/invoices");
  return data;
}

export async function createInvoice(body: InvoiceInput): Promise<Invoice> {
  const { data } = await apiClient.post<Invoice>("/invoices", body);
  return data;
}

export async function getInvoice(id: string): Promise<Invoice> {
  const { data } = await apiClient.get<Invoice>(`/invoices/${id}`);
  return data;
}

export async function updateInvoice(id: string, body: InvoiceInput): Promise<Invoice> {
  const { data } = await apiClient.put<Invoice>(`/invoices/${id}`, body);
  return data;
}

export async function cancelInvoice(id: string): Promise<Invoice> {
  const { data } = await apiClient.delete<Invoice>(`/invoices/${id}`);
  return data;
}

export async function downloadInvoicePdf(id: string, invoiceNo: string): Promise<void> {
  const { data } = await apiClient.get(`/invoices/${id}/pdf`, { responseType: "blob" });
  const url = window.URL.createObjectURL(new Blob([data], { type: "application/pdf" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${invoiceNo}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
