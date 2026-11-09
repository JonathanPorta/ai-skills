"""Temporary fixture directories for the test suite.

wt.sh refuses worktree roots under /tmp, /private/tmp and /var/tmp, and on Linux
tempfile.mkdtemp() lands under /tmp. Fixtures therefore live under the repository
(.tmp-tests/, ignored by git) so the suite exercises the real guard on every platform
while the explicit forbidden-temp cases stay negative tests.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = Path(os.environ.get("AI_SKILLS_TEST_TMP") or ROOT / ".tmp-tests")


def mkdtemp(prefix: str = "test-") -> str:
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=str(TEST_TMP))
