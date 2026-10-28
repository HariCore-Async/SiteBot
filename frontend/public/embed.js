/* SiteBot website widget loader.
 * Usage: <script src="https://YOUR-SITEBOT/embed.js" data-bot="pk_..." async></script>
 * Adds a small iframe in the page corner. The chat bubble and window live inside it, served by SiteBot, so the
 * website's styles can't clash with them and SiteBot can refuse to load on websites the bot doesn't belong to. */
(function () {
  var script = document.currentScript;
  if (!script || window.__sitebotLoaded) return;
  var key = script.getAttribute("data-bot");
  if (!key) return console.warn("SiteBot: add data-bot=\"<your key>\" to the embed script tag.");
  window.__sitebotLoaded = true;

  var base = new URL(script.src).origin;
  var frame = document.createElement("iframe");
  frame.src = base + "/widget/" + encodeURIComponent(key) + "?origin=" + encodeURIComponent(location.origin);
  // The page (no query string or #fragment, which may hold personal data) for page-aware suggested questions.
  frame.src += "&page=" + encodeURIComponent(location.origin + location.pathname);
  // data-test: SiteBot's own "Test it" page, which works before approval for the signed-in owner.
  if (script.hasAttribute("data-test")) frame.src += "&test=1";
  frame.title = "Chat with us";
  frame.setAttribute("allowtransparency", "true");
  var side = "right";
  var CLOSED = { width: "84px", height: "84px" };

  function place(open) {
    var small = window.innerWidth < 480;
    var s = frame.style;
    s.position = "fixed";
    s.zIndex = "2147483000";
    s.border = "0";
    s.background = "transparent";
    s.colorScheme = "light";
    s.bottom = open && small ? "0" : "8px";
    s.left = side === "left" ? (open && small ? "0" : "8px") : "auto";
    s.right = side === "right" ? (open && small ? "0" : "8px") : "auto";
    s.width = open ? (small ? "100%" : "416px") : CLOSED.width;
    s.height = open ? (small ? "100%" : "min(680px, calc(100vh - 16px))") : CLOSED.height;
    s.maxHeight = "100vh";
    // The widget can't tell a phone from a narrow desktop window by its own width, so say which it is.
    if (frame.contentWindow) frame.contentWindow.postMessage({ type: "sitebot:layout", full: open && small }, base);
  }

  var open = false;
  place(false);
  // Stays invisible until the widget says it's ready, so a website the bot isn't allowed on shows nothing.
  frame.style.visibility = "hidden";
  window.addEventListener("message", function (e) {
    if (e.origin !== base || e.source !== frame.contentWindow || !e.data || e.data.type !== "sitebot:state") return;
    if (e.data.hidden) return frame.remove();
    frame.style.visibility = "visible";
    open = !!e.data.open;
    if (e.data.position === "left" || e.data.position === "right") side = e.data.position;
    // A launcher with a label is wider than the round bubble, and a proactive greeting sits above it.
    var size = e.data.size;
    if (size && size.width > 0 && size.height > 0) {
      CLOSED = { width: Math.min(size.width, 360) + "px", height: Math.min(size.height, 320) + "px" };
    }
    place(open);
  });
  window.addEventListener("resize", function () {
    place(open);
  });

  function mount() {
    document.body.appendChild(frame);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
