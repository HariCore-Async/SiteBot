import { useRef } from "react";

/** Tabs with keyboard support: arrow keys, Home and End move between them (only the selected one is a Tab stop). */
export function Tabs({ tabs, value, onChange, className = "", label }) {
  const ref = useRef(null);
  const onKeyDown = (e) => {
    const i = tabs.findIndex(([id]) => id === value);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const j = (next + tabs.length) % tabs.length;
    onChange(tabs[j][0]);
    requestAnimationFrame(() => ref.current?.querySelectorAll('[role="tab"]')[j]?.focus());
  };
  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label} ref={ref} onKeyDown={onKeyDown}>
      {tabs.map(([id, text, badge]) => (
        <button
          key={id}
          role="tab"
          id={`tab-${id}`}
          aria-selected={value === id}
          tabIndex={value === id ? 0 : -1}
          className={`tab ${value === id ? "active" : ""}`}
          onClick={() => onChange(id)}
        >
          {text}
          {badge && <span className="pill accent tab-badge">{badge}</span>}
        </button>
      ))}
    </div>
  );
}
