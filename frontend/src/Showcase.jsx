import { useCallback, useEffect, useRef, useState } from "react";
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
  {
    site: "harborbank.com",
    q: "Is there a fee for international transfers?",
    a: [["International transfers cost $15, and incoming transfers are free", 1], ["Premier accounts pay no transfer fees", 2]],
    sources: ["Fees", "Premier banking"],
  },
  {
    site: "summitgym.com",
    q: "Can I freeze my membership?",
    a: [["You can freeze your membership for up to three months a year", 1], ["Requests need seven days' notice at the front desk or in the app", 1]],
    sources: ["Membership terms"],
  },
  {
    site: "greenleafcity.gov",
    q: "When is bulk trash pickup?",
    a: [["Bulk items are collected on the first Monday of each month", 1], ["Schedule a pickup online by the Friday before", 2]],
    sources: ["Trash and recycling", "Request a pickup"],
  },
  {
    site: "lumentech.io",
    q: "Does the API support webhooks?",
    a: [["Yes, webhooks fire on every document and signature event", 1], ["You can manage endpoints under Settings → Developers", 2]],
    sources: ["Webhooks", "Developer settings"],
  },
  {
    site: "oakwoodhotel.com",
    q: "What time is check-in?",
    a: [["Check-in starts at 3 p.m. and check-out is at 11 a.m.", 1], ["Early check-in is free when a room is ready", 1]],
    sources: ["Your stay"],
  },
  {
    site: "brightpathlearning.com",
    q: "Are the courses self-paced?",
    a: [["All courses are self-paced, with lifetime access to the material", 1], ["Live office hours run every Thursday", 2]],
    sources: ["How it works", "Community"],
  },
  {
    site: "velocitymotors.com",
    q: "How often should I service my car?",
    a: [["We recommend a service every 10,000 miles or 12 months", 1], ["Booking online gets 10% off labor", 2]],
    sources: ["Service schedule", "Offers"],
  },
  {
    site: "pawsandco.com",
    q: "Is grooming available on weekends?",
    a: [["Grooming is open Saturdays from 9 a.m. to 4 p.m.", 1], ["Sunday appointments are for members only", 1]],
    sources: ["Grooming"],
  },
  {
    site: "cedarlaw.com",
    q: "Do you offer free consultations?",
    a: [["Your first 30-minute consultation is free", 1], ["We handle family, property and employment law", 2]],
    sources: ["Consultations", "Practice areas"],
  },
  {
    site: "skylineairways.com",
    q: "How many bags can I check?",
    a: [["Economy fares include one checked bag up to 23 kg", 1], ["Business class includes two bags up to 32 kg each", 1]],
    sources: ["Baggage allowance"],
  },
  {
    site: "freshcartgrocery.com",
    q: "What's the minimum order for delivery?",
    a: [["Delivery is free on orders over $35", 1], ["Smaller orders have a $4.99 delivery fee", 1]],
    sources: ["Delivery"],
  },
];

const INTERVAL_MS = 2500;
const WHEEL_COOLDOWN_MS = 450;

export default function Showcase() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const ref = useRef(null);
  const lastWheel = useRef(0);
  const touchX = useRef(null);
  const n = EXAMPLES.length;

  const step = useCallback((d) => setIndex((i) => (i + d + n) % n), [n]);

  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => step(1), INTERVAL_MS);
    return () => clearInterval(t);
  }, [paused, step]);

  // Scrolling over the card flips through examples instead of scrolling the page.
  useEffect(() => {
    const el = ref.current;
    const onWheel = (e) => {
      const delta = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
      if (Math.abs(delta) < 4) return;
      e.preventDefault();
      const now = Date.now();
      if (now - lastWheel.current < WHEEL_COOLDOWN_MS) return;
      lastWheel.current = now;
      step(delta > 0 ? 1 : -1);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [step]);

  // Position of each slide relative to the current one, taking the shorter way round.
  const offsetOf = (i) => {
    let d = i - index;
    if (d > n / 2) d -= n;
    if (d < -n / 2) d += n;
    return d;
  };

  return (
    <div
      className="showcase"
      ref={ref}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onTouchStart={(e) => {
        touchX.current = e.touches[0].clientX;
        setPaused(true);
      }}
      onTouchEnd={(e) => {
        const dx = e.changedTouches[0].clientX - (touchX.current ?? e.changedTouches[0].clientX);
        if (Math.abs(dx) > 40) step(dx < 0 ? 1 : -1);
        touchX.current = null;
        setPaused(false);
      }}
    >
      <div className="preview">
        <div className="preview-bar">
          <span className="dot red" />
          <span className="dot yellow" />
          <span className="dot green" />
          <span className="preview-site" key={index}>
            {EXAMPLES[index].site}
          </span>
        </div>
        <div className="preview-stage" aria-live="polite">
          {EXAMPLES.map((ex, i) => {
            const d = offsetOf(i);
            return (
              <div
                key={ex.site}
                className={`preview-body ${d === 0 ? "active" : ""}`}
                aria-hidden={d !== 0}
                style={{ "--offset": Math.max(-1, Math.min(1, d)) }}
              >
                <div className="preview-q">{ex.q}</div>
                <div className="preview-a">
                  <span className="preview-avatar">
                    <LogoMark size={22} />
                  </span>
                  <div>
                    <p>
                      {ex.a.map(([text, num], k) => (
                        <span key={k}>
                          {text} <span className="cite">{num}</span>.{k < ex.a.length - 1 ? " " : ""}
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
            );
          })}
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
      <p className="showcase-hint">Scroll over the card to browse examples</p>
    </div>
  );
}
