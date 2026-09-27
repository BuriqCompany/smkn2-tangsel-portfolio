#!/usr/bin/env python3
"""Fetch the three newest news cards from SMKN 2 Tangsel's official news page."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

SOURCE_URL = "https://smkn2tangsel.sch.id/news"
HOME_URL = "https://smkn2tangsel.sch.id/"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "news.json"
USER_AGENT = "SMKN2TangselPortfolioNewsBot/1.0 (+https://github.com/BuriqCompany/smkn2-tangsel-portfolio)"


def fetch_page(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not retrieve {url}")


class NewsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.depth = 0
        self.current: dict[str, str] | None = None
        self.meta_depth: int | None = None
        self.in_title = False
        self.in_meta = False
        self.in_description = False
        self.description_started = False

    @staticmethod
    def classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        values = dict(attrs)
        return set((values.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = self.classes(attrs)

        if self.current is None:
            if tag == "div" and "media-h" in classes:
                self.current = {"title": "", "url": "", "image": "", "date": "", "description": ""}
                self.depth = 1
                self.meta_depth = None
                self.in_title = self.in_meta = self.in_description = False
                self.description_started = False
            return

        if tag == "div":
            self.depth += 1
            if "meta" in classes:
                self.in_meta = True
                self.meta_depth = self.depth
        elif tag == "h2":
            self.in_title = True
        elif tag == "a" and self.in_title and not self.current["url"]:
            self.current["url"] = urljoin(SOURCE_URL, attr.get("href", ""))
        elif tag == "img" and not self.current["image"]:
            self.current["image"] = urljoin(SOURCE_URL, attr.get("src", ""))
        elif tag == "p" and not self.description_started:
            self.description_started = True
            self.in_description = True
        elif tag == "br":
            self._space_for_active_field()

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == "h2":
            self.in_title = False
        elif tag == "p" and self.in_description:
            self.in_description = False
        elif tag == "div":
            if self.meta_depth == self.depth:
                self.in_meta = False
                self.meta_depth = None
            self.depth -= 1
            if self.depth == 0:
                self._finish_card()

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        if self.in_title:
            self.current["title"] += data
        if self.in_meta:
            self.current["date"] += data
        if self.in_description:
            self.current["description"] += data

    def _space_for_active_field(self) -> None:
        if self.current is None:
            return
        if self.in_title:
            self.current["title"] += " "
        if self.in_meta:
            self.current["date"] += " "
        if self.in_description:
            self.current["description"] += " "

    def _finish_card(self) -> None:
        assert self.current is not None
        item = {key: re.sub(r"\s+", " ", value).strip() for key, value in self.current.items()}
        if item["title"] and item["url"]:
            if not item["image"]:
                item["image"] = "https://smkn2tangsel.sch.id/assets/images/logo/logosmk.png"
            self.items.append(item)
        self.current = None


class AnnouncementParser(HTMLParser):
    """Read the school's featured announcement block on the homepage."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_heading = False
        self.in_paragraph = False
        self.heading = ""
        self.heading_candidate = ""
        self.description = ""
        self.url = ""
        self.is_announcement = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "h2":
            self.in_heading = not self.is_announcement
            self.heading_candidate = ""
        elif tag == "p" and self.is_announcement and not self.description:
            self.in_paragraph = True
        elif tag == "a" and self.is_announcement and not self.url:
            self.url = urljoin(HOME_URL, attr.get("href", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            candidate = re.sub(r"\s+", " ", self.heading_candidate).strip()
            if not self.is_announcement and "PENGUMUMAN" in candidate.upper():
                self.heading = candidate
                self.is_announcement = True
            self.in_heading = False
        elif tag == "p":
            self.in_paragraph = False

    def handle_data(self, data: str) -> None:
        if self.in_heading:
            self.heading_candidate += data
        if self.in_paragraph:
            self.description += data

    def item(self) -> dict[str, str] | None:
        title = re.sub(r"\s+", " ", self.heading).strip()
        description = re.sub(r"\s+", " ", self.description).strip()
        if not (self.is_announcement and title and self.url):
            return None
        return {
            "title": title,
            "url": self.url,
            "image": "https://smkn2tangsel.sch.id/assets/images/logo/logosmk.png",
            "date": "Pengumuman resmi",
            "description": description,
            "category": "Pengumuman",
        }


def main() -> None:
    page = fetch_page(SOURCE_URL)
    parser = NewsParser()
    parser.feed(page)
    home_page = fetch_page(HOME_URL)
    announcement_parser = AnnouncementParser()
    announcement_parser.feed(home_page)
    announcement = announcement_parser.item()

    collected = ([announcement] if announcement else []) + parser.items
    seen: set[str] = set()
    items = []
    for item in collected:
        key = item["url"] or item["title"]
        if key in seen:
            continue
        seen.add(key)
        item.setdefault("category", "Berita sekolah")
        items.append(item)
        if len(items) == 3:
            break
    if not items:
        raise RuntimeError("No news or announcement cards were found; keeping the last published feed unchanged.")

    previous = None
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
    unchanged = previous and previous.get("items") == items
    payload = {
        "source": SOURCE_URL,
        "updatedAt": previous.get("updatedAt") if unchanged else datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(items)} news items to {OUTPUT}")
    for item in items:
        print(f"- {item['title']} ({item['url']})")


if __name__ == "__main__":
    main()
