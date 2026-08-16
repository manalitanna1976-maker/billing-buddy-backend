import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { getBusiness } from "../api/business";
import AppShell from "../components/AppShell";
import { useAuthStore } from "../store/authStore";
import { cardClass, cardTitleClass, primaryButtonClass, secondaryButtonClass } from "../styles";

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-ink-muted">{label}</div>
      <div className="mt-1 rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink">
        {value}
      </div>
    </div>
  );
}

export default function UserProfilePage() {
  const navigate = useNavigate();
  const email = useAuthStore((s) => s.email);
  const setToken = useAuthStore((s) => s.setToken);
  const { data: business } = useQuery({ queryKey: ["business"], queryFn: getBusiness });

  function handleLogout() {
    setToken(null);
    navigate("/login");
  }

  return (
    <AppShell title="Your Profile">
      <div className="max-w-lg space-y-6">
        <div className={cardClass}>
          <h2 className={cardTitleClass}>Account</h2>
          <div className="space-y-3">
            <ReadOnlyField label="Email" value={email ?? "—"} />
            <ReadOnlyField label="Business" value={business?.name ?? "—"} />
            {/* The API has no role field on the current user — v1 signup always
                creates a single "owner" user per business, so this is a safe
                display default rather than a fabricated read from a real field. */}
            <ReadOnlyField label="Role" value="Owner" />
          </div>
        </div>

        <div className={cardClass}>
          <h2 className={cardTitleClass}>Password</h2>
          <p className="text-sm text-ink-muted">
            Changing your password isn't available yet — coming in a future release.
          </p>
          <button type="button" disabled className={secondaryButtonClass + " mt-3 cursor-not-allowed"}>
            Change password
          </button>
        </div>

        <button type="button" onClick={handleLogout} className={primaryButtonClass}>
          Log out
        </button>
      </div>
    </AppShell>
  );
}
