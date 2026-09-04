#!/usr/bin/env python3
"""Fail when ROADMAP.md lists a closed issue as still pending.

ROADMAP.md says a PR closing a roadmap item moves its row in the same PR, and
calls that fair game to block on. That rule was broken twice anyway: once by a
contributor PR that nobody blocked, and once by an issue closed directly, where
no PR existed for the rule to bind on. A rule enforced only by attention is not
enforced.

So this checks the tracker. Any issue linked from a section that means "not done
yet" must actually be open.

Degrades to a SKIP rather than a failure when the GitHub API is unreachable or
unauthenticated. A fork pull request has no token, and a contributor's first PR
must not go red for a reason that has nothing to do with their change.

Exit codes:
    0  every pending row links an open issue, or the check could not run
    1  a pending row links a closed issue
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = "ehtishammubarik/websieve"
ROADMAP = "ROADMAP.md"

# Sections whose rows assert "this has not shipped". A link under any other
# heading, including Now and Not planned, is describing history and may point
# at a closed issue.
PENDING_HEADINGS = ("## Next", "## Later")

ISSUE_LINK = re.compile(rf"https://github\.com/{re.escape(REPO)}/issues/(\d+)")


def pending_issue_numbers(text: str) -> dict[int, str]:
    """Issue numbers linked under a pending heading, mapped to that heading."""
    found: dict[int, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line if line.startswith(PENDING_HEADINGS) else None
        if current is None:
            continue
        for match in ISSUE_LINK.finditer(line):
            found.setdefault(int(match.group(1)), current.lstrip("# ").strip())
    return found


def issue_state(number: int, token: str | None) -> str:
    """OPEN, CLOSED, or UNKNOWN if the API would not answer."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues/{number}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "websieve-roadmap-check",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)["state"].upper()
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return "UNKNOWN"


def main() -> int:
    with open(ROADMAP, encoding="utf-8") as handle:
        text = handle.read()
    pending = pending_issue_numbers(text)
    if not pending:
        print(f"no issues linked from {' or '.join(PENDING_HEADINGS)}; nothing to check")
        return 0

    token = os.environ.get("GITHUB_TOKEN") or None
    states = {n: issue_state(n, token) for n in sorted(pending)}

    if all(state == "UNKNOWN" for state in states.values()):
        # Almost certainly a fork PR with no token, or a rate limit. Saying
        # "could not check" is honest; failing here would punish a contributor
        # for something their change did not cause.
        print("SKIP: the GitHub API did not answer, so roadmap freshness was NOT verified.")
        print("      This is a skip, not a pass. Re-run on a branch in the main repo.")
        return 0

    stale = [(n, states[n], pending[n]) for n in sorted(states) if states[n] == "CLOSED"]
    for number in sorted(states):
        if states[number] != "CLOSED":
            print(f"  #{number:<4} {states[number]:<8} {pending[number]}")

    if stale:
        print()
        print(f"{ROADMAP} lists {len(stale)} closed issue(s) as still pending:")
        for number, _, heading in stale:
            print(f"  #{number} is CLOSED but appears under '{heading}'")
        print()
        print("Move each row into 'Now', naming the PR that delivered it, or delete the")
        print("row if it shipped before the current release and belongs in CHANGELOG.md.")
        print("ROADMAP.md's own 'How this file stays true' section says to do this in the")
        print("same PR that closes the item. This check exists because that was not enough.")
        return 1

    print(f"OK: all {len(states)} pending roadmap items link an open issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
