import { isAxiosError } from "axios";

/**
 * The backend returns errors in two shapes: a plain string `detail` for
 * hand-raised HTTPExceptions, and a list of pydantic validation-error objects
 * for request-schema failures. Normalise both into one readable string.
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    if (error.response?.status === undefined) {
      return "Network error — please check your connection and try again.";
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => {
          const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
          const msg = typeof d?.msg === "string" ? d.msg : null;
          if (!msg) return null;
          return loc ? `${loc}: ${msg}` : msg;
        })
        .filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
    if (error.response?.status === 429) {
      return "Too many attempts. Please wait a few minutes and try again.";
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
