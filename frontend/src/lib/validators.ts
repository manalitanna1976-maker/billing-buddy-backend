// Mirrors backend/app/validators.py so the form fails fast before a round-trip.
export const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
export const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const IFSC_RE = /^[A-Z]{4}0[0-9A-Z]{6}$/;

export const gstinRule = {
  validate: (v: string | null | undefined) =>
    !v || v.trim() === "" || GSTIN_RE.test(v.trim().toUpperCase()) ||
    "Invalid GSTIN (e.g. 27AAPFU0939F1ZV)",
};
export const panRule = {
  validate: (v: string | null | undefined) =>
    !v || v.trim() === "" || PAN_RE.test(v.trim().toUpperCase()) ||
    "Invalid PAN (e.g. AAPFU0939F)",
};
export const ifscRule = {
  validate: (v: string | null | undefined) =>
    !v || v.trim() === "" || IFSC_RE.test(v.trim().toUpperCase()) ||
    "Invalid IFSC (e.g. HDFC0001234)",
};
