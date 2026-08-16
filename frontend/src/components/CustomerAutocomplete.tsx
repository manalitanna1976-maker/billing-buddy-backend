import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Customer, createCustomer, searchCustomers } from "../api/customers";
import { inputClass } from "../styles";

interface Props {
  value: Customer | null;
  onChange: (customer: Customer) => void;
}

export default function CustomerAutocomplete({ value, onChange }: Props) {
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
    queryKey: ["customers", "search", debounced],
    queryFn: () => searchCustomers(debounced),
    enabled: debounced.trim().length > 0 && open,
  });

  const exactMatch = results.some((r) => r.name.toLowerCase() === query.trim().toLowerCase());

  async function handleCreate() {
    const customer = await createCustomer({ name: query.trim() });
    onChange(customer);
    setOpen(false);
  }

  function handleSelect(customer: Customer) {
    onChange(customer);
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
        placeholder="Customer name"
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
                {r.place_of_supply && (
                  <div className="text-xs text-ink-muted">{r.place_of_supply}</div>
                )}
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
