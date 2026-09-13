import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { fetchMe } from "./api/auth";
import BankAccountsPage from "./pages/BankAccountsPage";
import AuthPage from "./pages/AuthPage";
import BusinessProfilePage from "./pages/BusinessProfilePage";
import CustomersPage from "./pages/CustomersPage";
import InventoryPage from "./pages/InventoryPage";
import InvoiceFormPage from "./pages/InvoiceFormPage";
import InvoiceListPage from "./pages/InvoiceListPage";
import UserProfilePage from "./pages/UserProfilePage";
import { useAuthStore } from "./store/authStore";

function useSessionProbe() {
  const setAuthed = useAuthStore((s) => s.setAuthed);
  const setEmail = useAuthStore((s) => s.setEmail);
  const authed = useAuthStore((s) => s.authed);

  const query = useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (query.isSuccess) {
      setAuthed(true);
      setEmail(query.data.email ?? null);
    } else if (query.isError) {
      setAuthed(false);
    }
  }, [query.isSuccess, query.isError, query.data, setAuthed, setEmail]);

  return { authed, loading: query.isLoading };
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const authed = useAuthStore((s) => s.authed);
  if (authed === null) {
    return <div className="p-8 text-sm text-ink-muted">Loading…</div>;
  }
  return authed ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}

function Shell() {
  useSessionProbe();
  return (
    <Routes>
      <Route path="/login" element={<AuthPage />} />
      <Route path="/signup" element={<AuthPage />} />
      <Route path="/" element={<ProtectedRoute><InvoiceListPage /></ProtectedRoute>} />
      <Route path="/business" element={<ProtectedRoute><BusinessProfilePage /></ProtectedRoute>} />
      <Route path="/bank-accounts" element={<ProtectedRoute><BankAccountsPage /></ProtectedRoute>} />
      <Route path="/customers" element={<ProtectedRoute><CustomersPage /></ProtectedRoute>} />
      <Route path="/inventory" element={<ProtectedRoute><InventoryPage /></ProtectedRoute>} />
      <Route path="/invoices/new" element={<ProtectedRoute><InvoiceFormPage /></ProtectedRoute>} />
      <Route path="/invoices/:id/edit" element={<ProtectedRoute><InvoiceFormPage /></ProtectedRoute>} />
      <Route path="/profile" element={<ProtectedRoute><UserProfilePage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
