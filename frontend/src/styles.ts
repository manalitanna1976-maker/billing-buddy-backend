// Shared Tailwind class strings so every page's form controls, cards, and
// buttons stay visually consistent with the approved design tokens instead
// of drifting page-to-page.

export const inputClass =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60";

export const selectClass = inputClass + " appearance-none";

export const labelClass = "mb-1 block text-xs font-medium text-ink-muted";

export const cardClass = "rounded-lg border border-border bg-surface p-5";

export const cardTitleClass = "font-serif text-base font-semibold text-ink mb-3";

export const primaryButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-50";

export const secondaryButtonClass =
  "inline-flex items-center justify-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-ink hover:bg-paper disabled:opacity-50";

export const dangerLinkClass = "text-sm font-medium text-danger hover:underline";

export const linkClass = "text-sm font-medium text-primary hover:underline";
