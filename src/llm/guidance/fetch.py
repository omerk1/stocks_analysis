"""Fetch the sample's press releases from EDGAR and turn them into plain text.

For each accession in the sample, two requests: the filing index
(`...-index.htm`), which lists every document with its type, then the press
release, the exhibit typed EX-99.1 (else the first EX-99.x). Both are cached raw
under `data/raw/sec/press_releases/<accession>/` with a `manifest.json` saying
which document was taken, so a rerun fetches nothing it already has.

EDGAR's fair-access rules: a User-Agent naming who is asking, with a contact
(read from `SEC_USER_AGENT`; the fetcher refuses to run without it), and at most
10 requests a second (here at most one per `MIN_INTERVAL`, ~6/s). A 429 or 5xx is
retried after a pause; anything else fails loudly.

    SEC_USER_AGENT="name email" python -m src.llm.guidance.fetch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from bs4.element import PreformattedString

from src.foundation.utils.config_loader import load_config
from src.llm.guidance.sample import SAMPLE_PATH

MIN_INTERVAL = 0.15  # seconds between requests: ~6.7/s, under EDGAR's 10/s
RETRIES = 4
TIMEOUT = 30
EXHIBIT = re.compile(r"^EX-99(\.\d+)?$", re.IGNORECASE)
PRIMARY = re.compile(r"^EX-99\.0*1$", re.IGNORECASE)
BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "center",
              "blockquote", "pre", "hr", "title"]


def cache_root() -> Path:
    return Path(load_config().data_paths.raw) / "sec" / "press_releases"


class Edgar:
    """A polite EDGAR session: User-Agent set, requests spaced, transient errors retried."""

    def __init__(self, user_agent: str, session: requests.Session | None = None, sleep=time.sleep,
                 clock=time.monotonic):
        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError("SEC_USER_AGENT must name the requester with a contact email")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._sleep, self._clock, self._last = sleep, clock, None

    def get(self, url: str) -> bytes:
        for attempt in range(RETRIES):
            if self._last is not None:
                wait = MIN_INTERVAL - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            try:
                r = self.session.get(url, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout):
                r = None
            if r is None or r.status_code == 429 or r.status_code >= 500:
                if attempt < RETRIES - 1:
                    self._sleep(2.0 * 2 ** attempt)
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"{url}: still failing after {RETRIES} tries")


def index_documents(index_html: bytes, index_url: str) -> list[dict]:
    """The filing index's document table: one dict per document (type, description, url)."""
    soup = BeautifulSoup(index_html, "html.parser")
    table = soup.find("table", class_="tableFile")
    if table is None:
        return []
    docs = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if len(cells) < 4 or link is None:
            continue
        href = link["href"]
        if href.startswith("/ix?doc="):  # inline-XBRL viewer link -> the document itself
            href = href[len("/ix?doc="):]
        docs.append({"type": cells[3].get_text(strip=True), "description": cells[1].get_text(" ", strip=True),
                     "url": requests.compat.urljoin(index_url, href)})
    return docs


def pick_release(docs: list[dict]) -> dict | None:
    """EX-99.1, else the first EX-99.x, else None."""
    exhibits = [d for d in docs if EXHIBIT.match(d["type"])]
    primary = [d for d in exhibits if PRIMARY.match(d["type"])]
    return (primary or exhibits or [None])[0]


def fetch_one(edgar: Edgar, accession: str, index_url: str, root: Path) -> dict:
    """The manifest for one release, fetching whatever isn't cached yet."""
    folder = root / accession
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    folder.mkdir(parents=True, exist_ok=True)
    index_path = folder / "index.htm"
    if not index_path.exists():
        index_path.write_bytes(edgar.get(index_url))
    docs = index_documents(index_path.read_bytes(), index_url)
    chosen = pick_release(docs)
    manifest = {"accession": accession, "index_url": index_url, "documents": docs, "release": chosen,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if chosen is not None:
        name = Path(chosen["url"]).name
        (folder / name).write_bytes(edgar.get(chosen["url"]))
        manifest["release_file"] = name
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return manifest


def release_text(raw: bytes) -> str:
    """Plain text of a release (HTML or plain-text exhibit). Table rows become one line
    each, cells joined by ' | ', so a guidance table stays readable. Only block-level
    tags break a line: inline ones (<b>, <font>, <span>) wrapping a figure stay inside
    their sentence. The encoding is checked (older exhibits are often windows-1252,
    whose en dash marks a range): UTF-8 if it decodes, else windows-1252."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    if re.search(r"<(html|body|p|div|table)\b", text, re.IGNORECASE):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for node in soup.find_all(string=lambda s: isinstance(s, PreformattedString)):
            node.extract()  # comments, doctype, CDATA: not text of the release
        for s in soup.find_all(string=True):  # source line wraps are not line breaks (except in <pre>)
            if s.find_parent("pre") is None:
                s.replace_with(re.sub(r"\s+", " ", s))
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(BLOCK_TAGS):
            tag.insert_before("\n")
            tag.insert_after("\n")
        for tr in soup.find_all("tr"):
            cells = [re.sub(r"\s+", " ", c.get_text("")).strip() for c in tr.find_all(["td", "th"])]
            tr.replace_with("\n" + " | ".join(c for c in cells if c) + "\n")
        text = soup.get_text("")
    lines = (re.sub(r"[ \t ​]+", " ", line).strip() for line in text.splitlines())
    out, blank = [], False
    for line in lines:
        if not line or re.fullmatch(r"[|\s]*", line):
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def load_text(accession: str, root: Path | None = None) -> str | None:
    """The cached release's text, or None if it has no press-release exhibit."""
    folder = (root or cache_root()) / accession
    manifest = json.loads((folder / "manifest.json").read_text())
    if "release_file" not in manifest:
        return None
    return release_text((folder / manifest["release_file"]).read_bytes())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.fetch")
    parser.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    args = parser.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv()
    edgar = Edgar(os.environ.get("SEC_USER_AGENT", ""))
    root = cache_root()
    sample = pd.read_csv(args.sample, dtype={"accession": str})
    for row in sample.itertuples():
        m = fetch_one(edgar, row.accession, row.index_url, root)
        took = m["release"]["type"] if m["release"] else "NO EX-99"
        print(f"{row.slot:>2} {row.ticker:<6} {row.accession}  {took}")


if __name__ == "__main__":
    main()
