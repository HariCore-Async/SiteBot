/* SiteBot browser client: build your own chat UI on your website, in any framework, with no server code.
 *
 *   <script src="https://YOUR-SITEBOT/sitebot-client.js"></script>
 *   const bot = SiteBot.connect({ key: "pk_..." });
 *   const info = await bot.config();              // { name, greeting, suggestions, ... }
 *   const reply = await bot.ask("Do you ship to Canada?", {
 *     onToken: (text, soFar) => render(soFar),      // streamed text as it arrives
 *   });                                            // { answer, sources, grounded, messageId }
 *
 * It uses your public pk_ key, so it only works on the bot's own website (checked by the browser's Origin header).
 * Never put an sk_ server key in a web page; that's for the server API. No dependencies; works as a plain script,
 * or `import`/`require` it from a bundle (it also sets window.SiteBot). */
(function (root) {
  var STORE = "sitebot_visitor_";
  var defaultHost = (function () {
    try {
      return new URL(document.currentScript.src).origin;
    } catch (e) {
      return "";
    }
  })();

  function randomId() {
    var raw = (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : Date.now() + "" + Math.random()).replace(/[^A-Za-z0-9]/g, "");
    return (raw + "0000000000000000").slice(0, 32);
  }

  function store(name, value) {
    try {
      if (value === undefined) return root.localStorage.getItem(name);
      root.localStorage.setItem(name, value);
    } catch (e) {
      /* storage blocked: the conversation lasts for this page */
    }
    return value;
  }

  async function errorOf(res) {
    try {
      var data = await res.json();
      if (typeof data.detail === "string") return new Error(data.detail);
    } catch (e) {
      /* not JSON */
    }
    return new Error("SiteBot request failed (" + res.status + ")");
  }

  function connect(options) {
    options = options || {};
    if (!options.key || options.key.indexOf("pk_") !== 0) throw new Error("SiteBot.connect needs your public pk_ key.");
    var host = (options.host || defaultHost).replace(/\/$/, "");
    if (!host) throw new Error("SiteBot.connect: pass { host: 'https://your-sitebot' }.");
    var base = host + "/api/public/" + encodeURIComponent(options.key);
    var visitor = options.visitorId || store(STORE + options.key) || store(STORE + options.key, randomId());

    async function get(path) {
      var sep = path.indexOf("?") >= 0 ? "&" : "?";
      var res = await fetch(base + path + sep + "visitor_id=" + visitor, { credentials: "omit" });
      if (!res.ok) throw await errorOf(res);
      return res.json();
    }

    async function post(path, body) {
      return fetch(base + path, {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ visitor_id: visitor }, body)),
      });
    }

    return {
      get visitorId() {
        return visitor;
      },

      /** The bot's name, greeting, suggested questions and widget style. */
      config: function () {
        return get("/config");
      },

      /** This visitor's conversation so far: [{ id, role, content, sources, grounded, created_at }]. */
      history: function () {
        return get("/messages");
      },

      /** Asks a question. Calls onToken(text, soFar) while streaming; resolves with the final answer. */
      ask: async function (question, handlers) {
        handlers = handlers || {};
        var res = await fetch(base + "/messages", {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ visitor_id: visitor, content: question }),
          signal: handlers.signal,
        });
        if (!res.ok || !res.body) throw await errorOf(res);
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        var answer = "";
        var result = null;
        for (;;) {
          var chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          var nl;
          while ((nl = buffer.indexOf("\n")) >= 0) {
            var line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (!line) continue;
            var ev = JSON.parse(line);
            if (handlers.onEvent) handlers.onEvent(ev);
            if (ev.type === "token") {
              answer += ev.text;
              if (handlers.onToken) handlers.onToken(ev.text, answer);
            } else if (ev.type === "replace") {
              // The answer was corrected after checking (for example an unsupported sentence was removed).
              answer = ev.text;
              if (handlers.onReplace) handlers.onReplace(answer);
              else if (handlers.onToken) handlers.onToken("", answer);
            } else if (ev.type === "done") {
              result = { answer: answer, sources: ev.sources, grounded: ev.grounded, messageId: ev.message_id };
            } else if (ev.type === "error") {
              throw new Error(ev.message);
            }
          }
        }
        if (!result) throw new Error("The answer was interrupted. Please try again.");
        return result;
      },

      /** Rates an answer ("up" or "down"); owners see ratings on their Embed page. */
      feedback: async function (messageId, rating, comment) {
        var res = await post("/feedback", { message_id: messageId, rating: rating, comment: comment || "" });
        if (!res.ok) throw await errorOf(res);
        return res.json();
      },

      /** Starts a fresh conversation for this visitor (the old one stays visible to the bot's owner). */
      newConversation: function () {
        visitor = store(STORE + options.key, randomId());
        return visitor;
      },
    };
  }

  var SiteBot = { connect: connect };
  root.SiteBot = SiteBot;
  if (typeof module === "object" && module.exports) module.exports = SiteBot;
})(typeof window !== "undefined" ? window : this);
