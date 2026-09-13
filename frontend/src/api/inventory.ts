import { apiClient } from "./client";

// Mirrors backend/app/schemas/inventory.py
export interface Product {
  id: string;
  name: string;
  hsn_sac: string | null;
  uom: string | null;
  current_qty: string;
  reorder_level: string | null;
  default_purchase_price: string | null;
  auto_created: boolean;
  needs_review: boolean;
}

export type ProductInput = {
  name: string;
  hsn_sac?: string | null;
  uom?: string | null;
  reorder_level?: string | null;
  default_purchase_price?: string | null;
};

export interface StockMovement {
  id: string;
  product_id: string;
  delta_qty: string;
  balance_after: string;
  reason: string;
  ref_type: string | null;
  ref_id: string | null;
  note: string | null;
  created_at: string;
}

export interface Supplier {
  id: string;
  name: string;
  gstin: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  state_code: string | null;
}

export type SupplierInput = Omit<Supplier, "id">;

export async function listProducts(
  params: { limit?: number; offset?: number; q?: string } = {},
): Promise<Product[]> {
  const { data } = await apiClient.get<Product[]>("/products", {
    params: { limit: 200, ...params },
  });
  return data;
}

export async function searchProducts(q: string): Promise<Product[]> {
  return listProducts({ q, limit: 20 });
}

export async function createProduct(body: ProductInput): Promise<Product> {
  const { data } = await apiClient.post<Product>("/products", body);
  return data;
}

export async function updateProduct(id: string, body: Partial<ProductInput>): Promise<Product> {
  const { data } = await apiClient.put<Product>(`/products/${id}`, body);
  return data;
}

export async function adjustStock(
  id: string,
  body: { delta_qty: string; note?: string | null },
): Promise<Product> {
  const { data } = await apiClient.post<Product>(`/products/${id}/adjust-stock`, body);
  return data;
}

export async function listStockMovements(id: string): Promise<StockMovement[]> {
  const { data } = await apiClient.get<StockMovement[]>(`/products/${id}/stock-movements`);
  return data;
}

export async function listSuppliers(
  params: { limit?: number; offset?: number; q?: string } = {},
): Promise<Supplier[]> {
  const { data } = await apiClient.get<Supplier[]>("/suppliers", {
    params: { limit: 200, ...params },
  });
  return data;
}

export async function searchSuppliers(q: string): Promise<Supplier[]> {
  return listSuppliers({ q, limit: 20 });
}

export async function createSupplier(body: SupplierInput): Promise<Supplier> {
  const { data } = await apiClient.post<Supplier>("/suppliers", body);
  return data;
}

export async function updateSupplier(
  id: string,
  body: Partial<SupplierInput>,
): Promise<Supplier> {
  const { data } = await apiClient.put<Supplier>(`/suppliers/${id}`, body);
  return data;
}
