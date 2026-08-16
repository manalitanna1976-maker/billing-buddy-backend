import { useMutation } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";

import { login, signup } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import { inputClass, labelClass, primaryButtonClass } from "../styles";

interface LoginValues {
  email: string;
  password: string;
}

interface SignupValues {
  business_name: string;
  email: string;
  password: string;
  confirm_password: string;
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex-1 rounded-md py-2 text-sm font-semibold transition-colors",
        active ? "bg-primary text-primary-fg" : "text-ink-muted hover:text-ink",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

// The backend rate-limits repeated failed logins (per email and per IP —
// see backend/app/rate_limit.py) and returns 429 with a specific `detail`
// once the caller is locked out. Surface that distinctly from a plain
// wrong-password 401 so the user knows to wait rather than re-guessing.
function loginErrorMessage(error: unknown): string {
  if (isAxiosError(error) && error.response?.status === 429) {
    return (
      (error.response.data as { detail?: string } | undefined)?.detail ??
      "Too many login attempts. Please wait a few minutes and try again."
    );
  }
  return "Invalid email or password.";
}

export default function AuthPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);
  const setEmail = useAuthStore((s) => s.setEmail);
  const [tab, setTab] = useState<"login" | "signup">(
    location.pathname === "/signup" ? "signup" : "login",
  );

  const loginForm = useForm<LoginValues>();
  const signupForm = useForm<SignupValues>();

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (data, variables) => {
      setToken(data.access_token);
      setEmail(variables.email);
      navigate("/");
    },
  });

  const signupMutation = useMutation({
    mutationFn: signup,
    onSuccess: (data, variables) => {
      setToken(data.access_token);
      setEmail(variables.email);
      navigate("/");
    },
  });

  return (
    <div className="flex min-h-screen">
      <div className="hidden w-1/2 flex-col justify-between bg-primary p-12 text-primary-fg lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary-fg font-serif text-base font-semibold text-primary">
            B
          </div>
          <span className="font-serif text-xl font-semibold">Billing Buddy</span>
        </div>
        <div>
          <h2 className="font-serif text-3xl font-semibold leading-snug">
            GST-compliant invoices, without the spreadsheet gymnastics.
          </h2>
          <p className="mt-4 max-w-md text-primary-fg/80">
            Set up your business once — logo, bank details, GSTIN — then generate compliant sale
            invoices in minutes, with CGST/SGST/IGST calculated for you automatically.
          </p>
        </div>
        <p className="text-sm text-primary-fg/70">© {new Date().getFullYear()} Billing Buddy CRM</p>
      </div>

      <div className="flex w-full flex-col items-center justify-center bg-paper p-8 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex rounded-lg border border-border bg-surface p-1">
            <TabButton active={tab === "login"} onClick={() => setTab("login")}>
              Log in
            </TabButton>
            <TabButton active={tab === "signup"} onClick={() => setTab("signup")}>
              Create account
            </TabButton>
          </div>

          {tab === "login" ? (
            <form
              onSubmit={loginForm.handleSubmit((values) => loginMutation.mutate(values))}
              className="space-y-4"
            >
              <h1 className="font-serif text-2xl font-semibold text-ink">Welcome back</h1>
              <div>
                <label htmlFor="login-email" className={labelClass}>Email</label>
                <input
                  id="login-email"
                  {...loginForm.register("email", { required: true })}
                  type="email"
                  autoComplete="email"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="login-password" className={labelClass}>Password</label>
                <input
                  id="login-password"
                  {...loginForm.register("password", { required: true })}
                  type="password"
                  autoComplete="current-password"
                  className={inputClass}
                />
              </div>
              {loginMutation.isError && (
                <p className="text-sm text-danger">{loginErrorMessage(loginMutation.error)}</p>
              )}
              <button
                type="submit"
                disabled={loginMutation.isPending}
                className={primaryButtonClass + " w-full"}
              >
                {loginMutation.isPending ? "Logging in…" : "Log in"}
              </button>
            </form>
          ) : (
            <form
              onSubmit={signupForm.handleSubmit((values) => {
                if (values.password !== values.confirm_password) {
                  signupForm.setError("confirm_password", { message: "Passwords do not match" });
                  return;
                }
                signupMutation.mutate(values);
              })}
              className="space-y-4"
            >
              <h1 className="font-serif text-2xl font-semibold text-ink">Create your account</h1>
              <div>
                <label htmlFor="signup-business-name" className={labelClass}>Business name</label>
                <input
                  id="signup-business-name"
                  {...signupForm.register("business_name", { required: true })}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="signup-email" className={labelClass}>Work email</label>
                <input
                  id="signup-email"
                  {...signupForm.register("email", { required: true })}
                  type="email"
                  autoComplete="email"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="signup-password" className={labelClass}>Password</label>
                <input
                  id="signup-password"
                  {...signupForm.register("password", { required: true, minLength: 8 })}
                  type="password"
                  autoComplete="new-password"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="signup-confirm-password" className={labelClass}>Confirm password</label>
                <input
                  id="signup-confirm-password"
                  {...signupForm.register("confirm_password", { required: true })}
                  type="password"
                  autoComplete="new-password"
                  className={inputClass}
                />
                {signupForm.formState.errors.confirm_password && (
                  <p className="mt-1 text-sm text-danger">
                    {signupForm.formState.errors.confirm_password.message}
                  </p>
                )}
              </div>
              {signupMutation.isError && (
                <p className="text-sm text-danger">
                  Could not sign up — email may already be registered.
                </p>
              )}
              <button
                type="submit"
                disabled={signupMutation.isPending}
                className={primaryButtonClass + " w-full"}
              >
                {signupMutation.isPending ? "Creating…" : "Create account"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
