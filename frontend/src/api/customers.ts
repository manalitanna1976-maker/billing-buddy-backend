import { apiClient } from "./client";

// Mirrors backend/app/schemas/customer.py — gstin and pan are separate
// fields (split from a single gstin_pan column per architect review).
export interface Customer {
  id: string;
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

export type CustomerInput = Omit<Customer, "id">;

export async function searchCustomers(q: string): Promise<Customer[]> {
  const { data } = await apiClient.get<Customer[]>("/customers", { params: { q } });
  return data;
}

export async function listCustomers(
  params: { limit?: number; offset?: number; q?: string } = {},
): Promise<Customer[]> {
  const { data } = await apiClient.get<Customer[]>("/customers", {
    params: { limit: 200, ...params },
  });
  return data;
}

export async function getCustomer(id: string): Promise<Customer> {
  const { data } = await apiClient.get<Customer>(`/customers/${id}`);
  return data;
}

export async function createCustomer(
  body: Partial<CustomerInput> & { name: string },
): Promise<Customer> {
  const { data } = await apiClient.post<Customer>("/customers", body);
  return data;
}

export async function updateCustomer(
  id: string,
  body: Partial<CustomerInput>,
): Promise<Customer> {
  const { data } = await apiClient.put<Customer>(`/customers/${id}`, body);
  return data;
}
