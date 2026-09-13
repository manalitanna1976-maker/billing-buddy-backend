import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Product, searchProducts } from "../api/inventory";
import { inputClass } from "../styles";

interface Props {
  value: Product | null;
  freeTextValue?: string;
  onSelect: (product: Product) => void;
  onFreeTextChange: (name: string) => void;
}

export default function ProductAutocomplete({
  value,
  freeTextValue,
  onSelect,
  onFreeTextChange,
}: Props) {
  const [query, setQuery] = useState(value?.name ?? freeTextValue ?? "");
  const [debounced, setDebounced] = useState(query);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setQuery(value?.name ?? freeTextValue ?? "");
  }, [value?.id, value?.name, freeTextValue]);

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
    queryKey: ["products", "search", debounced],
    queryFn: () => searchProducts(debounced),
    enabled: debounced.trim().length > 0 && open,
  });

  function handleSelect(product: Product) {
    onSelect(product);
    setOpen(false);
  }

  return (
    <div className="relative" ref={containerRef}>
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          onFreeTextChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Product name"
        className={inputClass}
      />
      {open && debounced.trim() && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-border bg-surface shadow-lg">
          {isFetching && <li className="px-3 py-2 text-sm text-ink-muted">Searching…</li>}
          {!isFetching && results.length === 0 && (
            <li className="px-3 py-2 text-sm text-ink-muted">
              No match — will create "{query.trim()}" as a new product.
            </li>
          )}
          {!isFetching &&
            results.map((r) => (
              <li
                key={r.id}
                onMouseDown={() => handleSelect(r)}
                className="cursor-pointer px-3 py-2 text-sm text-ink hover:bg-primary/10"
              >
                <div className="font-medium">{r.name}</div>
                <div className="text-xs text-ink-muted">Qty in stock: {r.current_qty}</div>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
