"""Domain verification: the owner proves they control the bot's website, so their request is approved without waiting.

Two ways, like Google Search Console:
  meta tag  <meta name="sitebot-verification" content="TOKEN"> on the website's home page
  DNS TXT   a TXT record "sitebot-verification=TOKEN" on the domain (looked up over DNS-over-HTTPS)
"""

import re
import secrets

import httpx

META_NAME = "sitebot-verification"
MAX_HTML = 1_000_000


def new_token() -> str:
    return secrets.token_urlsafe(24)


def meta_tag(token: str) -> str:
    return f'<meta name="{META_NAME}" content="{token}">'


def dns_value(token: str) -> str:
    return f"{META_NAME}={token}"


def _has_meta(html: str, token: str) -> bool:
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        if re.search(rf"""name\s*=\s*["']?{META_NAME}["']?""", tag, flags=re.I) and re.search(
            rf"""(?i:content)\s*=\s*["']?{re.escape(token)}["'\s/>]""", tag + ">"
        ):
            return True
    return False


def check_meta(domain: str, token: str, http=httpx) -> tuple[bool, str]:
    """Looks for the meta tag on https://<domain>/ and https://www.<domain>/."""
    errors = []
    for url in (f"https://{domain}/", f"https://www.{domain}/"):
        try:
            with http.stream("GET", url, timeout=10, follow_redirects=True, headers={"User-Agent": "SiteBot-Verification/1.0"}) as r:
                if r.status_code != 200:
                    errors.append(f"{url} answered {r.status_code}")
                    continue
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_HTML:
                        break
        except httpx.HTTPError as e:
            errors.append(f"couldn't open {url} ({type(e).__name__})")
            continue
        if _has_meta(body.decode("utf-8", errors="replace"), token):
            return True, ""
        errors.append(f"no matching tag on {url}")
    return False, "; ".join(errors)


def check_dns(domain: str, token: str, http=httpx) -> tuple[bool, str]:
    """Looks for the TXT record using Google's and Cloudflare's DNS-over-HTTPS (no DNS library needed)."""
    want = dns_value(token)
    for resolver in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        try:
            r = http.get(resolver, params={"name": domain, "type": "TXT"}, headers={"Accept": "application/dns-json"}, timeout=10)
            answers = r.json().get("Answer") or []
        except (httpx.HTTPError, ValueError):
            continue
        for a in answers:
            if want in str(a.get("data", "")).replace('" "', "").strip('"'):
                return True, ""
        return False, f"no TXT record {want} found on {domain} yet (DNS changes can take a while)"
    return False, "couldn't reach a DNS resolver; try again in a moment"
