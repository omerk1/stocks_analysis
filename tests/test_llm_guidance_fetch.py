import json

import pytest

from src.llm.guidance import fetch

INDEX = b"""<html><body>
<table class="tableFile" summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>FORM 8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/000000000012000001/f8k.htm">f8k.htm</a></td><td>8-K</td><td>30000</td></tr>
<tr><td>2</td><td>SLIDES</td><td><a href="/Archives/edgar/data/1/000000000012000001/ex99-2.htm">ex99-2.htm</a></td><td>EX-99.2</td><td>9000</td></tr>
<tr><td>3</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1/000000000012000001/ex99-1.htm">ex99-1.htm</a></td><td>EX-99.1</td><td>50000</td></tr>
</table></body></html>"""
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000012000001/0000000000-12-000001-index.htm"


def test_index_documents_and_pick():
    docs = fetch.index_documents(INDEX, INDEX_URL)
    assert [d["type"] for d in docs] == ["8-K", "EX-99.2", "EX-99.1"]
    assert docs[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1/000000000012000001/f8k.htm"
    assert fetch.pick_release(docs)["type"] == "EX-99.1"
    assert fetch.pick_release(docs[:2])["type"] == "EX-99.2"
    assert fetch.pick_release([{"type": "EX-99", "url": "u"}])["type"] == "EX-99"
    assert fetch.pick_release([{"type": "EX-99.01", "url": "u"}, {"type": "EX-99.2", "url": "v"}])["url"] == "u"
    assert fetch.pick_release(docs[:1]) is None
    assert fetch.index_documents(b"<html></html>", INDEX_URL) == []


def test_release_text_keeps_table_rows_on_one_line():
    html = b"""<html><body><p>Company&nbsp;X reports results.</p><p></p><p>  </p>
    <table><tr><td>Outlook</td><td>Low</td><td>High</td></tr>
    <tr><td>EPS</td><td>$2.10</td><td></td><td>$2.20</td></tr></table>
    <script>var x = 1;</script><p>Forward-looking statements.</p></body></html>"""
    text = fetch.release_text(html)
    assert text.splitlines() == ["Company X reports results.", "", "Outlook | Low | High", "",
                                 "EPS | $2.10 | $2.20", "", "Forward-looking statements."]
    assert fetch.release_text(b"Plain   text\n\n\n\nexhibit") == "Plain text\n\nexhibit"


def test_release_text_keeps_inline_tags_in_their_sentence():
    html = b"""<!DOCTYPE html><html><body><!-- XBRL junk --><p>expects EPS of <b>$2.10</b> to <font size=2>$2.20</font>
    for 2015,<br>up from <span>$2.00</span>.</p><div>Next</div>
    <table><tr><td>$<b>1.2</b> billion</td></tr></table><pre>keep
  this</pre></body></html>"""
    assert fetch.release_text(html).splitlines() == [
        "expects EPS of $2.10 to $2.20 for 2015,", "up from $2.00.", "", "Next", "", "$1.2 billion", "",
        "keep", "this"]


def test_release_text_keeps_a_nested_table_s_rows_apart():
    html = b"""<html><body><table><tr><td><p>Outlook</p><table>
    <tr><td>EPS</td><td>$2.10</td></tr><tr><td>Revenue</td><td>$9.5 billion</td></tr></table></td></tr></table>
    </body></html>"""
    assert fetch.release_text(html).splitlines() == ["Outlook", "", "EPS | $2.10", "", "Revenue | $9.5 billion"]


def test_release_text_detects_windows_1252():
    html = "<html><body><p>EPS of $2.10–$2.20, Company X</p></body></html>".encode("cp1252")
    assert fetch.release_text(html) == "EPS of $2.10–$2.20, Company X"
    plain = "Range $2.10–$2.20".encode("cp1252")
    assert fetch.release_text(plain) == "Range $2.10–$2.20"


class FakeResponse:
    def __init__(self, status, content=b"ok"):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, statuses):
        self.headers, self.statuses, self.urls = {}, list(statuses), []

    def get(self, url, timeout):
        self.urls.append(url)
        return FakeResponse(self.statuses.pop(0))


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_edgar_needs_a_contact():
    with pytest.raises(ValueError):
        fetch.Edgar("", session=FakeSession([]))
    with pytest.raises(ValueError):
        fetch.Edgar("just a name", session=FakeSession([]))


def test_edgar_spaces_requests_and_retries_transient_errors():
    clock, session = Clock(), FakeSession([200, 200, 503, 403, 200, 404])
    edgar = fetch.Edgar("me me@example.com", session=session, sleep=clock.sleep, clock=clock.now)
    assert session.headers["User-Agent"] == "me me@example.com"
    edgar.get("a")
    edgar.get("b")  # back to back: waits out the interval
    assert clock.sleeps == [pytest.approx(fetch.MIN_INTERVAL)]
    edgar.get("c")  # 503, then 403 (SEC's rate limit), each paused, then 200
    assert session.urls == ["a", "b", "c", "c", "c"]
    with pytest.raises(RuntimeError):
        edgar.get("d")  # 404 is not retried
    assert session.urls[-1] == "d" and session.urls.count("d") == 1


def test_fetch_one_caches(tmp_path):
    class StubEdgar:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            return INDEX if url == INDEX_URL else b"<p>release</p>"

    edgar = StubEdgar()
    m = fetch.fetch_one(edgar, "0000000000-12-000001", INDEX_URL, tmp_path)
    assert m["release"]["type"] == "EX-99.1" and m["release_file"] == "ex99-1.htm"
    assert fetch.load_text("0000000000-12-000001", tmp_path) == "release"
    again = fetch.fetch_one(edgar, "0000000000-12-000001", INDEX_URL, tmp_path)
    assert len(edgar.urls) == 2 and again == m  # nothing refetched
    saved = json.loads((tmp_path / "0000000000-12-000001" / "manifest.json").read_text())
    assert saved["release_file"] == "ex99-1.htm"


def test_fetch_one_refuses_an_index_it_cannot_read(tmp_path):
    class ErrorPage:
        def get(self, url):
            return b"<html><body>Request Rate Threshold Exceeded</body></html>"

    with pytest.raises(ValueError, match="no document table"):
        fetch.fetch_one(ErrorPage(), "0000000000-12-000002", INDEX_URL, tmp_path)
    folder = tmp_path / "0000000000-12-000002"
    assert not (folder / "manifest.json").exists() and not (folder / "index.htm").exists()
