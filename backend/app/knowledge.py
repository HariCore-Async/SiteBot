"""What a bot's owner teaches it directly: answers to questions and uploaded documents (PDF, Word, text, Markdown).

They're stored as chunks in KNOWLEDGE_GENERATION, so retrieval finds them alongside the website's pages, citations work
the same way, and re-indexing the website leaves them alone.
"""

import base64
import io
import re
import zipfile
from xml.etree import ElementTree

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .embeddings import embed_passages
from .ingest import chunk_text
from .models import KNOWLEDGE_GENERATION, Chunk, Knowledge, Site, utcnow

MAX_DOC_BYTES = 10 * 1024 * 1024
MAX_DOCS_PER_BOT = 50
MAX_ANSWERS_PER_BOT = 500
MAX_DOC_CHUNKS = 400
DOC_TYPES = (".pdf", ".docx", ".txt", ".md")


def knowledge_url(site: Site, k: Knowledge) -> str:
    """Where a citation of this knowledge points: the bot's website (there's no page of its own to link to)."""
    return f"{site.root_url.rstrip('/')}#sitebot-{k.kind}-{k.id}"


def citation_title(site: Site, k: Knowledge) -> str:
    return f"Answer from the {site.name} team" if k.kind == "answer" else k.filename or k.title


def _index(db: Session, site: Site, k: Knowledge, pieces: list[str]) -> None:
    url, title = knowledge_url(site, k), citation_title(site, k)
    db.execute(delete(Chunk).where(Chunk.site_id == site.id, Chunk.generation == KNOWLEDGE_GENERATION, Chunk.url == url))
    vectors = embed_passages([f"{title}\n{p}" for p in pieces]) if pieces else []
    for piece, vec in zip(pieces, vectors):
        db.add(Chunk(site_id=site.id, generation=KNOWLEDGE_GENERATION, url=url, title=title, content=piece, embedding=vec))
    k.chunks = len(pieces)
    k.updated_at = utcnow()
    # New knowledge can answer questions the old suggestions skipped; let them be made again.
    site.suggestions = None
    db.commit()


def save_answer(db: Session, site: Site, question: str, answer: str, author_id: int, k: Knowledge | None = None) -> Knowledge:
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise HTTPException(400, "Write both the question and its answer.")
    if not k:
        if db.scalar(select(func.count(Knowledge.id)).where(Knowledge.site_id == site.id, Knowledge.kind == "answer")) >= MAX_ANSWERS_PER_BOT:
            raise HTTPException(400, f"A bot can have up to {MAX_ANSWERS_PER_BOT} answers.")
        k = Knowledge(site_id=site.id, kind="answer", author_id=author_id)
        db.add(k)
    k.title, k.content = question, answer
    db.flush()
    # Question and answer together, so a visitor's question finds it and the bot can cite it. Written as a plain FAQ entry:
    # "Question:/Answer:" labels make the answer checker read it as another assistant's reply rather than a fact.
    text = f"Frequently asked question: {question}\n{answer}"
    _index(db, site, k, chunk_text(text) or [text])
    return k


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:  # noqa: BLE001  (pypdf raises many kinds)
            raise HTTPException(400, f"That PDF couldn't be read: {e}")
    if name.endswith(".docx"):
        try:
            xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
        except (zipfile.BadZipFile, KeyError):
            raise HTTPException(400, "That Word file couldn't be read. Save it as .docx and try again.")
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ElementTree.fromstring(xml)
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
        return "\n".join(p for p in paragraphs if p.strip())
    raise HTTPException(400, "Upload a PDF, Word (.docx), text (.txt) or Markdown (.md) file.")


def save_document(db: Session, site: Site, filename: str, data_b64: str, author_id: int) -> Knowledge:
    filename = re.sub(r"[^\w.\- ()]", "_", filename.strip())[:200] or "document.txt"
    if not filename.lower().endswith(DOC_TYPES):
        raise HTTPException(400, "Upload a PDF, Word (.docx), text (.txt) or Markdown (.md) file.")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except ValueError:
        raise HTTPException(400, "The file didn't upload correctly. Please try again.")
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(413, f"Files can be up to {MAX_DOC_BYTES // (1024 * 1024)} MB.")
    if db.scalar(select(func.count(Knowledge.id)).where(Knowledge.site_id == site.id, Knowledge.kind == "document")) >= MAX_DOCS_PER_BOT:
        raise HTTPException(400, f"A bot can have up to {MAX_DOCS_PER_BOT} documents. Remove one first.")
    text = re.sub(r"[ \t]+", " ", extract_text(filename, data)).strip()
    pieces = chunk_text(text)
    if not pieces:
        raise HTTPException(400, "No text was found in that file. (Scanned PDFs without a text layer can't be read.)")
    k = Knowledge(site_id=site.id, kind="document", title=filename, filename=filename, size=len(data), author_id=author_id, content=text[:200000])
    db.add(k)
    db.flush()
    _index(db, site, k, pieces[:MAX_DOC_CHUNKS])
    return k


def remove(db: Session, site: Site, k: Knowledge) -> None:
    db.execute(delete(Chunk).where(Chunk.site_id == site.id, Chunk.generation == KNOWLEDGE_GENERATION, Chunk.url == knowledge_url(site, k)))
    db.delete(k)
    site.suggestions = None
    db.commit()


def knowledge_out(k: Knowledge) -> dict:
    return {
        "id": k.id, "kind": k.kind, "title": k.title, "content": k.content if k.kind == "answer" else k.content[:300],
        "filename": k.filename, "size": k.size, "chunks": k.chunks,
        "created_at": k.created_at.isoformat(), "updated_at": k.updated_at.isoformat(),
    }

