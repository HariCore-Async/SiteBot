# Answer quality

## Test questions (per website chatbot)

On a chatbot's **Test questions** tab, the owner (or an editor) lists up to 30 questions:

- with **what a good answer says** (optional): it passes when the answer states the same key facts. The fast AI model
  judges that; if it can't be reached, every number and name in the expected answer must appear in the answer.
- with no expected answer: any answer with sources passes.
- marked **the website doesn't cover this**: it passes when the bot says it doesn't know.

They run when someone presses **Run all**, and automatically after every re-read of the website. Each question is asked
the normal way, in a throwaway test chat. The answer cache is skipped, and the cost counts toward the chatbot's daily
limit like a visitor's question. A run stops early if the daily limit is reached. The last 20 runs are kept, with each
answer, its sources and why it passed or failed.

## The answer checker

After the model answers, a second check removes sentences that state facts the website doesn't. It used to send every
sentence to the fast model, which sometimes flagged a fully supported answer, so the visitor got "I don't know" for a
question the owner had taught (about 1 in 4 replays of one real case). Now:

- a sentence whose numbers and names all appear word for word in the excerpts is accepted without asking;
- short framing with no facts ("Yes.", "Good question!") is never dropped on its own;
- everything else is checked as before: a sentence is removed only if it's flagged twice in a row.

Made-up details are still caught (a made-up "Munich office with 40 staff" was removed in every replay), and many answers
now need no checking call at all, which saves time and cost.

## Answer cache

When the same first question (ignoring case, spacing and end punctuation) comes to the same bot again, the checked
answer and its sources are reused: it's instant, costs nothing, and still shows up as a conversation. Follow-up questions
are never cached, because they depend on the conversation. An entry only matches the bot's current index and answer
model, and it's cleared when:

- the website is re-read;
- the owner adds, edits or removes an answer or a document;
- a visitor marks that answer as not helpful;
- it's a week old.

Set `ANSWER_CACHE=false` to switch it off.

## Re-ranking: measured, not switched on

Idea: after the hybrid search (vector + full-text, fused), re-order the top candidates with a small cross-encoder before
the model sees the top 6. Measured with `backend/tools/retrieval_eval.py`: 120 questions written by the AI from random
passages of six real bots (Python docs, React, GitHub, two universities, Virtualan). For each question it checks where
the passage's page lands.

| | right page first | in top 3 | among the 6 the model reads | time per question (desktop CPU) |
|---|---|---|---|---|
| today | 69% | 82% | **89%** | — |
| re-ranked, top 20, whole passages | 75% | 87% | **92%** | 1.6 s |
| re-ranked, top 20, 700 characters | 68% | 86% | 92% | 0.7 s |
| re-ranked, top 12, 700 characters | 72% | 85% | 89% | 0.34 s |
| re-ranked, top 10, 500 characters | 72% | 85% | 90% | 0.19 s |

(Cross-encoder: `ms-marco-MiniLM-L-6-v2`, 80 MB. The 12-layer version and `jina-reranker-v1-tiny-en` crashed while loading
on Windows.)

What decides an answer is whether the right page is among the 6 excerpts the model reads. The fast settings don't change
that (89–90%, at most 1 question in 120). Only re-ranking whole passages helps (+3 points), and it adds about 1.6 s to
every answer on a desktop, more on Railway's shared CPU, plus the model's memory. **Not worth it for now.** Revisit if
bots get much bigger, or if test-question runs show the right pages aren't being found. Rerun the tool to check.
