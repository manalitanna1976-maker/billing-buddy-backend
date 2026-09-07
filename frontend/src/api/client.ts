import axios from "axios";

import { useAuthStore } from "../store/authStore";

// The session lives in an httpOnly cookie set by the backend on login/signup.
// `withCredentials` makes the browser send it on every request; the frontend
// never sees or stores the token (XSS can't lift it from localStorage).
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
});

// A 401 from any endpoint (other than login/signup / the /auth/me probe, which
// surface their own state) means the session is gone -- mark unauthenticated so
// the app falls back to the login screen instead of looping on failed requests.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error?.config?.url ?? "";
    const isAuthProbe = url.includes("/auth/");
    if (error?.response?.status === 401 && !isAuthProbe) {
      useAuthStore.getState().setAuthed(false);
    }
    return Promise.reject(error);
  },
);
