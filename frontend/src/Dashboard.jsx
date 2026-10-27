import { ArrowRightIcon, CodeIcon, GlobeIcon } from "./Icons.jsx";

export default function Dashboard({ me, onChatWithBot, onEmbed }) {
  const firstName = (me.name || "").split(" ")[0] || "there";
  return (
    <div className="page wide">
      <div className="dash-head">
        <h1>Welcome, {firstName}</h1>
        <p className="muted">What would you like to do today?</p>
      </div>

      <div className="dash-options">
        <button className="dash-card" onClick={onChatWithBot}>
          <span className="dash-icon">
            <GlobeIcon />
          </span>
          <h2>Chat with a bot</h2>
          <p className="muted">
            Open your chatbots or any chatbot in the Library. Each one answers only from its website's pages, with sources.
          </p>
          <span className="dash-cta">
            Open <ArrowRightIcon size={15} />
          </span>
        </button>

        <button className="dash-card" onClick={onEmbed}>
          <span className="dash-icon">
            <CodeIcon />
          </span>
          <h2>Add a chatbot to your website</h2>
          <p className="muted">
            Put one of your chatbots on its own website with one line of code, or build your own chat UI with our API.
          </p>
          <span className="dash-cta">
            Set it up <ArrowRightIcon size={15} />
          </span>
        </button>
      </div>
    </div>
  );
}
