import { useQuery } from "@tanstack/react-query";

import { listStates } from "../api/meta";
import { inputClass } from "../styles";

interface Props {
  value: string | null | undefined;
  onChange: (value: string | null) => void;
  id?: string;
  allowBlank?: boolean;
}

/**
 * Indian state / UT picker. Emits the canonical "<code>-<Name>" string the
 * backend uses for GST intra/inter-state detection. If `value` is a legacy
 * free-text string that isn't in the list, it's shown as a disabled extra
 * option so nothing is silently lost.
 */
export default function StateSelect({ value, onChange, id, allowBlank = true }: Props) {
  const { data: states = [] } = useQuery({
    queryKey: ["meta", "states"],
    queryFn: listStates,
    staleTime: Infinity,
  });

  const known = states.some((s) => s.value === value);

  return (
    <select
      id={id}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className={inputClass}
    >
      {allowBlank && <option value="">Select state…</option>}
      {value && !known && (
        <option value={value}>{value} (unrecognised — please reselect)</option>
      )}
      {states.map((s) => (
        <option key={s.code} value={s.value}>
          {s.value}
        </option>
      ))}
    </select>
  );
}
