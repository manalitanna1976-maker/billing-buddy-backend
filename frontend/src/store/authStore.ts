import { create } from "zustand";

const EMAIL_STORAGE_KEY = "billing-buddy-email";

interface AuthState {
  // null = not yet checked; true/false = known. Drives the route guard.
  authed: boolean | null;
  // Cached for display only (sidebar / profile). The real session is the
  // httpOnly cookie -- this is not a credential.
  email: string | null;
  setAuthed: (authed: boolean | null) => void;
  setEmail: (email: string | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  authed: null,
  email: localStorage.getItem(EMAIL_STORAGE_KEY),
  setAuthed: (authed) => set({ authed, ...(authed === false ? { email: null } : {}) }),
  setEmail: (email) => {
    if (email) localStorage.setItem(EMAIL_STORAGE_KEY, email);
    else localStorage.removeItem(EMAIL_STORAGE_KEY);
    set({ email });
  },
}));
