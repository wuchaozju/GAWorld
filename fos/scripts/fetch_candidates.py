#!/usr/bin/env python3
"""
Fetch 100 recent comments from 3 subreddits via PullPush API,
count unique authors, save as candidate_users.csv.
"""

import csv, json, time, sys
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

SUBREDDITS = ["AskReddit", "personalfinance", "relationship_advice"]
SIZE = 100
OUTPUT = Path(__file__).resolve().parent.parent / "candidate_users.csv"
DELAY_S = 1.2
EXCLUDE_AUTHORS = {"[deleted]", "AutoModerator"}

def fetch_comments(subreddit, size=100):
    url = f"https://api.pullpush.io/reddit/search/comment/?subreddit={subreddit}&size={size}"
    req = Request(url, headers={"User-Agent": "fos-research/1.0"})
    print(f"Fetching r/{subreddit} ... ", end="", flush=True)
    try:
        with urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            comments = data.get("data", [])
            print(f"got {len(comments)} comments")
            return comments
    except URLError as e:
        print(f"ERROR: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"JSON decode ERROR: {e}")
        return []

def main():
    all_comments = []
    for sub in SUBREDDITS:
        comments = fetch_comments(sub, SIZE)
        all_comments.extend(comments)
        if sub != SUBREDDITS[-1]:
            time.sleep(DELAY_S)
    
    total = len(all_comments)
    print(f"\nTotal comments fetched: {total}")
    
    counter = Counter()
    for c in all_comments:
        author = c.get("author", "")
        if author and author not in EXCLUDE_AUTHORS:
            counter[author] += 1
    
    unique = len(counter)
    print(f"Unique authors (excl. deleted/AutoModerator): {unique}")
    
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "count_in_sample"])
        for username, count in counter.most_common():
            writer.writerow([username, count])
    print(f"Saved {counter.most_common().__len__()} rows to {OUTPUT}")
    
    print(f"\n{'='*60}")
    print("TOP 30 AUTHORS BY FREQUENCY")
    print(f"{'='*60}")
    print(f"{'username':<30} {'count_in_sample':>6}")
    print(f"{'-'*30} {'-'*6}")
    for i, (name, count) in enumerate(counter.most_common(30), 1):
        print(f"{i:2}. {name:<27} {count:>6}")
    
    print(f"\n{'='*60}")
    print("TOP 10 — SUBREDDIT BREAKDOWN")
    print(f"{'='*60}")
    for name, _ in counter.most_common(10):
        subs = Counter()
        for c in all_comments:
            if c.get("author") == name:
                subs[c.get("subreddit", "?")] += 1
        parts = ", ".join(f"r/{s}={n}" for s, n in subs.most_common())
        print(f"  {name}: {parts}")
    
    print(f"\nDone. Full data: {OUTPUT}")

if __name__ == "__main__":
    main()
