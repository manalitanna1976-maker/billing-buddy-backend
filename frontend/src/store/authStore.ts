import { create } from "zustand";

const STORAGE_KEY = "billing-buddy-token";
const EMAIL_STORAGE_KEY = "billing-buddy-email";

interface AuthState {
  token: string | null;
  // The backend has no GET /users/me endpoint (JWT only carries user_id and
  // business_id, no email/role) — cache the email the user typed at
  // login/signup so the profile page has something to show. Cleared on
  // logout.
  email: string | null;
  setToken: (token: string | null) => void;
  setEmail: (email: string | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(STORAGE_KEY),
  email: localStorage.getItem(EMAIL_STORAGE_KEY),
  setToken: (token) => {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(EMAIL_STORAGE_KEY);
    }
    set({ token, ...(token ? {} : { email: null }) });
  },
  setEmail: (email) => {
    if (email) localStorage.setItem(EMAIL_STORAGE_KEY, email);
    else localStorage.removeItem(EMAIL_STORAGE_KEY);
    set({ email });
  },
}));
