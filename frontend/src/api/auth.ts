import { apiClient } from "./client";

export interface Me {
  business_id: string;
  business_name: string;
  email: string | null;
}

export async function signup(body: {
  business_name: string;
  email: string;
  password: string;
}): Promise<void> {
  // Session cookie is set by the response; nothing to store client-side.
  await apiClient.post("/auth/signup", body);
}

export async function login(body: { email: string; password: string }): Promise<void> {
  await apiClient.post("/auth/login", body);
}

export async function logout(): Promise<void> {
  await apiClient.post("/auth/logout");
}

export async function fetchMe(): Promise<Me> {
  const { data } = await apiClient.get<Me>("/auth/me");
  return data;
}
