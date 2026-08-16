import { apiClient } from "./client";

export interface Business {
  id: string;
  name: string;
  gstin: string | null;
  address: string | null;
  state: string | null;
  phone: string | null;
  email: string | null;
  logo_url: string | null;
  signature_url: string | null;
  invoice_prefix: string;
  invoice_postfix: string;
}

export type BusinessUpdateInput = Partial<
  Pick<
    Business,
    | "name"
    | "gstin"
    | "address"
    | "state"
    | "phone"
    | "email"
    | "invoice_prefix"
    | "invoice_postfix"
  >
>;

export async function getBusiness(): Promise<Business> {
  const { data } = await apiClient.get<Business>("/business");
  return data;
}

export async function updateBusiness(body: BusinessUpdateInput): Promise<Business> {
  const { data } = await apiClient.put<Business>("/business", body);
  return data;
}

async function uploadFile(path: string, file: File): Promise<Business> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<Business>(path, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export const uploadLogo = (file: File) => uploadFile("/business/logo", file);
export const uploadSignature = (file: File) => uploadFile("/business/signature", file);
