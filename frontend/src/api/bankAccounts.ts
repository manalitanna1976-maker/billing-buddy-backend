import { apiClient } from "./client";

export interface BankAccount {
  id: string;
  bank_name: string;
  account_no: string;
  ifsc: string;
  is_default: boolean;
}

export async function listBankAccounts(): Promise<BankAccount[]> {
  const { data } = await apiClient.get<BankAccount[]>("/bank-accounts");
  return data;
}

export async function createBankAccount(body: Omit<BankAccount, "id">): Promise<BankAccount> {
  const { data } = await apiClient.post<BankAccount>("/bank-accounts", body);
  return data;
}

export async function updateBankAccount(
  id: string,
  body: Partial<Omit<BankAccount, "id">>,
): Promise<BankAccount> {
  const { data } = await apiClient.put<BankAccount>(`/bank-accounts/${id}`, body);
  return data;
}

export async function deleteBankAccount(id: string): Promise<void> {
  await apiClient.delete(`/bank-accounts/${id}`);
}
