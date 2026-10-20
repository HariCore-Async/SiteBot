import { useState } from "react";
import BotInfo from "./BotInfo.jsx";
import { BotIcon } from "./Sidebar.jsx";
import { ArrowRightIcon, BeakerIcon, GlobeIcon, SearchIcon } from "./Icons.jsx";

function BotCard({ site, onChat }) {
  return (
    <div
      className="bot-card"
      role="button"
      tabIndex={0}
      onClick={() => onChat(site.id)}
      onKeyDown={(e) => e.key === "Enter" && onChat(site.id)}
    >
      <BotIcon site={site} size={32} />
      <div className="bot-name">{site.name} Chatbot</div>
      <BotInfo site={site} />
    </div>
  );
}

export default function Dashboard({ me, myBots, library, onCreate, onChat }) {
  const [query, setQuery] = useState("");
  const firstName = (me.name || "").split(" ")[0] || "there";
  const q = query.trim().toLowerCase();
  const shown = q ? library.filter((s) => `${s.name} ${s.domain}`.toLowerCase().includes(q)) : library;
  return (
    <div className="page">
      <div className="dash-head">
        <h1>Welcome, {firstName}</h1>
        <p className="muted">What would you like to do today?</p>
      </div>

      <div className="dash-options">
        <button className="dash-card" onClick={onCreate}>
          <span className="dash-icon">
            <GlobeIcon />
          </span>
          <h2>Create a chatbot</h2>
          <p className="muted">
            Paste any website link. We read its public pages and build a chatbot that answers only from that site, with sources.
          </p>
          <span className="dash-cta">
            Get started <ArrowRightIcon size={15} />
          </span>
        </button>

        <div className="dash-card disabled" aria-disabled="true">
          <span className="dash-icon">
            <BeakerIcon />
          </span>
          <h2>
            Test a website's chatbot <span className="pill">Coming soon</span>
          </h2>
          <p className="muted">Check how well the chatbot already on a website answers its visitors' questions.</p>
        </div>
      </div>

      {myBots.length > 0 && (
        <section className="dash-section">
          <h3 className="section-title">Your chatbots</h3>
          <div className="bot-grid">
            {myBots.slice(0, 6).map((s) => (
              <BotCard key={s.id} site={s} onChat={onChat} />
            ))}
          </div>
        </section>
      )}

      {library.length > 0 && (
        <section className="dash-section">
          <div className="section-head">
            <div>
              <h3 className="section-title">Library</h3>
              <p className="muted small">Every chatbot built on SiteBot. Open any of them and start asking; no need to add it first.</p>
            </div>
            <div className="bot-search library-search">
              <SearchIcon />
              <input type="search" placeholder="Search the library" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the library" />
            </div>
          </div>
          {shown.length ? (
            <div className="bot-grid">
              {shown.map((s) => (
                <BotCard key={s.id} site={s} onChat={onChat} />
              ))}
            </div>
          ) : (
            <p className="muted small">No chatbots match "{query.trim()}". Create one from its website link.</p>
          )}
        </section>
      )}
    </div>
  );
}
