// Mirrors backend/app/constants/indian_states.py::same_gst_state — tolerant of
// "Maharashtra" vs "27-Maharashtra". Display-only; backend is authoritative.
function normalise(v: string | null | undefined): string | null {
  if (!v) return null;
  let s = v.trim();
  if (!s) return null;
  // strip a leading "NN-" / "NN " code
  if (s.length >= 3 && /^\d\d[-–— ,:]/.test(s)) s = s.slice(3).trim();
  return s.toLowerCase();
}

export function sameGstState(a: string | null | undefined, b: string | null | undefined): boolean {
  const na = normalise(a);
  const nb = normalise(b);
  return na != null && nb != null && na === nb;
}
