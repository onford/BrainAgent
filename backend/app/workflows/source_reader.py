"""Read public source pages/PDFs as inert text with bounded, saved provenance."""

import asyncio
import base64
import hashlib
import ipaddress
import socket
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from .cognition_contracts import SourceDocument


def abstract_only(document):
    location = urlsplit(document.url)
    return (
        "[Abstract]" in document.text
        or location.hostname == "pubmed.ncbi.nlm.nih.gov"
        or (
            location.hostname in {"arxiv.org", "www.arxiv.org"}
            and location.path.startswith("/abs/")
        )
    )


class PageText(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.parts, self.links = base, [], []
        self.hidden = 0
        self.title, self.in_title = "", False
        self.article_title, self.in_article_title = "", False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag == "article-title" and not self.article_title:
            self.in_article_title = True
        if tag in {"a", "ext-link"}:
            attributes = dict(attrs)
            href = attributes.get("href") or attributes.get("xlink:href", "")
            url = urljoin(self.base, href)
            if urlsplit(url).scheme in {"http", "https"}:
                self.links.append(url)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if tag == "article-title":
            self.in_article_title = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())
        if self.in_title:
            self.title += data
        if self.in_article_title:
            self.article_title += data


async def public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
    ):
        raise ValueError("source must be a public HTTP(S) URL without credentials")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or 443
    )
    if not addresses or any(
        not ipaddress.ip_address(a[4][0]).is_global for a in addresses
    ):
        raise ValueError("private/local network sources are not supported")


class SourceReader:
    async def read(self, url, kind):
        # Article pages are JS shells; the public article API contains real text.
        parsed = urlsplit(url)
        repository = re.fullmatch(r"/([\w.-]+)/([\w.-]+)", parsed.path.rstrip("/"))
        if parsed.hostname == "github.com" and repository:
            owner, name = repository.groups()
            url = f"https://api.github.com/repos/{owner}/{name}/readme"
        file_path = re.fullmatch(r"/([\w.-]+)/([\w.-]+)/blob/([^/]+)/(.+)", parsed.path)
        if parsed.hostname == "github.com" and file_path:
            owner, name, ref, path = file_path.groups()
            url = (
                f"https://api.github.com/repos/{owner}/{name}/contents/{path}?"
                + urlencode({"ref": ref})
            )
        article = re.fullmatch(
            r"/article/(MED|PMC)/([A-Za-z0-9]+)", parsed.path.rstrip("/")
        )
        if parsed.hostname == "europepmc.org" and article:
            source, identity = article.groups()
            query = (
                f"EXT_ID:{identity} AND SRC:MED"
                if source == "MED"
                else f"PMCID:{identity}"
            )
            url = (
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
                + urlencode({"query": query, "format": "json", "resultType": "core"})
            )
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "BrainAgent/0.2 research"},
        ) as client:
            for _ in range(6):
                await public_url(url)
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 12 * 1024 * 1024:
                            raise ValueError("source exceeds 12 MB reading limit")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    mime = response.headers.get("content-type", "")
                    break
            else:
                raise ValueError("too many source redirects")
        links, title = [], url
        if body.startswith(b"%PDF"):
            from pypdf import PdfReader

            def extract():
                reader = PdfReader(BytesIO(body))
                return "\n".join(
                    f"[Page {i + 1}]\n{page.extract_text()}"
                    for i, page in enumerate(reader.pages[:80])
                ), len(reader.pages) > 80

            text, truncated = await asyncio.to_thread(extract)
        elif "json" in mime and urlsplit(url).hostname == "api.github.com":
            document = json.loads(body)
            if document.get("encoding") != "base64" or not document.get("content"):
                raise ValueError(
                    "GitHub response has no readable file content; read a README or file URL"
                )
            text = base64.b64decode(document["content"]).decode(
                "utf-8", errors="replace"
            )
            title = f"{urlsplit(url).path.removeprefix('/repos/').split('/readme')[0]} — {document.get('name', 'repository file')}"
            base = document.get("html_url") or url
            links = [base]
            for href in re.findall(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
                target = urljoin(base, href)
                if urlsplit(target).scheme in {"http", "https"}:
                    links.append(target)
            links.extend(re.findall(r"https?://[^\s<>\[\]()]+", text))
            parser = PageText(base)
            parser.feed(text)
            links = list(dict.fromkeys(links + parser.links))[:150]
            truncated = False
        elif "json" in mime and urlsplit(url).hostname == "www.ebi.ac.uk":
            results = json.loads(body).get("resultList", {}).get("result", [])
            if not results or not results[0].get("abstractText"):
                raise ValueError(
                    "paper metadata has no readable abstract; follow an open full-text source"
                )
            article = results[0]
            parser = PageText(url)
            parser.feed(article["abstractText"])
            title = article.get("title", url)
            text = title + "\n[Abstract]\n" + "\n".join(parser.parts)
            if article.get("pmcid") and article.get("isOpenAccess") == "Y":
                links.append(
                    f"https://www.ebi.ac.uk/europepmc/webservices/rest/{article['pmcid']}/fullTextXML"
                )
            truncated = False
        else:
            text = body.decode("utf-8", errors="replace")
            if kind == "paper" and "json" in mime:
                raise ValueError(
                    "paper metadata JSON is not article text; follow an abstract or full-text URL"
                )
            if "html" in mime or "xml" in mime or "<html" in text[:1000].lower():
                parser = PageText(url)
                parser.feed(text)
                text, links, title = (
                    "\n".join(parser.parts),
                    list(dict.fromkeys(parser.links))[:150],
                    parser.article_title or parser.title or url,
                )
            truncated = False
        location = urlsplit(url)
        if location.hostname == "pubmed.ncbi.nlm.nih.gov" or (
            location.hostname in {"arxiv.org", "www.arxiv.org"}
            and location.path.startswith("/abs/")
        ):
            text = "[Abstract]\n" + text
        if len(text.strip()) < 100:
            raise ValueError("source has insufficient readable text")
        if any(
            marker in title.lower()
            for marker in ("just a moment", "access denied", "captcha")
        ):
            raise ValueError(
                "source returned an access challenge instead of article text"
            )
        return SourceDocument(
            id="s-" + hashlib.sha256(url.encode()).hexdigest()[:16],
            url=url,
            title=title,
            kind=kind,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            sha256=hashlib.sha256(body).hexdigest(),
            text=text[:80000],
            links=links,
            truncated=truncated or len(text) > 80000,
        )
