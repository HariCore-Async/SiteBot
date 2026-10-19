import { useEffect, useState } from "react";
import { LogoMark } from "./Icons.jsx";

// Illustrative examples for the landing page (fictional sites).
const EXAMPLES = [
  {
    site: "acmecloud.com",
    q: "What does the Pro plan include?",
    a: [["Pro includes unlimited e-signatures, contract templates and priority support", 1], ["Teams can add members at any time", 2]],
    sources: ["Pricing", "Teams and billing"],
  },
  {
    site: "riverside.edu",
    q: "When is the fall application deadline?",
    a: [["Fall applications close on March 1, and scholarship priority is January 15", 1], ["Decisions are emailed within four weeks", 2]],
    sources: ["Admissions", "After you apply"],
  },
  {
    site: "northwindclinic.org",
    q: "Do you accept walk-in patients?",
    a: [["Yes, walk-ins are seen weekdays from 8 a.m. to 6 p.m.", 1], ["You can also book online to skip the wait", 2]],
    sources: ["Visit us", "Appointments"],
  },
  {
    site: "bluebirdbooks.com",
    q: "Do you ship internationally?",
    a: [["We ship to over 40 countries, with tracking on every order", 1], ["Delivery usually takes 5 to 10 business days", 1]],
    sources: ["Shipping and returns"],
  },
];

const INTERVAL_MS = 3000;

export default function Showcase() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % EXAMPLES.length), INTERVAL_MS);
    return () => clearInterval(t);
  }, [paused]);

  return (
    <div className="showcase" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="preview">
        <div className="preview-bar">
          <span className="dot red" />
          <span className="dot yellow" />
          <span className="dot green" />
          <span className="preview-site">{EXAMPLES[index].site}</span>
        </div>
        <div className="preview-stage" aria-live="polite">
          {EXAMPLES.map((ex, i) => (
            <div key={ex.site} className={`preview-body ${i === index ? "active" : ""}`} aria-hidden={i !== index}>
              <div className="preview-q">{ex.q}</div>
              <div className="preview-a">
                <span className="preview-avatar">
                  <LogoMark size={22} />
                </span>
                <div>
                  <p>
                    {ex.a.map(([text, n], k) => (
                      <span key={k}>
                        {text} <span className="cite">{n}</span>.{k < ex.a.length - 1 ? " " : ""}
                      </span>
                    ))}
                  </p>
                  <div className="sources">
                    {ex.sources.map((s, k) => (
                      <span key={s} className="source-chip">
                        <span className="source-n">{k + 1}</span>
                        <span className="source-title">{s}</span>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="showcase-dots" role="tablist" aria-label="Examples">
        {EXAMPLES.map((ex, i) => (
          <button
            key={ex.site}
            role="tab"
            aria-selected={i === index}
            aria-label={`Example ${i + 1}: ${ex.site}`}
            className={i === index ? "active" : ""}
            onClick={() => setIndex(i)}
          />
        ))}
      </div>
    </div>
  );
}
