"""Read-only MPM page fetcher (Playwright + Microsoft Edge persistent profile for Windows SSO).

Only page.goto() and reads. Never click, fill, press or submit anything on MPM.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class LoginError(Exception):
    """SSO session invalid. The run must stop immediately (E-LOGIN) so the account is not locked."""


class PageError(Exception):
    """Page could not be loaded: timeout, not found, access denied (E-PAGE)."""


@dataclass(frozen=True)
class FetchResult:
    html: str
    html_path: str
    png_path: str


class Fetcher(Protocol):
    def fetch(self, doc_key: str, url: str, run_id: int) -> FetchResult: ...


class MpmScraper:
    """Use as a context manager: `with MpmScraper(cfg) as s: s.fetch(...)`."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.sel = cfg.selectors
        self.opts = cfg.settings["scraper"]
        self.snap_dir = cfg.path("snapshots")
        self._pw = self._ctx = self._page = None
        self._last_fetch = 0.0

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # imported lazily so tests need no browser

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.cfg.path("edge_profile")),
            channel=self.opts.get("browser_channel", "msedge"),
            headless=bool(self.opts.get("headless", False)),
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.set_default_timeout(int(self.opts.get("page_timeout_seconds", 45)) * 1000)
        return self

    def __exit__(self, *exc):
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()

    def _is_login_page(self, url: str) -> bool:
        return any(m.lower() in url.lower() for m in self.sel["login_markers"]["url_contains"])

    def fetch(self, doc_key: str, url: str, run_id: int) -> FetchResult:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import TimeoutError as PwTimeout

        wait = float(self.opts.get("delay_between_pages_seconds", 5)) - (time.monotonic() - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        self._last_fetch = time.monotonic()
        page = self._page
        try:
            resp = page.goto(url, wait_until="domcontentloaded")
        except PwTimeout as exc:
            raise PageError(f"Timeout membuka {url}") from exc
        except PwError as exc:
            raise PageError(f"Gagal membuka {url}: {exc}") from exc
        if self._is_login_page(page.url) or (resp is not None and resp.status in (401,)):
            raise LoginError("Sesi SSO ke MPM tidak valid")
        if resp is not None and resp.status >= 400:
            raise PageError(f"HTTP {resp.status} untuk {url}")
        try:
            page.wait_for_selector(self.sel["ready"])
        except PwTimeout as exc:
            if self._is_login_page(page.url):
                raise LoginError("Sesi SSO ke MPM tidak valid") from exc
            raise PageError(f"Tabel approval tidak muncul di {url}") from exc

        day = time.strftime("%Y%m%d")
        folder = self.snap_dir / day
        folder.mkdir(parents=True, exist_ok=True)
        base = folder / f"{doc_key}_run{run_id}"
        html = page.content()
        Path(f"{base}.html").write_text(html, encoding="utf-8")
        page.screenshot(path=f"{base}.png", full_page=True)
        return FetchResult(html=html, html_path=f"{base}.html", png_path=f"{base}.png")
