"""Minimal parsing utilities for legacy Agent output.

Provides strip_thinking_tokens for cleaning LLM responses.
See docs/plans/policy-cascade-port-investigation.md

Contains: strip_thinking_tokens
"""

import re


def strip_thinking_tokens(text: str) -> str:
    """Strip thinking/reasoning tokens from model output.

    Handles all known formats across providers:
    - XML: <think>...</think>, <reasoning>...</reasoning>, etc.
    - Special markers: <|thinking|>...</|thinking|>
    - Pipe-style: |think>...|/think>
    - Kimi markers: ◁think▷...◁/think▷
    - Bracket markup: [THINK]...[/THINK]
    - Markdown sections: # Thinking\n...
    - Various self-closing and dangling variants
    - Thought-for prefix: "Thought for 2.3s ..."
    """
    if not text:
        return text

    # --- Phase 1: strip known thinking patterns from the ENTIRE text ---
    # These patterns use known delimiters that won't appear in legitimate
    # JSON content (angle brackets, pipes, special markers, etc.).

    # Strip leading "JSON" prefix some models emit before <think>
    # Runs BEFORE XML strip so it catches "JSON<think>...</think>{\"action\":...}"
    # as a unit before the XML regex strips the inner <think> block.
    text = re.sub(
        r"^[A-Za-z]+<think>.*?</think>\s*",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # XML-style paired tags: <think>, <reasoning>, <thought>, <reflection>, <analysis>
    text = re.sub(
        r"<(?:think|reasoning|thought|reflection|analysis)\b[^>]*>.*?"
        r"</(?:think|reasoning|thought|reflection|analysis)\b[^>]*>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Self-closing XML tags
    text = re.sub(
        r"<(?:think|reasoning|thought|reflection|analysis)[^>]*/>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Pipe-style: |think>...|/think> (some GGUF quants)
    text = re.sub(
        r"\|(?:think|thought|reasoning)\>.*?\|/(?:think|thought|reasoning)\>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Special markers: <|thinking|>...</|thinking|> (some GGUF quants)
    text = re.sub(
        r"<\|thinking\|>.*?<\|/thinking\|>",
        "",
        text,
        flags=re.DOTALL,
    )

    # Qwen uncensored special tokens: standalone markers that leak into output
    # <|thought|>, <|channel|>, <channel|> appear despite --reasoning off flag
    text = re.sub(
        r"<(?:\|thought\||\|channel\||channel\|)>",
        "",
        text,
    )

    # Kimi markers: ◁think▷...◁/think▷
    text = re.sub(
        r"◁think▷.*?◁/think▷",
        "",
        text,
        flags=re.DOTALL,
    )

    # Bracket markup: [THINK]...[/THINK]
    text = re.sub(
        r"\[THINK\].*?\[/THINK\]",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # "Thought for X seconds" prefixes
    text = re.sub(
        r"^Thought for \d+\.?\d*\s*(?:seconds?|ms)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Markdown thinking headers (# Thinking, ## Reasoning, etc.)
    # Stop at next header (*#) or blank line (\n\s*\n).
    text = re.sub(
        r"^#{1,3}\s*(?:Thinking|Reasoning|Thought|Analysis)\b[^\n]*\n.*?"
        r"(?=\n#{1,3}|\n\s*\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )

    # Bare /think, /reasoning, /analysis markers at start of line
    text = re.sub(
        r"(^|\n)\s*/(?:think|reasoning|analysis)\b.*?(?=\n|\Z)",
        "\\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Dangling inline /think, /reasoning, /analysis markers
    text = re.sub(
        r"(?i)\s+/(?:think|reasoning|analysis)\b(?=\s|$)",
        "",
        text,
    )

    # --- Phase 2: strip format tokens and prefixes from BEFORE the JSON ---
    # These patterns are scope-restricted to the region before the first
    # JSON brace so they can't corrupt data inside JSON string values.

    json_start = text.find("{")
    if json_start != -1:
        prefix = text[:json_start]
        body = text[json_start:]

        # Format tokens like <|channel|>, <|constrain|>, <|message|> (GPT-OSS, etc.)
        prefix = re.sub(
            r"<\|[a-z_]+\|>\s*",
            "",
            prefix,
            flags=re.IGNORECASE,
        )

        # Strip known GPT-OSS prefixes ending with "JSON"
        # Only matches short prefixes like "final JSON" or "JSON" —
        # not arbitrary natural language that happens to end with JSON.
        prefix = re.sub(
            r"^(?:final\s+)?JSON\s*$",
            "",
            prefix,
            flags=re.IGNORECASE,
        )

        text = prefix + body

    return text.strip()


def strip_reasoning_prose(text: str) -> str:
    """Strip prose-style reasoning leakage from model output.

    Handles bullet-list and markdown-list reasoning patterns where
    the model outputs a full character analysis before the actual speech.
    """
    import re

    if not text or len(text) < 30:
        return text

    lines = text.strip().split('\n')

    # ── Detect bullet-list reasoning ──
    # These patterns indicate the text is a structured self-analysis,
    # not a speech. The actual speech (if any) is the last portion.
    trait_keywords = ['openness','conscientiousness','extraversion','agreeableness','neuroticism']
    role_patterns = [
        r'^\s*[\*\-\•]\s*\*{0,2}role:',      # * Role: or - **Role:**
        r'^\s*[\*\-\•]\s*\*{0,2}age:',        # * Age: or - **Age:**
        r'^\s*[\*\-\•]\s*\*{0,2}user:',       # * User:
        r'^\s*[\*\-\•]\s*\*{0,2}traits?:',    # * Traits:
        r'^\s*[\*\-\•]\s*\*{0,2}persona:',    # * Persona:
    ]

    # Count lines matching reasoning patterns
    reasoning_line_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        # Check role/trait bullet patterns
        for pat in role_patterns:
            if re.match(pat, stripped):
                reasoning_line_indices.append(i)
                break
        # Check for trait value lines (e.g., "Openness: 78")
        for kw in trait_keywords:
            if kw in stripped and any(c.isdigit() for c in stripped):
                if i not in reasoning_line_indices:
                    reasoning_line_indices.append(i)
                break
        # Numbered reasoning steps
        if re.match(r'^\d+\.\s*(?:deconstruct|analyze|synthesize|map|draft|consider|check|refine)', stripped):
            reasoning_line_indices.append(i)

    # If we found substantial reasoning (5+ lines of it), strip everything
    # from the start through the reasoning block
    if len(reasoning_line_indices) >= 5:
        # Find where the reasoning block ends and the actual speech begins
        # The speech is typically the last non-empty, non-reasoning portion
        last_reasoning = max(reasoning_line_indices)

        # Walk backwards from end to find where speech starts
        # Speech lines are typically not bullet/trait/numbered lines
        speech_start = len(lines)
        for i in range(len(lines) - 1, last_reasoning, -1):
            if lines[i].strip() and i not in reasoning_line_indices:
                speech_start = i
            elif speech_start < len(lines):
                break

        # Collect speech lines from after the reasoning block
        if speech_start < len(lines):
            speech_lines = [line for i, line in enumerate(lines) if i >= speech_start and line.strip()]
            return ' '.join(speech_lines).strip()
        else:
            return ''  # All content was reasoning

    # Fallback: check if text is dominated by trait analysis (compact format)
    trait_count = sum(1 for kw in trait_keywords if kw in text.lower())
    word_count = len(text.split())
    if trait_count >= 3 and word_count > 60:
        # Text is too long for a speech and has many trait keywords — likely all reasoning
        # Try to extract just the last sentence
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) >= 3:
            # Take last 1-2 sentences that don't contain trait keywords
            clean_sentences = [s for s in sentences[-3:] if not any(kw in s.lower() for kw in trait_keywords)]
            if clean_sentences:
                return ' '.join(clean_sentences).strip()
        return ''  # All reasoning

    return text.strip()


def detect_reasoning_leak(text: str) -> bool:
    """Return True if the text contains residual reasoning markers."""
    if not text or len(text) < 10:
        return False

    import re
    text_lower = text.lower()

    # Tag-style
    for p in [r'<think', r'</think', r'<reasoning', r'<\|thinking\|>']:
        if re.search(p, text_lower):
            return True

    # Bullet-list role/trait analysis (most common leak format)
    bullet_reasoning = [
        r'^\s*[\*\-\•]\s*\*{0,2}(?:role|age|user|traits?|persona|work sector|political view)\s*:',
        r'^\s*[\*\-\•]\s*\*{0,2}(?:openness|conscientiousness|extraversion|agreeableness|neuroticism)',
    ]
    for p in bullet_reasoning:
        if re.search(p, text_lower, re.MULTILINE):
            return True

    # Numbered analysis steps
    if re.search(r'^\d+\.\s*(?:deconstruct|analyze|synthesize|map\s+to|draft|consider|refine)', text_lower, re.MULTILINE):
        return True

    # Prose reasoning headers
    for p in [r'^thinking\s*process', r'^let\s+me\s+think', r'^step\s*\d+\s*:', r'^deconstruct\s+the\s+persona']:
        if re.search(p, text_lower, re.MULTILINE):
            return True

    # High trait keyword density in a long text (>200 words, 4+ trait mentions)
    trait_kws = ['openness','conscientiousness','extraversion','agreeableness','neuroticism']
    trait_count = sum(1 for kw in trait_kws if kw in text_lower)
    word_count = len(text.split())
    if trait_count >= 4 and word_count > 200:
        return True

    return False
