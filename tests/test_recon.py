"""Behavioural tests for the recon skill's safety boundaries.

Each case reproduces a review finding against the first published version: a
page cap that only limited bytes, a path lock that let `/menu` reach `/other`,
a `make stop` that killed whatever held the port, and a hosts cleanup that
deleted every line naming the host. They run the real crawler and the real
templates against local fixtures.
"""

from __future__ import annotations

import contextlib
import http.server
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import posixpath
import tempfile
import threading
import time
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "recon"
CRAWL = SKILL / "scripts" / "crawl.py"
MAKEFILE_TEMPLATE = SKILL / "assets" / "templates" / "Makefile"
HOSTS_TEMPLATE = SKILL / "assets" / "templates" / "hosts.sh"


def page(*links: str) -> str:
    anchors = "".join(f'<a href="{link}">{link}</a>' for link in links)
    return f"<html><head><title>t</title></head><body>{anchors}</body></html>"


@contextlib.contextmanager
def site(pages: dict[str, str], redirects: dict[str, str] | None = None,
         statuses: dict[str, int | str] | None = None):
    """Serve `pages` (path -> HTML) and record every path requested.

    `statuses` maps a path to an HTTP status to return instead, or to "drop"
    to close the connection without a response.
    """
    requested: list[str] = []
    redirects = redirects or {}
    statuses = statuses or {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            requested.append(self.path)
            if statuses.get(self.path) == "drop":
                self.close_connection = True
                return
            if self.path in statuses:
                self.send_response(int(statuses[self.path]))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path in redirects:
                self.send_response(302)
                self.send_header("Location", redirects[self.path])
                self.end_headers()
                return
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = body.encode()
            kind = "text/plain" if self.path == "/robots.txt" else "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requested
    finally:
        server.shutdown()
        server.server_close()


def crawl(url: str, dest: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CRAWL), url, "--dest", str(dest), *args],
        capture_output=True, text=True, timeout=60,
    )


def page_requests(requested: list[str]) -> list[str]:
    return [path for path in requested if path != "/robots.txt"]


def effective_path(raw: str) -> str:
    """How a lenient server would route `raw`: fully decoded, dot segments resolved."""
    previous = None
    while previous != raw:
        previous, raw = raw, urllib.parse.unquote(raw)
    return posixpath.normpath(raw)


def ps_can_report_start_times() -> bool:
    result = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"nothing listening on {port}")


class CrawlBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dest = Path(tempfile.mkdtemp(prefix="recon-test-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)

    def test_page_cap_limits_requests_not_bytes(self) -> None:
        pages = {
            "/": page("/a", "/b", "/c"),
            "/a": page("/", "/b"),
            "/b": page("/c"),
            "/c": page("/a"),
        }
        with site(pages) as (base, requested):
            result = crawl(base + "/", self.dest, "--max-pages", "1", "--no-assets")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(page_requests(requested), ["/"])
        self.assertEqual(len(list(self.dest.rglob("*.html"))), 1)

    def test_path_prefix_never_requests_sibling_paths(self) -> None:
        pages = {
            "/menu": page("/menu/lunch", "/other", "/menu-old"),
            "/menu/lunch": page("/other/deep", "/menu"),
            "/other": page(),
            "/menu-old": page(),
        }
        with site(pages) as (base, requested):
            result = crawl(base + "/menu", self.dest, "--no-assets")
        self.assertEqual(result.returncode, 0, result.stderr)
        fetched = page_requests(requested)
        self.assertIn("/menu/lunch", fetched)
        self.assertFalse([p for p in fetched if not (p == "/menu" or p.startswith("/menu/"))], fetched)

    def test_encoded_dot_segments_cannot_escape_the_path_lock(self) -> None:
        escapes = [
            "/menu/%2e%2e/other",
            "/menu/%2E%2E/other",
            "/menu/..%2fother",
            "/menu/%2e%2e%2fother",
            "/menu/%252e%252e/other",
            "/menu/./../other",
        ]
        pages = {"/menu": page(*escapes, "/menu/ok"), "/menu/ok": page()}
        with site(pages) as (base, requested):
            result = crawl(base + "/menu", self.dest, "--no-assets")
        self.assertEqual(result.returncode, 0, result.stderr)
        fetched = page_requests(requested)
        self.assertIn("/menu/ok", fetched)
        outside = [p for p in fetched if not (effective_path(p) == "/menu" or effective_path(p).startswith("/menu/"))]
        self.assertEqual(outside, [], fetched)

    def test_unreadable_robots_policy_fails_closed(self) -> None:
        pages = {"/": page("/private"), "/private": page()}
        for status in (401, 403, 500, 503, "drop"):
            with self.subTest(robots=status):
                with site(pages, statuses={"/robots.txt": status}) as (base, requested):
                    result = crawl(base + "/", self.dest, "--no-assets")
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assertEqual(page_requests(requested), [])
                self.assertIn("--ignore-robots", result.stderr)

    def test_missing_robots_file_allows_the_crawl(self) -> None:
        pages = {"/": page("/a"), "/a": page()}
        for status in (404, 410):
            with self.subTest(robots=status):
                with site(pages, statuses={"/robots.txt": status}) as (base, requested):
                    result = crawl(base + "/", self.dest, "--no-assets")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(page_requests(requested), ["/", "/a"])

    def test_ignore_robots_is_the_explicit_override(self) -> None:
        with site({"/": page()}, statuses={"/robots.txt": 403}) as (base, requested):
            result = crawl(base + "/", self.dest, "--no-assets", "--ignore-robots")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(requested, ["/"])

    def test_include_widens_the_boundary_explicitly(self) -> None:
        pages = {"/menu": page("/other"), "/other": page()}
        with site(pages) as (base, requested):
            crawl(base + "/menu", self.dest, "--no-assets", "--include", r"/other$")
        self.assertIn("/other", page_requests(requested))

    def test_redirect_out_of_boundary_is_not_followed(self) -> None:
        pages = {"/menu": page("/menu/jump"), "/other": page()}
        with site(pages, redirects={"/menu/jump": "/other"}) as (base, requested):
            result = crawl(base + "/menu", self.dest, "--no-assets")
        self.assertNotIn("/other", page_requests(requested))
        self.assertIn("redirect-outside-boundary", result.stdout)

    def test_robots_disallow_is_respected_unless_ignored(self) -> None:
        pages = {
            "/robots.txt": "User-agent: *\nDisallow: /private\n",
            "/": page("/private", "/public"),
            "/private": page(),
            "/public": page(),
        }
        with site(pages) as (base, requested):
            crawl(base + "/", self.dest, "--no-assets")
        self.assertNotIn("/private", requested)
        self.assertIn("/public", requested)

    def test_depth_cap_is_enforced(self) -> None:
        pages = {"/": page("/1"), "/1": page("/2"), "/2": page("/3"), "/3": page()}
        with site(pages) as (base, requested):
            crawl(base + "/", self.dest, "--no-assets", "--depth", "1")
        self.assertEqual(page_requests(requested), ["/", "/1"])

    def test_off_host_links_are_never_requested(self) -> None:
        with site({"/": page("http://127.0.0.2:9/elsewhere")}) as (base, requested):
            result = crawl(base + "/", self.dest, "--no-assets")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(page_requests(requested), ["/"])


@unittest.skipUnless(shutil.which("make"), "make is required")
class MakefileStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path(tempfile.mkdtemp(prefix="recon-pack-"))
        self.addCleanup(shutil.rmtree, self.pack, ignore_errors=True)
        (self.pack / "example.com").mkdir()
        (self.pack / "example.com" / "index.html").write_text(page(), encoding="utf-8")
        text = MAKEFILE_TEMPLATE.read_text(encoding="utf-8").replace("__ROOT__", "example.com")
        (self.pack / "Makefile").write_text(text, encoding="utf-8")

    def start(self, *command: str, cwd: Path) -> subprocess.Popen:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        return process

    def make(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["make", "-s", *args], cwd=self.pack, capture_output=True, text=True, timeout=30)

    def test_help_lists_targets(self) -> None:
        result = self.make("help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in ("dev", "open", "stop", "docker"):
            self.assertIn(target, result.stdout)

    def test_stop_leaves_an_unrelated_listener_alone(self) -> None:
        port = free_port()
        unrelated = self.start(sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               cwd=self.pack)
        wait_for_port(port)
        result = self.make("stop", f"PORT={port}")
        self.assertEqual(result.returncode, 0, result.stderr)
        time.sleep(0.3)
        self.assertIsNone(unrelated.poll(), "make stop killed a server it did not start")

    def test_stale_pid_of_an_identical_server_is_not_trusted(self) -> None:
        port = free_port()
        same_command = self.start(
            sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
            "--directory", str(self.pack / "example.com"), cwd=self.pack,
        )
        wait_for_port(port)
        (self.pack / ".recon-dev.pid").write_text(
            f"{same_command.pid} {port} Mon Jan 1 00:00:00 2001\n", encoding="utf-8")
        result = self.make("stop", f"PORT={port}")
        self.assertEqual(result.returncode, 0, result.stderr)
        time.sleep(0.3)
        self.assertIsNone(same_command.poll(), "make stop trusted a recycled PID")

    @unittest.skipUnless(ps_can_report_start_times(), "ps cannot report process start times here")
    def test_stop_stops_the_dev_server_it_started(self) -> None:
        port = free_port()
        dev = self.start("make", "-s", "dev", f"PORT={port}", cwd=self.pack)
        wait_for_port(port)
        unrelated_port = free_port()
        unrelated = self.start(sys.executable, "-m", "http.server", str(unrelated_port),
                               "--bind", "127.0.0.1", cwd=self.pack)
        wait_for_port(unrelated_port)
        result = self.make("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stopped", result.stdout)
        dev.wait(timeout=10)
        self.assertIsNone(unrelated.poll(), "make stop also killed an unrelated server")
        self.assertFalse((self.pack / ".recon-dev.pid").exists())

    def test_stale_pid_file_is_not_trusted(self) -> None:
        sleeper = self.start("sleep", "30", cwd=self.pack)
        (self.pack / ".recon-dev.pid").write_text(f"{sleeper.pid} 8765\n", encoding="utf-8")
        result = self.make("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(sleeper.poll(), "make stop killed a PID that is not its server")


class HostsScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="recon-hosts-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        script = HOSTS_TEMPLATE.read_text(encoding="utf-8")
        script = script.replace("__HOST__", "example.com").replace("__TAG__", "example.com-2026-10-17")
        self.script = self.work / "hosts.sh"
        self.script.write_text(script, encoding="utf-8")
        self.hosts = self.work / "hosts"
        self.original = "127.0.0.1 localhost\n192.0.2.10 example.com\n10.0.0.5 www.example.com\n"
        self.hosts.write_text(self.original, encoding="utf-8")
        self.hosts.chmod(0o644)

    def run_script(self, action: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, HOSTS_FILE=str(self.hosts))
        return subprocess.run(["sh", str(self.script), action], env=env, capture_output=True, text=True, timeout=30)

    def test_add_then_remove_preserves_existing_mappings(self) -> None:
        added = self.run_script("add")
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertIn("already maps example.com", added.stderr)
        self.assertIn("127.0.0.1 example.com # recon:example.com-2026-10-17",
                      self.hosts.read_text(encoding="utf-8"))
        removed = self.run_script("remove")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(self.hosts.read_text(encoding="utf-8"), self.original)
        self.assertEqual(self.hosts.stat().st_mode & 0o777, 0o644)

    def test_add_is_idempotent(self) -> None:
        self.run_script("add")
        self.run_script("add")
        tagged = [line for line in self.hosts.read_text(encoding="utf-8").splitlines() if "# recon:" in line]
        self.assertEqual(len(tagged), 1)

    def test_remove_without_add_changes_nothing(self) -> None:
        result = self.run_script("remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hosts.read_text(encoding="utf-8"), self.original)

    def shim_failing(self, command: str) -> dict:
        shims = self.work / "shims"
        shims.mkdir(exist_ok=True)
        fake = shims / command
        fake.write_text("#!/bin/sh\necho simulated failure >&2\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)
        return {"PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}

    def run_with(self, action: str, env_extra: dict) -> subprocess.CompletedProcess:
        env = dict(os.environ, HOSTS_FILE=str(self.hosts), **env_extra)
        return subprocess.run(["sh", str(self.script), action], env=env, capture_output=True, text=True, timeout=30)

    def assert_untouched(self, expected: bytes) -> None:
        self.assertEqual(self.hosts.read_bytes(), expected)
        self.assertEqual(list(self.work.glob(".hosts.recon.*")), [], "temporary file left behind")

    def test_failed_rewrite_preserves_the_hosts_file(self) -> None:
        self.run_script("add")
        with_line = self.hosts.read_bytes()
        for command in ("mv", "cp"):
            with self.subTest(failing=command):
                result = self.run_with("remove", self.shim_failing(command))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unchanged", result.stderr)
                self.assert_untouched(with_line)
                shutil.rmtree(self.work / "shims")

    def test_failed_add_preserves_the_hosts_file(self) -> None:
        before = self.hosts.read_bytes()
        for command in ("mv", "cp", "awk"):
            with self.subTest(failing=command):
                result = self.run_with("add", self.shim_failing(command))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unchanged", result.stderr)
                self.assert_untouched(before)
                shutil.rmtree(self.work / "shims")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_directory_preserves_the_hosts_file(self) -> None:
        self.run_script("add")
        with_line = self.hosts.read_bytes()
        self.work.chmod(0o555)
        self.addCleanup(self.work.chmod, 0o755)
        result = self.run_script("remove")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.hosts.read_bytes(), with_line)

    def test_symlinked_hosts_file_is_refused(self) -> None:
        link = self.work / "hosts-link"
        link.symlink_to(self.hosts)
        result = subprocess.run(["sh", str(self.script), "add"], env=dict(os.environ, HOSTS_FILE=str(link)),
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(self.hosts.read_text(encoding="utf-8"), self.original)
        self.assertTrue(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
