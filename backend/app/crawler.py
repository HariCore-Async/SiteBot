"""Same-site crawler: sitemap + link discovery, robots.txt, login/bot-wall detection, optional Playwright render."""

import hashlib
import io
import logging
import re
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
import lxml.html
import trafilatura
from lxml import etree

from .config import settings

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 SiteBot/1.0"
)
ROBOTS_AGENT = "SiteBot"

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".css", ".js", ".json", ".xml", ".rss", ".atom", ".txt",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dmg", ".msi", ".apk",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".wav", ".ogg",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".woff", ".woff2", ".ttf", ".eot",
}
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|_ga|_gl|igshid|si)$", re.I)
LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|sign_in|signup|sign-up|register|auth|sso|oauth|account/login|users/sign_in)(/|$|\?)", re.I)
BOT_WALL_MARKERS = (
    "cf-chl", "challenge-platform", "just a moment...", "attention required! | cloudflare",
    "captcha", "are you a robot", "px-captcha", "perimeterx", "verify you are human",
    "access denied", "request unsuccessful. incapsula",
)
MIN_TEXT_CHARS = 200


class CrawlError(Exception):
    pass


@dataclass
class PageResult:
    url: str
    status: str  # indexed | login | blocked | failed | empty
    title: str = ""
    text: str = ""
    rendered: bool = False
    links: list[str] = field(default_factory=list)
    html: str = ""


# ---------- URL helpers ----------

def normalize_input_url(raw: str) -> tuple[str, str]:
    """Returns (domain key, start url). The domain key ignores www. and the path, so any page on a site maps to one bot."""
    raw = raw.strip()
    if not raw:
        raise CrawlError("Please enter a website link.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        raise CrawlError("That doesn't look like a valid website link.")
    if host in {"localhost"} or re.match(r"^\d+\.\d+\.\d+\.\d+$", host) or host.endswith((".local", ".internal")):
        raise CrawlError("Only public websites can be indexed.")
    domain = host[4:] if host.startswith("www.") else host
    return domain, canonical(raw)


def host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def canonical(url: str) -> str:
    p = urlparse(url)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)))
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((p.scheme.lower(), (p.netloc or "").lower(), path, "", query, ""))


def dedup_key(url: str) -> str:
    """The same page reached over http/https or with/without www. counts once."""
    p = urlparse(url)
    return f"{host_key(url)}{p.path}?{p.query}"


def is_crawlable(url: str, domain: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or host_key(url) != domain:
        return False
    ext = re.search(r"\.[a-z0-9]{2,5}$", p.path.lower())
    if ext and ext.group(0) in SKIP_EXTENSIONS:
        return False
    if LOGIN_PATH.search(p.path):
        return False
    # Avoid calendar/faceted-search traps.
    return len(p.query) < 120 and p.path.count("/") <= 8


# ---------- Extraction ----------

def extract_text(html: str, url: str) -> str:
    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True, favor_recall=True, deduplicate=True
    ) or ""
    if len(text) < MIN_TEXT_CHARS:
        # Landing pages are often lists of short blocks that trafilatura drops; fall back to visible body text.
        try:
            doc = lxml.html.fromstring(html)
            for bad in doc.xpath("//script|//style|//noscript|//svg|//template"):
                bad.drop_tree()
            body = doc.find("body")
            fallback = " ".join((body if body is not None else doc).text_content().split())
            if len(fallback) > len(text):
                text = fallback
        except (etree.ParserError, ValueError):
            pass
    return text.strip()


def extract_title(html: str) -> str:
    try:
        doc = lxml.html.fromstring(html)
    except (etree.ParserError, ValueError):
        return ""
    title = doc.findtext(".//title") or ""
    return " ".join(title.split())[:300]


def extract_links(html: str, base_url: str) -> list[str]:
    try:
        doc = lxml.html.fromstring(html, base_url=base_url)
        doc.make_links_absolute(base_url, resolve_base_href=True)
    except (etree.ParserError, ValueError):
        return []
    links = []
    for el, attr, link, _ in doc.iterlinks():
        if el.tag == "a" and attr == "href" and "nofollow" not in (el.get("rel") or ""):
            links.append(link.split("#", 1)[0])
    return links


def extract_site_identity(html: str, url: str, domain: str) -> tuple[str, str]:
    """Best-effort brand name and favicon for the bot."""
    label = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    name = ""
    favicon = urljoin(url, "/favicon.ico")
    try:
        doc = lxml.html.fromstring(html)
        for xp in ("//meta[@property='og:site_name']/@content", "//meta[@name='application-name']/@content"):
            vals = [v.strip() for v in doc.xpath(xp) if v.strip()]
            if vals and len(vals[0]) <= 40:
                name = vals[0]
                break
        if not name:
            title = doc.findtext(".//title") or ""
            parts = [p.strip() for p in re.split(r"\s[|\-–—:·•]\s|\s[|]\s?", title) if p.strip()]
            matches = [p for p in parts if label.lower() in p.lower().replace(" ", "") and len(p) <= 30]
            if matches:
                name = min(matches, key=len)
        icons = doc.xpath("//link[contains(translate(@rel,'ICON','icon'),'icon')]/@href")
        if icons:
            favicon = urljoin(url, icons[0])
    except (etree.ParserError, ValueError):
        pass
    if not name:
        name = label.replace("-", " ").title()
    name = re.sub(r"\.(com|org|net|io|co|in|ai|dev|app)$", "", name, flags=re.I) if name.lower() == domain else name
    return name, favicon


def classify(status_code: int, final_url: str, requested_url: str, html: str, text_len: int) -> str | None:
    """Returns login / blocked / failed, or None when the page is fine."""
    lower = html[:20000].lower()
    if status_code == 401:
        return "login"
    if LOGIN_PATH.search(urlparse(final_url).path) and not LOGIN_PATH.search(urlparse(requested_url).path):
        return "login"
    if status_code in (403, 429, 503) or (text_len < 800 and any(m in lower for m in BOT_WALL_MARKERS)):
        return "blocked"
    if status_code >= 400:
        return "failed"
    if 'type="password"' in lower or "type='password'" in lower or "type=password" in lower:
        if text_len < 1500:
            return "login"
    return None


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages[:60]).strip()


# ---------- Playwright ----------

class Renderer:
    """Lazily starts headless Chromium in the crawl thread; disables itself if unavailable."""

    def __init__(self) -> None:
        self.enabled = settings.enable_playwright
        self._pw = None
        self._browser = None

    def render(self, url: str) -> str | None:
        if not self.enabled:
            return None
        try:
            if self._browser is None:
                from playwright.sync_api import sync_playwright

                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = self._browser.new_page(user_agent=USER_AGENT)
            try:
                page.goto(url, wait_until="networkidle", timeout=25000)
                return page.content()
            finally:
                page.close()
        except Exception as e:  # noqa: BLE001  (Playwright raises many types; never fail the crawl over it)
            log.warning("Playwright render failed for %s: %s", url, e)
            if self._browser is None:
                self.enabled = False
            return None

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------- Crawl ----------

class Crawler:
    def __init__(
        self,
        domain: str,
        start_url: str,
        include_pdfs: bool,
        on_page: Callable[[PageResult], None],
        on_progress: Callable[[int, int], None],
        max_pages: int | None = None,
    ) -> None:
        self.domain = domain
        self.start_url = start_url
        self.include_pdfs = include_pdfs
        self.on_page = on_page
        self.on_progress = on_progress
        self.max_pages = max_pages or settings.max_pages
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            max_redirects=5,
        )
        self.robots: RobotFileParser | None = None
        self.renderer = Renderer()
        self.seen: set[str] = set()
        self.content_hashes: set[str] = set()
        self.homepage_html = ""
        self.homepage_url = ""

    # robots + sitemaps
    def _load_robots(self, base: str) -> list[str]:
        sitemaps: list[str] = []
        try:
            r = self.client.get(urljoin(base, "/robots.txt"))
            if r.status_code == 200 and "text" in r.headers.get("content-type", "text"):
                rp = RobotFileParser()
                rp.parse(r.text.splitlines())
                self.robots = rp
                sitemaps = list(rp.site_maps() or [])
        except httpx.HTTPError:
            pass
        return sitemaps or [urljoin(base, "/sitemap.xml"), urljoin(base, "/sitemap_index.xml")]

    def _allowed(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(ROBOTS_AGENT, url)

    def _sitemap_urls(self, sitemaps: list[str]) -> list[str]:
        urls: list[str] = []
        queue = deque(sitemaps[:5])
        fetched = 0
        while queue and fetched < 12 and len(urls) < self.max_pages * 5:
            sm = queue.popleft()
            fetched += 1
            try:
                r = self.client.get(sm)
                if r.status_code != 200:
                    continue
                root = etree.fromstring(r.content, parser=etree.XMLParser(recover=True, resolve_entities=False))
            except (httpx.HTTPError, etree.XMLSyntaxError, ValueError):
                continue
            if root is None:
                continue
            locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
            if root.tag.endswith("sitemapindex"):
                queue.extend(locs[:10])
            else:
                urls.extend(locs)
        cleaned = [canonical(u) for u in urls if is_crawlable(u, self.domain)]
        # Shallow pages first: they usually describe the site best.
        return sorted(dict.fromkeys(cleaned), key=lambda u: (urlparse(u).path.count("/"), len(u)))

    def _fetch(self, url: str) -> tuple[str, PageResult | None, httpx.Response | None]:
        try:
            r = self.client.get(url)
            return url, None, r
        except httpx.HTTPError as e:
            log.info("Fetch failed %s: %s", url, e)
            return url, PageResult(url=url, status="failed"), None

    def _process(self, url: str, r: httpx.Response) -> PageResult:
        final_url = canonical(str(r.url))
        if host_key(final_url) != self.domain:
            return PageResult(url=url, status="failed")
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or final_url.lower().endswith(".pdf"):
            if not self.include_pdfs or r.status_code != 200:
                return PageResult(url=final_url, status="empty")
            try:
                text = pdf_text(r.content)
            except Exception:  # noqa: BLE001
                return PageResult(url=final_url, status="failed")
            title = urlparse(final_url).path.rsplit("/", 1)[-1]
            return PageResult(url=final_url, status="indexed" if text else "empty", title=title, text=text)
        if "html" not in ctype and ctype:
            return PageResult(url=final_url, status="empty")

        html = r.text
        text = extract_text(html, final_url)
        bad = classify(r.status_code, final_url, url, html, len(text))
        if bad:
            return PageResult(url=final_url, status=bad, html=html)
        rendered = False
        if len(text) < MIN_TEXT_CHARS:
            rendered_html = self.renderer.render(final_url)
            if rendered_html:
                rtext = extract_text(rendered_html, final_url)
                if len(rtext) > len(text):
                    html, text, rendered = rendered_html, rtext, True
        links = extract_links(html, final_url)
        if len(text) < 50:
            return PageResult(url=final_url, status="empty", links=links, html=html)
        return PageResult(url=final_url, status="indexed", title=extract_title(html), text=text, rendered=rendered, links=links, html=html)

    def run(self) -> None:
        try:
            base = f"{urlparse(self.start_url).scheme}://{urlparse(self.start_url).netloc}/"
            sitemaps = self._load_robots(base)
            frontier: deque[tuple[str, int]] = deque()

            def enqueue(u: str, depth: int, front: bool = False) -> None:
                u = canonical(u)
                key = dedup_key(u)
                if key in self.seen or not is_crawlable(u, self.domain) or not self._allowed(u):
                    return
                if not self.include_pdfs and urlparse(u).path.lower().endswith(".pdf"):
                    return  # don't spend the page budget downloading PDFs we won't read
                self.seen.add(key)
                (frontier.appendleft if front else frontier.append)((u, depth))

            enqueue(base, 0)
            enqueue(self.start_url, 0)
            for u in self._sitemap_urls(sitemaps):
                enqueue(u, 1)
            if not frontier:
                raise CrawlError("This site's robots.txt does not allow crawling.")

            processed = 0
            with ThreadPoolExecutor(max_workers=settings.crawl_concurrency) as pool:
                while frontier and processed < self.max_pages:
                    batch = [frontier.popleft() for _ in range(min(len(frontier), settings.crawl_concurrency, self.max_pages - processed))]
                    depths = dict(batch)
                    for url, early, resp in pool.map(lambda b: self._fetch(b[0]), batch):
                        result = early or self._process(url, resp)
                        if not self.homepage_html and result.html and depths[url] == 0:
                            self.homepage_html, self.homepage_url = result.html, result.url
                        if result.status == "indexed":
                            digest = hashlib.sha1(result.text.encode()).hexdigest()
                            if digest in self.content_hashes:
                                result.status = "empty"
                            self.content_hashes.add(digest)
                        processed += 1
                        if depths[url] < settings.max_depth:
                            for link in result.links:
                                enqueue(link, depths[url] + 1)
                        result.html = ""  # free memory
                        self.on_page(result)
                        self.on_progress(min(len(self.seen), self.max_pages), processed)
        finally:
            self.renderer.close()
            self.client.close()
