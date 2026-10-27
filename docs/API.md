# SiteBot developer API

There are three ways to put a SiteBot chatbot on a website:

| Option | Where it runs | Key | Use it when |
|---|---|---|---|
| **Widget** (`embed.js`) | the website | public `pk_...` | you want a ready-made chat bubble. Style it on the Embed page. |
| **Browser client** (`sitebot-client.js`) | the website's own front end | public `pk_...` | you want your own UI in React, Vue or plain JS, with no server code. |
| **Server API** (`/api/v1`) | your backend | secret `sk_...` | you want your own UI and to keep the bot behind your server, or to use it from another app. |

All three give the same answers: grounded only in the bot's indexed pages, with numbered `[n]` citations and a list of sources. Each one is covered by the same limits, the owner's credits and the embed's daily limit. Conversations show on the Embed page in SiteBot.

Every option needs an **approved** embed. Open the Embed page (Home → *Add a chatbot to your website*) and request one. An admin approves it.

---

## Widget

```html
<script src="https://YOUR-SITEBOT/embed.js" data-bot="pk_..." async></script>
```

The Embed page sets the colour, position, theme (light, dark or auto), font, corner rounding, header title, launcher icon and label, greeting, and custom CSS. Custom CSS applies only inside the chat window. `@import` and `url()` are removed from it. "Powered by SiteBot" always stays in the widget.

## Browser client: `sitebot-client.js`

```html
<script src="https://YOUR-SITEBOT/sitebot-client.js"></script>
<script>
  const bot = SiteBot.connect({ key: "pk_..." });

  const info = await bot.config();       // { name, domain, favicon, greeting, suggestions, color, position, style }
  const past = await bot.history();      // this visitor's messages so far

  const reply = await bot.ask("Do you ship to Canada?", {
    onToken: (text, soFar) => render(soFar),   // streamed text
    onReplace: (full) => render(full),         // optional: the answer was corrected after checking
  });
  // reply = { answer, sources: [{ n, title, url }], grounded, messageId }

  await bot.feedback(reply.messageId, "up");   // or "down", with an optional comment
  bot.newConversation();                       // start fresh for this visitor
</script>
```

- It only works on the bot's own domain, `www.` and its subdomains, over HTTPS. The browser's `Origin` header is checked on every call. An admin can switch off "Only allow on <domain>" for an embed; then any HTTPS website may use it, the widget included.
- `SiteBot.connect` options:
  - `key` (required).
  - `host`: defaults to where the script was loaded from.
  - `visitorId`: defaults to a random id kept in `localStorage`, so a visitor's conversation continues.
- Errors (limits reached, not available on this website, rate limited) are thrown as `Error` with a message you can show to the visitor.
- It also works with `import`/`require` from a bundle, and it always sets `window.SiteBot`.

## Server API: `/api/v1`

Create a server key on the Embed page (*Build your own chat UI → Create server key*). It is shown **once**, and SiteBot only stores a hash of it. You can replace or revoke it there at any time.

```
Authorization: Bearer sk_...
```

- Call it from your server only. Any request with a browser `Origin` header is refused with `403`, so a key that ends up in front-end code doesn't work there.
- **`visitor_id`** is your own id for the end user: 1–64 characters, `A–Z a–z 0–9 _ . : @ -`. Use the same id to keep that user's history.
- **Limits:**
  - 120 requests a minute and 3000 an hour per embed.
  - 6 questions a minute and 60 an hour per `visitor_id`.
  - The embed's daily spending limit and the owner's credit limit also apply.

### `POST /api/v1/messages`

```json
{ "visitor_id": "user-123", "content": "What do you offer?", "conversation_id": 42, "new_conversation": false, "stream": true }
```

- `conversation_id`: optional. It continues that conversation, and it must belong to this `visitor_id`.
- `new_conversation`: with no `conversation_id`, `true` starts a new conversation. Otherwise the visitor's latest conversation continues, or a new one starts.
- `stream`: `true` (the default) returns NDJSON, one JSON event per line.

  ```
  {"type": "conversation", "conversation_id": 42}
  {"type": "user_saved", "message_id": 101, "chat_title": "What do you offer?"}
  {"type": "token", "text": "We offer "}
  {"type": "token", "text": "consulting [1]..."}
  {"type": "replace", "text": "…the full, checked answer…"}      (only if the answer was corrected)
  {"type": "done", "message_id": 102, "sources": [{"n": 1, "title": "Services", "url": "https://…"}], "grounded": true, "usage": null}
  {"type": "error", "message": "This assistant is taking a short break. Please try again later."}   (instead of done)
  ```

  Build the answer by appending `token` texts. On `replace`, swap in its text. `[n]` markers refer to `sources[n]`. `grounded: false` means the bot didn't find the answer on the website and said so.

- `stream: false` returns one JSON object:

  ```json
  { "conversation_id": 42, "message_id": 102, "answer": "We offer consulting [1]…", "sources": [{ "n": 1, "title": "Services", "url": "https://…" }], "grounded": true }
  ```

  If the bot can't answer right now (for example a limit was reached), it returns `503` with `{"detail": "..."}`.

### `GET /api/v1/bot`
The bot's `name`, `domain`, `favicon`, `greeting` and `suggestions`.

### `GET /api/v1/suggestions`
`{ "questions": [...] }`: starter questions the bot can answer.

### `GET /api/v1/conversations?visitor_id=user-123`
The visitor's conversations: `[{ conversation_id, title, updated_at }]`, newest first.

### `GET /api/v1/conversations/{conversation_id}/messages?visitor_id=user-123`
`[{ id, role: "user" | "assistant", content, sources, grounded, created_at, feedback }]`

### `POST /api/v1/feedback`
```json
{ "message_id": 102, "rating": "up", "comment": "optional" }
```
Rates an answer. Owners see ratings on the Embed page.

### Errors
| Status | Meaning |
|---|---|
| `401` | Missing or wrong server key |
| `403` | Called from a browser, or (public API) from a website the bot isn't allowed on |
| `404` | Embed not approved, turned off, or the conversation/answer isn't this visitor's |
| `422` | Invalid request body |
| `429` | Rate limited |
| `503` | Can't answer right now (daily limit or credits reached) |

Error bodies are `{"detail": "a readable message"}`.

## Examples

The Embed page shows these with your keys filled in.

**curl**
```bash
curl -N https://YOUR-SITEBOT/api/v1/messages \
  -H "Authorization: Bearer $SITEBOT_SERVER_KEY" -H "Content-Type: application/json" \
  -d '{"visitor_id": "user-123", "content": "What do you offer?"}'
```

**Python**
```python
import os, requests
r = requests.post("https://YOUR-SITEBOT/api/v1/messages",
                  headers={"Authorization": f"Bearer {os.environ['SITEBOT_SERVER_KEY']}"},
                  json={"visitor_id": "user-123", "content": "What do you offer?", "stream": False}, timeout=60)
print(r.json()["answer"])
```

**Node (Express pass-through stream)**
```js
app.post("/chat", async (req, res) => {
  const r = await fetch("https://YOUR-SITEBOT/api/v1/messages", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.SITEBOT_SERVER_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: req.user.id, content: req.body.message }),
  });
  res.status(r.status).type("application/x-ndjson");
  for await (const chunk of r.body) res.write(chunk);
  res.end();
});
```
