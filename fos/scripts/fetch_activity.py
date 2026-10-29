#!/usr/bin/env python3
"""
Fetch comment and submission counts for each candidate user via the PullPush
API, then save the results as user_activity.csv.

This script reads candidate_users.csv, asks the PullPush API how many recent
comments and submissions each username has, adds the two numbers together, and
writes the results to a new CSV file. It also prints progress while it works
and shows the busiest users at the end.
"""

import csv
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = REPO_ROOT / "candidate_users.csv"
OUTPUT_CSV = REPO_ROOT / "user_activity.csv"

USER_AGENT = "fos-research/1.0"
REQUEST_TIMEOUT_S = 30
DELAY_BETWEEN_REQUESTS_S = 1.2
COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/?author={author}&size=100"
SUBMISSION_URL = (
    "https://api.pullpush.io/reddit/search/submission/?author={author}&size=100"
)


def read_usernames(csv_path: Path) -> list[str]:
    """Read the username column from candidate_users.csv and return the list."""
    usernames: list[str] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            usernames.append(row["username"])
    return usernames


def fetch_count(url: str) -> int:
    """Ask PullPush for items at the given url and return how many came back.

    Returns -1 if the request fails for any reason (network error, bad
    response, or unreadable data) instead of crashing the whole script.
    """
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            return len(data.get("data", []))
    except HTTPError as e:
        print(f"  HTTP error {e.code} for {url}", flush=True)
        return -1
    except URLError as e:
        print(f"  Network error for {url}: {e}", flush=True)
        return -1
    except (TimeoutError, json.JSONDecodeError) as e:
        print(f"  Error for {url}: {e}", flush=True)
        return -1


def fetch_user_activity(username: str) -> tuple[int, int]:
    """Fetch comment and submission counts for one username from PullPush.

    Sleeps before each request so we never fire two requests at once.
    """
    time.sleep(DELAY_BETWEEN_REQUESTS_S)
    comment_count = fetch_count(COMMENT_URL.format(author=username))
    time.sleep(DELAY_BETWEEN_REQUESTS_S)
    submission_count = fetch_count(SUBMISSION_URL.format(author=username))
    return comment_count, submission_count


def save_results(rows: list[tuple[str, int, int, int]], csv_path: Path) -> None:
    """Write the activity rows to user_activity.csv at the repo root."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["username", "comment_count", "submission_count", "total_activity"]
        )
        for row in rows:
            writer.writerow(row)
    print(f"Saved {len(rows)} rows to {csv_path}", flush=True)


def print_top_users(rows: list[tuple[str, int, int, int]], top_n: int = 20) -> None:
    """Print the top users by total activity in a tidy table."""
    sorted_rows = sorted(rows, key=lambda r: r[3], reverse=True)
    print(f"\n{'=' * 60}")
    print(f"TOP {top_n} USERS BY TOTAL ACTIVITY")
    print(f"{'=' * 60}")
    print(f"{'rank':>4}  {'username':<30} {'comments':>8} {'subs':>6} {'total':>6}")
    print("-" * 60)
    for rank, (name, comments, subs, total) in enumerate(sorted_rows[:top_n], 1):
        print(f"{rank:>4}  {name:<30} {comments:>8} {subs:>6} {total:>6}")


def main() -> int:
    """Run the whole fetch-and-save job, then print the summary."""
    usernames = read_usernames(INPUT_CSV)
    total = len(usernames)
    print(f"Loaded {total} usernames from {INPUT_CSV}", flush=True)

    rows: list[tuple[str, int, int, int]] = []
    for i, username in enumerate(usernames, 1):
        comment_count, submission_count = fetch_user_activity(username)
        total_activity = comment_count + submission_count
        rows.append((username, comment_count, submission_count, total_activity))
        if i % 10 == 0 or i == total:
            print(
                f"Processed {i}/{total} (last: {username} total={total_activity})",
                flush=True,
            )

    save_results(rows, OUTPUT_CSV)
    print_top_users(rows)

    active = sum(1 for r in rows if r[3] >= 25)
    print(f"\nTotal users processed: {total}")
    print(f"Users with total_activity >= 25: {active}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
