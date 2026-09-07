import { apiClient } from "./client";

export interface IndianState {
  code: string;
  name: string;
  value: string; // "27-Maharashtra"
}

export async function listStates(): Promise<IndianState[]> {
  const { data } = await apiClient.get<IndianState[]>("/meta/states");
  return data;
}
