import { useEffect, useId, useMemo, useRef, useState } from "react";

export type ModelOption = {
  value: string;
  label: string;
};

type ModelComboboxProps = {
  value: string;
  options: readonly ModelOption[];
  loading?: boolean;
  error?: string;
  onChange: (value: string) => void;
};

function ModelCombobox({
  value,
  options,
  loading = false,
  error = "",
  onChange,
}: ModelComboboxProps) {
  const generatedId = useId();
  const listId = `${generatedId}-list`;
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const exactMatch = options.some((option) => option.value === value);
  const visible = useMemo(() => {
    if (!value.trim() || exactMatch) return [...options];
    const query = value.trim().toLowerCase();
    return options.filter((option) => (
      option.value.toLowerCase().includes(query)
      || option.label.toLowerCase().includes(query)
    ));
  }, [exactMatch, options, value]);

  useEffect(() => {
    const onDocumentMouseDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocumentMouseDown);
    return () => document.removeEventListener("mousedown", onDocumentMouseDown);
  }, []);

  useEffect(() => {
    setActiveIndex(0);
  }, [open, value, options]);

  const selectOption = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setActiveIndex((current) => Math.min(current + 1, Math.max(visible.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Enter" && open && visible[activeIndex]) {
      event.preventDefault();
      selectOption(visible[activeIndex].value);
    }
  };

  return (
    <div className="model-combobox" ref={containerRef}>
      <div className="model-combobox-control">
        <input
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          className="model-combobox-toggle"
          aria-label="Show model list"
          aria-expanded={open}
          aria-controls={listId}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setOpen((current) => !current)}
        >
          ▾
        </button>
      </div>
      {open && (
        <ul id={listId} className="model-combobox-list" role="listbox">
          {loading && (
            <li className="model-combobox-status" role="presentation">Loading models from the selected endpoint…</li>
          )}
          {!loading && error && (
            <li className="model-combobox-status is-error" role="presentation">{error}</li>
          )}
          {!loading && !error && visible.length === 0 && (
            <li className="model-combobox-status" role="presentation">
              No models from this endpoint. Type a model or deployment name.
            </li>
          )}
          {visible.map((option, index) => (
            <li key={option.value} role="option" aria-selected={index === activeIndex}>
              <button
                type="button"
                className={index === activeIndex ? "is-active" : ""}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectOption(option.value)}
              >
                <strong>{option.value}</strong>
                {option.label !== option.value && <small>{option.label}</small>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default ModelCombobox;
