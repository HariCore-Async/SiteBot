import { timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";

export default function Dashboard({ me, myBots, libraryCount, onCreate, onChat }) {
  const firstName = (me.name || "").split(" ")[0] || "there";
  return (
    <div className="page">
      <div className="dash-head">
        <h1>Welcome, {firstName}</h1>
        <p className="muted">What would you like to do today?</p>
      </div>

      <div className="dash-options">
        <button className="dash-card" onClick={onCreate}>
          <span className="dash-icon">✨</span>
          <h2>Create a chatbot</h2>
          <p className="muted">
            Paste any website link. We read its public pages and build a chatbot that answers only from that site, with sources.
          </p>
          <span className="dash-cta">Get started →</span>
        </button>

        <div className="dash-card disabled" aria-disabled="true">
          <span className="dash-icon">🧪</span>
          <h2>
            Test a website's chatbot <span className="pill">Coming soon</span>
          </h2>
          <p className="muted">Check how well the chatbot already on a website answers its visitors' questions.</p>
        </div>
      </div>

      {myBots.length > 0 && (
        <>
          <h3 className="section-title">Your chatbots</h3>
          <div className="bot-grid">
            {myBots.slice(0, 6).map((s) => (
              <button key={s.id} className="bot-card" onClick={() => onChat(s.id)}>
                <BotIcon site={s} size={36} />
                <div>
                  <div className="bot-name">{s.name} Chatbot</div>
                  <div className="muted small">
                    {s.domain} · {s.pages_indexed} pages · {timeAgo(s.indexed_at)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {libraryCount > 0 && (
        <p className="library-hint">
          📚 {libraryCount} more chatbot{libraryCount === 1 ? " is" : "s are"} already in the library. Search for one in the sidebar.
        </p>
      )}
    </div>
  );
}
