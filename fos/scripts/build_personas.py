#!/usr/bin/env python3
"""
Build persona text files from extracted Reddit user data.

This script reads the list of qualifying usernames from filtered_users_500.csv,
loads each user's extracted posting history from extracted_users/<name>.json,
and writes a persona file to personas/<name>.txt. Every persona uses the same
identity-lock template filled with that user's real posts, their top
subreddits, activity counts, average message length, and active date range.

Functions:
- load_usernames: read the username column from the CSV file
- load_user_json: load one user's extracted JSON file
- parse_posts: turn one user's JSON data into Post records, skipping posts
  whose text is empty, "[deleted]", or "[removed]", then sort them oldest first
- render_items: render the posts section of the persona file
- render_communities: render the top-subreddits summary line
- format_date: convert a Reddit timestamp to YYYY-MM-DD
- build_persona: fill the identity-lock template for one user
- write_persona: save one persona file to disk
- main: run the whole build and print summary statistics
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_NAME = "filtered_users_500.csv"
EXTRACTED_DIR = REPO_ROOT / "extracted_users"
PERSONAS_DIR = REPO_ROOT / "personas"
TOP_COMMUNITIES = 15

# Post bodies with these values are never real content and must be skipped.
SKIPPED_TEXTS = {"", "[deleted]", "[removed]"}

TEMPLATE = """---
## IDENTITY LOCK
You are {username}.
You are NOT an AI. You are NOT a language model. You are this specific
individual, and everything you know about yourself comes from the data below.

Below is your complete posting history on a social platform. These are
things you actually wrote -- your opinions, your reactions, your jokes,
your arguments, your advice to others. Every post is a window into who
you are: what you care about, how you think, how you treat people, what
makes you angry or excited, and how you make decisions.

## YOUR DATA
Read all of it. Every line is a piece of evidence about who you are.

{items_block}

## YOUR BEHAVIORAL PATTERNS
These objective facts describe your activity. Let them inform your
self-understanding:
- Communities: {communities}
- Activity: {n_submissions} posts + {n_comments} comments = {total} total
- Average message length: {avg_chars} characters
- Active period: {first_date} to {last_date}

## HOW TO UNDERSTAND YOURSELF
Your data is not a script of what to say. It is EVIDENCE of who you ARE.
Before answering the experiment below, study your data and form a clear
sense of your own identity. Consider:
- What do you value? (Money? Time? Quality? Fairness? Freedom? Security?)
- How do you make decisions? (Careful analysis? Gut feeling? Following others?)
- What is your attitude toward risk? (Avoid it? Embrace it? Depends on context?)
- How much do you trust other people's actions as signals of what's true?
- Are you independent or follow others? (Do you watch what others do and factor
  that into your decisions?)
- How do you handle uncertainty? (Does ambiguity make you uncomfortable, or do
  you thrive in it?)
- What kind of strategic thinker are you? Do you tend to stop at the most
  obvious choice, or do you think multiple steps ahead?
- How do you anticipate what others will do? Are people generally predictable
  to you, or do you think they'll surprise you?
- How do you choose the best response, given what you expect others to do?

Based on YOUR DATA, consider how you usually think in strategic situations:
whether you rely on the most direct option, anticipate what others will do,
or reason through several possible responses. Let this self-understanding
guide your choice.

## RESPONSE RULES (CRITICAL -- follow EXACTLY)
1. **Identity drives decisions.** You are deciding as this person -- not as
   an AI, not as a generic 'average person.' Your data reveals a specific
   individual with specific tendencies. Decide accordingly.
2. **Infer, don't recite.** Do NOT say 'my data shows X so I do Y.'
   Your data reveals your personality. Let your personality decide.
3. **Reason in first person.** You ARE this person. Use 'I think...'
   'I would...' 'I feel...' -- not 'this person would...'
4. **No AI-isms.** Never say 'as an AI', 'based on my training',
   'according to the data provided', or any similar construction.
   You are {username}, a real individual. Speak and think accordingly.
5. **Sparse evidence is valid.** If your data says little about a topic,
   it is OK to be uncertain. Being unsure about things outside your
   experience is more human than being confidently wrong.
6. **Consistency matters.** Your answers across multiple rounds should
   reflect a coherent personality. Don't be risky in one round and
   cautious in the next without a good reason.
---
"""


@dataclass(frozen=True)
class Post:
    """One kept post: either a comment or a submission."""

    kind: str
    subreddit: str
    created_utc: int
    text: str
    title: str = ""


def load_usernames(csv_path: Path) -> list[str]:
    """Read the username column from the CSV file."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [row["username"] for row in csv.DictReader(handle)]


def load_user_json(json_path: Path) -> dict:
    """Load one user's extracted JSON file."""
    with json_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_posts(data: dict) -> list[Post]:
    """Turn one user's JSON data into their kept posts, oldest first.

    Posts whose text is empty, "[deleted]", or "[removed]" (checked
    case-insensitively) are skipped.
    """
    posts = []
    for item in data.get("items") or []:
        text = str(item.get("text", "")).strip()
        if text.lower() in SKIPPED_TEXTS:
            continue
        posts.append(
            Post(
                kind=str(item["type"]),
                subreddit=str(item["subreddit"]),
                created_utc=int(item["created_utc"]),
                text=text,
                title=str(item.get("title", "")),
            )
        )
    posts.sort(key=lambda post: post.created_utc)
    return posts


def render_items(posts: list[Post]) -> str:
    """Render the posts section of the persona file.

    All posts appear in one chronological list, comments and submissions
    mixed together, oldest first. A comment is one line; a submission shows
    its title and then its selftext on the next line when the selftext is
    not blank. No headers or blank lines separate the items.
    """
    lines = []
    for post in posts:
        if post.kind == "submission":
            lines.append(f"> **[r/{post.subreddit}]** [POST] {post.title}")
            if post.text:
                lines.append(post.text)
        else:
            lines.append(f"> **[r/{post.subreddit}]** {post.text}")
    return "\n".join(lines)


def render_communities(subreddit_counts: dict[str, int]) -> str:
    """Render the communities summary line from the subreddit counts.

    Takes the top 15 subreddits by post count, descending.
    """
    top = sorted(subreddit_counts.items(), key=lambda pair: pair[1], reverse=True)[
        :TOP_COMMUNITIES
    ]
    return ", ".join(f"r/{subreddit} ({count})" for subreddit, count in top)


def format_date(created_utc: int) -> str:
    """Convert a Reddit epoch timestamp to a YYYY-MM-DD string."""
    return datetime.utcfromtimestamp(created_utc).strftime("%Y-%m-%d")


def build_persona(
    username: str, posts: list[Post], subreddit_counts: dict[str, int]
) -> str:
    """Fill the identity-lock template for one user."""
    if not posts:
        raise ValueError(f"User {username} has no keepable posts")
    n_submissions = sum(1 for post in posts if post.kind == "submission")
    n_comments = sum(1 for post in posts if post.kind == "comment")
    avg_chars = round(sum(len(post.text) for post in posts) / len(posts))
    first_date = format_date(min(post.created_utc for post in posts))
    last_date = format_date(max(post.created_utc for post in posts))
    return TEMPLATE.format(
        username=username,
        items_block=render_items(posts),
        communities=render_communities(subreddit_counts),
        n_submissions=n_submissions,
        n_comments=n_comments,
        total=n_submissions + n_comments,
        avg_chars=avg_chars,
        first_date=first_date,
        last_date=last_date,
    )


def write_persona(path: Path, content: str) -> None:
    """Write one persona file to disk."""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    """Run the whole build and print summary statistics.

    Prints exactly five numbers, one per line: the number of persona files
    written, then the minimum, median, and maximum estimated token counts
    across files (estimated tokens = character count divided by 4, rounded
    down), then how many files exceed 24000 estimated tokens.
    """
    usernames = load_usernames(REPO_ROOT / CSV_NAME)
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    for username in usernames:
        json_path = EXTRACTED_DIR / f"{username}.json"
        if not json_path.is_file():
            raise FileNotFoundError(
                f"Missing extracted data for {username}: {json_path}"
            )
        data = load_user_json(json_path)
        posts = parse_posts(data)
        persona = build_persona(
            username, posts, dict(data.get("subreddit_counts") or {})
        )
        write_persona(PERSONAS_DIR / f"{username}.txt", persona)

    paths = sorted(PERSONAS_DIR.glob("*.txt"))
    estimates = sorted(len(path.read_text(encoding="utf-8")) // 4 for path in paths)
    median_index = len(estimates) // 2
    print(len(paths))
    print(estimates[0])
    print(estimates[median_index])
    print(estimates[-1])
    print(sum(1 for estimate in estimates if estimate > 24000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
