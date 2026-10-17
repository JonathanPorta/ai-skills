#!/usr/bin/env python3
"""Bounded page crawler for recon.

Fetches HTML pages breadth-first, one request at a time, and enforces every
limit *before* the request is made: the page cap, the depth cap, the host and
path boundary, robots.txt, and the target of every redirect. Pages are saved
under DEST/<host>/ so the pack can be served locally.

Same-host page requisites (images, stylesheets, scripts, icons) are fetched by
default and may live anywhere on the host; they are never parsed for further
links. Off-host assets are left to the rest of the recon workflow.

Prints one tab-separated line per decision:
    page   <status>  <url>  <saved-path>
    asset  <status>  <url>  <saved-path>
    skip   <reason>  <url>

Exit codes: 0 crawl ran, 2 bad arguments or start URL outside the boundary,
3 start URL refused (login wall, robots.txt, or fetch failure).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import html.parser
import pathlib
import posixpath
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SKIP_EXTENSIONS = {".mp4", ".webm", ".mov", ".zip", ".dmg", ".exe", ".map"}
ASSET_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "mask-icon"}


class OutOfBoundary(Exception):
    """A redirect pointed outside the boundary; the target was not requested."""

    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.target = target


class Boundary:
    def __init__(self, start: str, prefix: str | None, include: list[str], exclude: list[str]) -> None:
        parts = urllib.parse.urlsplit(start)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError(f"not an http(s) URL: {start}")
        self.host = netloc_of(parts)
        self.prefix = normalize_prefix(parts.path if prefix is None else prefix)
        self.include = [re.compile(pattern) for pattern in include]
        self.exclude = [re.compile(pattern) for pattern in exclude]

    def same_host(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        return parts.scheme in {"http", "https"} and netloc_of(parts) == self.host

    def allows_page(self, url: str) -> bool:
        if not self.same_host(url) or any(p.search(url) for p in self.exclude):
            return False
        path = urllib.parse.urlsplit(url).path or "/"
        if self.prefix == "/" or path == self.prefix or path.startswith(self.prefix + "/"):
            return True
        return any(p.search(url) for p in self.include)

    def allows_asset(self, url: str) -> bool:
        return self.same_host(url) and not any(p.search(url) for p in self.exclude)


def netloc_of(parts: urllib.parse.SplitResult) -> str:
    host = (parts.hostname or "").lower()
    default = {"http": 80, "https": 443}.get(parts.scheme)
    return host if parts.port in (None, default) else f"{host}:{parts.port}"


def normalize_prefix(path: str) -> str:
    path = posixpath.normpath(path or "/")
    return "/" if path in {".", "/"} else path.rstrip("/")


def canonical(url: str) -> str:
    return urllib.parse.urldefrag(url)[0]


def skipped_by_extension(url: str) -> bool:
    return posixpath.splitext(urllib.parse.urlsplit(url).path)[1].lower() in SKIP_EXTENSIONS


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[str] = []
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        if tag == "a" and values.get("href"):
            self.pages.append(values["href"])
        elif tag in {"img", "source"}:
            if values.get("src"):
                self.assets.append(values["src"])
            for candidate in values.get("srcset", "").split(","):
                if candidate.strip():
                    self.assets.append(candidate.strip().split()[0])
        elif tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        elif tag == "link" and values.get("href"):
            if ASSET_RELS & set(values.get("rel", "").lower().split()):
                self.assets.append(values["href"])


class GuardedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed) -> None:
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not self.allowed(target):
            raise OutOfBoundary(target)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def save_path(root: pathlib.Path, url: str, is_html: bool) -> pathlib.Path:
    parts = urllib.parse.urlsplit(url)
    segments = [s for s in urllib.parse.unquote(parts.path).split("/") if s not in {"", ".", ".."}]
    if is_html and (not segments or "." not in segments[-1]):
        segments.append("index.html")
    elif not segments:
        segments.append("index")
    name = segments[-1]
    if parts.query:
        stem, ext = posixpath.splitext(name)
        name = f"{stem}__{hashlib.sha1(parts.query.encode()).hexdigest()[:10]}{ext}"
    segments[-1] = name
    target = root.joinpath(*segments)
    if root.resolve() not in target.resolve().parents:
        raise ValueError(f"refusing to write outside {root}: {url}")
    return target


class Crawler:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.boundary = Boundary(args.url, args.prefix, args.include, args.exclude)
        self.root = pathlib.Path(args.dest) / self.boundary.host.replace(":", "_")
        self.robots: urllib.robotparser.RobotFileParser | None = None
        self.page_requests = 0
        self.asset_requests = 0

    def opener(self, allowed):
        return urllib.request.build_opener(GuardedRedirects(allowed))

    def emit(self, *fields: str) -> None:
        print("\t".join(fields), flush=True)

    def load_robots(self) -> None:
        if self.args.ignore_robots:
            return
        parts = urllib.parse.urlsplit(self.args.url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = urllib.robotparser.RobotFileParser(robots_url)
        try:
            request = urllib.request.Request(robots_url, headers={"User-Agent": self.args.user_agent})
            with self.opener(self.boundary.same_host).open(request, timeout=self.args.timeout) as response:
                parser.parse(response.read().decode("utf-8", "replace").splitlines())
        except (urllib.error.URLError, OutOfBoundary, OSError, ValueError):
            parser.parse([])  # unreachable robots.txt: nothing is disallowed
        self.robots = parser

    def robots_allow(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(self.args.user_agent, url)

    def fetch(self, url: str, allowed):
        request = urllib.request.Request(url, headers={"User-Agent": self.args.user_agent})
        with self.opener(allowed).open(request, timeout=self.args.timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status, response.geturl(), content_type, response.read()

    def run(self) -> int:
        start = canonical(self.args.url)
        if not self.boundary.allows_page(start):
            self.emit("skip", "start-outside-boundary", start)
            return 2
        self.load_robots()
        queue = collections.deque([(start, 0)])
        seen_pages = {start}
        seen_assets: set[str] = set()
        assets: list[str] = []
        while queue and self.page_requests < self.args.max_pages:
            url, depth = queue.popleft()
            if skipped_by_extension(url):
                self.emit("skip", "media-or-archive", url)
                continue
            if not self.robots_allow(url):
                self.emit("skip", "robots", url)
                if url == start:
                    return 3
                continue
            self.page_requests += 1
            try:
                status, final_url, content_type, body = self.fetch(url, self.boundary.allows_page)
            except OutOfBoundary as error:
                self.emit("skip", "redirect-outside-boundary", f"{url} -> {error.target}")
                if url == start:
                    return 3
                continue
            except urllib.error.HTTPError as error:
                self.emit("page", str(error.code), url, "-")
                if url == start:
                    return 3
                continue
            except (urllib.error.URLError, OSError) as error:
                self.emit("skip", f"fetch-failed:{error}", url)
                if url == start:
                    return 3
                continue
            is_html = "html" in content_type.lower()
            target = save_path(self.root, final_url, is_html)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self.emit("page", str(status), final_url, str(target))
            if not is_html:
                continue
            parser = LinkParser()
            parser.feed(body.decode("utf-8", "replace"))
            for href in parser.pages:
                link = canonical(urllib.parse.urljoin(final_url, href))
                if link in seen_pages:
                    continue
                seen_pages.add(link)
                if not self.boundary.allows_page(link):
                    if self.boundary.same_host(link):
                        self.emit("skip", "outside-boundary", link)
                    continue
                if depth + 1 > self.args.depth:
                    self.emit("skip", "depth", link)
                    continue
                queue.append((link, depth + 1))
            for src in parser.assets:
                asset = canonical(urllib.parse.urljoin(final_url, src))
                if asset not in seen_assets and self.boundary.allows_asset(asset):
                    seen_assets.add(asset)
                    assets.append(asset)
        for url, _depth in queue:
            self.emit("skip", "page-cap", url)
        if not self.args.no_assets:
            self.fetch_assets(assets)
        return 0

    def fetch_assets(self, assets: list[str]) -> None:
        for url in assets:
            if self.asset_requests >= self.args.max_assets:
                self.emit("skip", "asset-cap", url)
                continue
            if skipped_by_extension(url) or not self.robots_allow(url):
                self.emit("skip", "asset-not-allowed", url)
                continue
            self.asset_requests += 1
            try:
                status, final_url, _content_type, body = self.fetch(url, self.boundary.allows_asset)
            except (OutOfBoundary, urllib.error.URLError, OSError) as error:
                self.emit("skip", f"asset-failed:{error}", url)
                continue
            target = save_path(self.root, final_url, is_html=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self.emit("asset", str(status), final_url, str(target))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded page crawler for recon.")
    parser.add_argument("url", help="start URL; its path is the default boundary prefix")
    parser.add_argument("--dest", required=True, help="pack directory; pages go to DEST/<host>/")
    parser.add_argument("--max-pages", type=int, default=50, help="maximum page requests (default 50)")
    parser.add_argument("--depth", type=int, default=3, help="maximum link depth from the start URL (default 3)")
    parser.add_argument("--prefix", help="path boundary; default is the start URL's path, '/' for the whole host")
    parser.add_argument("--include", action="append", default=[], help="regex for extra page URLs to allow")
    parser.add_argument("--exclude", action="append", default=[], help="regex for page or asset URLs to refuse")
    parser.add_argument("--ignore-robots", action="store_true", help="do not consult robots.txt")
    parser.add_argument("--no-assets", action="store_true", help="fetch pages only")
    parser.add_argument("--max-assets", type=int, default=500, help="maximum same-host asset requests (default 500)")
    parser.add_argument("--timeout", type=float, default=30, help="per-request timeout in seconds (default 30)")
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    args = parser.parse_args(argv)
    if args.max_pages < 1 or args.depth < 0 or args.max_assets < 0:
        parser.error("--max-pages must be at least 1; --depth and --max-assets cannot be negative")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        crawler = Crawler(args)
    except (ValueError, re.error) as error:
        print(f"crawl.py: {error}", file=sys.stderr)
        return 2
    return crawler.run()


if __name__ == "__main__":
    sys.exit(main())
