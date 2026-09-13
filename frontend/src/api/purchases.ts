import { apiClient } from "./client";

// Mirrors backend/app/schemas/purchase.py
export interface PurchaseLineItemInput {
  product_id?: string | null;
  product_name?: string | null;
  hsn_sac?: string | null;
  qty: string;
  uom?: string | null;
  price: string;
  discount?: string;
  gst_rate?: string;
}

export interface PurchaseLineItemRead extends PurchaseLineItemInput {
  id: string;
  sr_no: number;
  raw_description: string;
  line_total: string;
}

export interface PurchaseInput {
  supplier_id: string;
  invoice_no?: string | null;
  invoice_date?: string | null;
  po_no?: string | null;
  shipping_total?: string;
  other_charges?: string;
  round_off?: string;
  notes?: string | null;
  line_items: PurchaseLineItemInput[];
}

export interface Purchase {
  id: string;
  supplier_id: string | null;
  invoice_no: string | null;
  invoice_date: string | null;
  po_no: string | null;
  taxable_total: string;
  tax_total: string;
  shipping_total: string;
  other_charges: string;
  round_off: string;
  grand_total: string;
  currency: string;
  notes: string | null;
  origin: string;
  status: string;
  doc_type: string;
  line_items: PurchaseLineItemRead[];
}

export interface PurchaseListItem {
  id: string;
  invoice_no: string | null;
  po_no: string | null;
  invoice_date: string | null;
  supplier_name: string | null;
  grand_total: string;
  status: string;
  origin: string;
}

export async function listPurchases(
  params: { limit?: number; offset?: number } = {},
): Promise<PurchaseListItem[]> {
  const { data } = await apiClient.get<PurchaseListItem[]>("/purchases", {
    params: { limit: 200, ...params },
  });
  return data;
}

export async function getPurchase(id: string): Promise<Purchase> {
  const { data } = await apiClient.get<Purchase>(`/purchases/${id}`);
  return data;
}

export async function createPurchase(body: PurchaseInput): Promise<Purchase> {
  const { data } = await apiClient.post<Purchase>("/purchases", body);
  return data;
}
