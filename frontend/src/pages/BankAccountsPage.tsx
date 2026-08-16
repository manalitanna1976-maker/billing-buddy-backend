import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";

import {
  BankAccount,
  createBankAccount,
  deleteBankAccount,
  listBankAccounts,
  updateBankAccount,
} from "../api/bankAccounts";
import AppShell from "../components/AppShell";
import {
  cardClass,
  cardTitleClass,
  dangerLinkClass,
  inputClass,
  labelClass,
  linkClass,
  primaryButtonClass,
} from "../styles";

function maskAccountNo(accountNo: string): string {
  if (accountNo.length <= 4) return accountNo;
  return "•••• " + accountNo.slice(-4);
}

export default function BankAccountsPage() {
  const queryClient = useQueryClient();
  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ["bank-accounts"],
    queryFn: listBankAccounts,
  });
  const { register, handleSubmit, reset } = useForm<Omit<BankAccount, "id">>({
    defaultValues: { bank_name: "", account_no: "", ifsc: "", is_default: false },
  });

  const createMutation = useMutation({
    mutationFn: createBankAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bank-accounts"] });
      reset();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBankAccount,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bank-accounts"] }),
  });

  const setDefaultMutation = useMutation({
    mutationFn: (id: string) => updateBankAccount(id, { is_default: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bank-accounts"] }),
  });

  return (
    <AppShell title="Bank Accounts">
      <div className="space-y-6">
        <div className={cardClass}>
          <h2 className={cardTitleClass}>Accounts on file</h2>
          {isLoading ? (
            <p className="text-sm text-ink-muted">Loading…</p>
          ) : accounts.length === 0 ? (
            <p className="text-sm text-ink-muted">No bank accounts yet — add one below.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="py-2 font-medium">Bank name</th>
                  <th className="py-2 font-medium">Account no.</th>
                  <th className="py-2 font-medium">IFSC</th>
                  <th className="py-2 font-medium"></th>
                  <th className="py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className="border-b border-border last:border-0">
                    <td className="py-2">{a.bank_name}</td>
                    <td className="py-2 tabular-nums">{maskAccountNo(a.account_no)}</td>
                    <td className="py-2 tabular-nums">{a.ifsc}</td>
                    <td className="py-2">
                      {a.is_default ? (
                        <span className="rounded-full bg-highlight px-2 py-0.5 text-xs font-medium text-gold">
                          Default
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setDefaultMutation.mutate(a.id)}
                          disabled={setDefaultMutation.isPending}
                          className={linkClass}
                        >
                          Set default
                        </button>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => deleteMutation.mutate(a.id)}
                        className={dangerLinkClass}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <form
          onSubmit={handleSubmit((values) => createMutation.mutate(values))}
          className={cardClass}
        >
          <h2 className={cardTitleClass}>Add bank account</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass}>Bank name</label>
              <input {...register("bank_name", { required: true })} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Account number</label>
              <input {...register("account_no", { required: true })} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>IFSC</label>
              <input {...register("ifsc", { required: true })} className={inputClass} />
            </div>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" {...register("is_default")} /> Set as default account
          </label>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className={primaryButtonClass + " mt-4"}
          >
            {createMutation.isPending ? "Adding…" : "Add bank account"}
          </button>
        </form>
      </div>
    </AppShell>
  );
}
