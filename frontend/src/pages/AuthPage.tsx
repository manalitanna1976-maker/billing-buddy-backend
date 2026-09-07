import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";

import { login, signup } from "../api/auth";
import { getErrorMessage } from "../lib/apiError";
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

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-sm text-danger">{message}</p>;
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

export default function AuthPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setAuthed = useAuthStore((s) => s.setAuthed);
  const setEmail = useAuthStore((s) => s.setEmail);
  const [tab, setTab] = useState<"login" | "signup">(
    location.pathname === "/signup" ? "signup" : "login",
  );

  const loginForm = useForm<LoginValues>();
  const signupForm = useForm<SignupValues>();

  async function onAuthed(email: string) {
    setEmail(email);
    setAuthed(true);
    await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    navigate("/");
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (_d, variables) => onAuthed(variables.email),
  });

  const signupMutation = useMutation({
    mutationFn: signup,
    onSuccess: (_d, variables) => onAuthed(variables.email),
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
                  {...loginForm.register("email", { required: "Email is required" })}
                  type="email"
                  autoComplete="email"
                  className={inputClass}
                />
                <FieldError message={loginForm.formState.errors.email?.message} />
              </div>
              <div>
                <label htmlFor="login-password" className={labelClass}>Password</label>
                <input
                  id="login-password"
                  {...loginForm.register("password", { required: "Password is required" })}
                  type="password"
                  autoComplete="current-password"
                  className={inputClass}
                />
                <FieldError message={loginForm.formState.errors.password?.message} />
              </div>
              {loginMutation.isError && (
                <p className="text-sm text-danger">
                  {getErrorMessage(loginMutation.error, "Invalid email or password.")}
                </p>
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
                  {...signupForm.register("business_name", { required: "Business name is required" })}
                  className={inputClass}
                />
                <FieldError message={signupForm.formState.errors.business_name?.message} />
              </div>
              <div>
                <label htmlFor="signup-email" className={labelClass}>Work email</label>
                <input
                  id="signup-email"
                  {...signupForm.register("email", {
                    required: "Email is required",
                    pattern: { value: /^[^@\s]+@[^@\s]+\.[^@\s]+$/, message: "Enter a valid email" },
                  })}
                  type="email"
                  autoComplete="email"
                  className={inputClass}
                />
                <FieldError message={signupForm.formState.errors.email?.message} />
              </div>
              <div>
                <label htmlFor="signup-password" className={labelClass}>Password</label>
                <input
                  id="signup-password"
                  {...signupForm.register("password", {
                    required: "Password is required",
                    minLength: { value: 8, message: "Password must be at least 8 characters" },
                  })}
                  type="password"
                  autoComplete="new-password"
                  className={inputClass}
                />
                <FieldError message={signupForm.formState.errors.password?.message} />
              </div>
              <div>
                <label htmlFor="signup-confirm-password" className={labelClass}>Confirm password</label>
                <input
                  id="signup-confirm-password"
                  {...signupForm.register("confirm_password", { required: "Please confirm your password" })}
                  type="password"
                  autoComplete="new-password"
                  className={inputClass}
                />
                <FieldError message={signupForm.formState.errors.confirm_password?.message} />
              </div>
              {signupMutation.isError && (
                <p className="text-sm text-danger">
                  {getErrorMessage(signupMutation.error, "Could not sign up — please try again.")}
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
