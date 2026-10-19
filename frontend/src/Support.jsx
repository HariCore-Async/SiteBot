const SUPPORT_EMAIL = "supportteamxdev@gmail.com";

const STEPS = [
  {
    title: "Add a website",
    text: "Paste any public website link under New chatbot. If that site is already in SiteBot, its chatbot opens straight away.",
  },
  {
    title: "SiteBot reads it",
    text: "It reads the site's public pages (and its PDFs, if you choose) and learns their content. You'll see a progress bar, and you can leave while it works.",
  },
  {
    title: "Ask anything",
    text: "The chatbot answers from that website only, with numbered citations and links to the exact pages it used.",
  },
  {
    title: "Compare and come back",
    text: "Open two chatbots side by side, and pick up any conversation where you left it. Start fresh whenever you like.",
  },
];

const FAQ = [
  {
    q: "Where do the answers come from?",
    a: "Only from the website the chatbot was built from. Every fact is linked to its source page, and each answer is checked against those pages before you see it. Anything the site doesn't support is removed.",
  },
  {
    q: "Why does the chatbot say it doesn't have that information?",
    a: "Because it couldn't find a clear answer on the website, and it would rather tell you than guess. Try rephrasing, or ask about something the site covers. On very large sites, the page may not have been read yet; see the next question.",
  },
  {
    q: "How much of a website is read?",
    a: "Up to 300 pages by default. If a site is clearly larger, you'll be told how many pages it has and roughly how long reading it will take, and you can choose to read all of it. Chatbots that stopped at 300 pages show a Read whole site button.",
  },
  {
    q: "Can it read PDFs?",
    a: "Yes. Tick “Also read PDFs linked from the site” when you create the chatbot. Admins can also turn PDFs on for an existing chatbot and re-index it. Scanned PDFs that contain only images have no text to read.",
  },
  {
    q: "Why were some pages skipped or blocked?",
    a: "SiteBot only reads public pages. Pages behind a login are skipped, and sites whose rules (robots.txt) or bot protection don't allow reading are respected, never bypassed.",
  },
  {
    q: "How do I sign in?",
    a: "With Google, or with your email or username and a password. New accounts confirm their email with a 6-digit code the first time.",
  },
  {
    q: "I signed up with Google. Can I use a password too?",
    a: "Yes. Open Settings (the person icon next to Sign out) and set a password. You can also choose a username there.",
  },
  {
    q: "I forgot my password.",
    a: "On the sign-in page, choose Forgot password?, enter your email or username, and we'll email you a code to set a new one.",
  },
  {
    q: "Why can't I sign in?",
    a: "Your organisation may require approval for new users. If so, an admin needs to approve your email or your company's domain. Contact your admin, or email us below.",
  },
  {
    q: "What are credits and limits?",
    a: "Answering questions uses an AI service that costs a small amount per question. Each person has a spending limit, shown in the Credits bar at the bottom of the sidebar. When you reach it, ask an admin to raise it.",
  },
  {
    q: "How do I keep a chatbot up to date?",
    a: "Websites change, so admins can re-index a chatbot from Admin → Bots. The chatbot keeps answering from its previous copy until the new one is ready.",
  },
  {
    q: "Can I remove a chatbot from my list?",
    a: "Yes. Hover over it in the sidebar and choose the bin icon. It's removed only for you, along with your conversation. Add it back any time by pasting its link.",
  },
];

export default function Support({ onBack, backLabel = "Back" }) {
  return (
    <div className="page support">
      {onBack && (
        <button className="link-btn support-back" onClick={onBack}>
          ← {backLabel}
        </button>
      )}

      <header className="support-head">
        <span className="eyebrow">Help and support</span>
        <h1>How SiteBot works</h1>
        <p>
          SiteBot turns any website into an assistant you can talk to. It reads the site, answers questions using only what the site says,
          and shows exactly where each answer came from, so you get facts you can check instead of guesses.
        </p>
      </header>

      <section className="support-section">
        <h2>Getting started</h2>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <span className="step-n">{i + 1}</span>
              <div>
                <strong>{s.title}</strong>
                <p>{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="support-section">
        <h2>Frequently asked questions</h2>
        <div className="faq">
          {FAQ.map((f) => (
            <details key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="support-section contact-card">
        <div>
          <h2>Still need help?</h2>
          <p>Email our support team and we'll get back to you. Include the website or chatbot you were using and what happened.</p>
        </div>
        <a className="btn primary" href={`mailto:${SUPPORT_EMAIL}?subject=SiteBot%20support`}>
          {SUPPORT_EMAIL}
        </a>
      </section>
    </div>
  );
}
