// Simple native-title tooltip — no fancy positioning library needed for a
// single help icon next to a label (design note: "doesn't need to be
// fancy").
export default function InfoTooltip({ text }: { text: string }) {
  return (
    <span
      title={text}
      tabIndex={0}
      className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-ink-muted text-[10px] font-semibold text-ink-muted align-middle"
      aria-label={text}
    >
      i
    </span>
  );
}
