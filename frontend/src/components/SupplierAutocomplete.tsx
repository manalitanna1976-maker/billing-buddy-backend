import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Supplier, createSupplier, searchSuppliers } from "../api/inventory";
import { inputClass } from "../styles";

interface Props {
  value: Supplier | null;
  onChange: (supplier: Supplier) => void;
}

export default function SupplierAutocomplete({ value, onChange }: Props) {
  const [query, setQuery] = useState(value?.name ?? "");
  const [debounced, setDebounced] = useState(query);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setQuery(value?.name ?? "");
  }, [value?.id, value?.name]);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const { data: results = [], isFetching } = useQuery({
    queryKey: ["suppliers", "search", debounced],
    queryFn: () => searchSuppliers(debounced),
    enabled: debounced.trim().length > 0 && open,
  });

  const exactMatch = results.some((r) => r.name.toLowerCase() === query.trim().toLowerCase());

  async function handleCreate() {
    const supplier = await createSupplier({
      name: query.trim(),
      gstin: null,
      phone: null,
      email: null,
      address: null,
      state_code: null,
    });
    onChange(supplier);
    setOpen(false);
  }

  function handleSelect(supplier: Supplier) {
    onChange(supplier);
    setOpen(false);
  }

  return (
    <div className="relative" ref={containerRef}>
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Supplier name"
        className={inputClass}
      />
      {open && debounced.trim() && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-border bg-surface shadow-lg">
          {isFetching && <li className="px-3 py-2 text-sm text-ink-muted">Searching…</li>}
          {!isFetching &&
            results.map((r) => (
              <li
                key={r.id}
                onMouseDown={() => handleSelect(r)}
                className="cursor-pointer px-3 py-2 text-sm text-ink hover:bg-primary/10"
              >
                <div className="font-medium">{r.name}</div>
                {r.gstin && <div className="text-xs text-ink-muted">{r.gstin}</div>}
              </li>
            ))}
          {!isFetching && !exactMatch && query.trim() && (
            <li
              onMouseDown={handleCreate}
              className="cursor-pointer border-t border-border px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10"
            >
              + Create "{query.trim()}"
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
