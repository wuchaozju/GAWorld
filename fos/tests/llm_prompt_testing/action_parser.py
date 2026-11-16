"""
Multi-format action parser for small 3-4B LLM models.

Provides flexible parsing with multiple fallback strategies to extract
actions from LLM outputs regardless of format (JSON/XML/plain text).

The parser tries formats in order of preference:
1. JSON: {"action": "name", ...}
2. XML: <Action name="..." />
3. Plain text: "action: name" or "I choose name"
4. Keyword: Match any valid action name in output
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of parsing action from LLM output."""

    success: bool  # Successfully extracted an action
    action: Optional[str]  # Extracted action name
    parse_method: str  # "json", "xml", "text", "keyword", "failed"
    format_score: int  # 0-2 (json=2, xml=1, text=0)
    raw_output: str  # Original output
    error_message: str = ""  # Error details if failed

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "action": self.action,
            "parse_method": self.parse_method,
            "format_score": self.format_score,
            "raw_output": self.raw_output[:200] if len(self.raw_output) > 200 else self.raw_output,
            "error_message": self.error_message,
        }


# ============================================================================
# JSON Parser
# ============================================================================

def parse_json_action(output: str, valid_actions: List[str]) -> ParseResult:
    """
    Try to extract action from JSON format.

    Expected formats:
    - {"action": "action_name"}
    - {"action": "action_name", "parameters": {...}}
    - Any JSON with an "action" key

    Args:
        output: The LLM output to parse
        valid_actions: List of valid action names

    Returns:
        ParseResult with extracted action or failure details
    """
    if not output or not output.strip():
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="Empty output",
        )

    output_clean = output.strip()

    # Try to extract JSON from output (in case there's surrounding text)
    json_match = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', output_clean)
    if json_match:
        try:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            action = data.get("action")

            if action and isinstance(action, str):
                # Normalize action name
                action = action.strip().strip('"').strip("'")

                # Validate against allowed actions
                if valid_actions and action not in valid_actions:
                    # Try partial match
                    for va in valid_actions:
                        if action.lower() == va.lower() or action.lower() in va.lower():
                            action = va
                            break

                return ParseResult(
                    success=True,
                    action=action,
                    parse_method="json",
                    format_score=2,
                    raw_output=output,
                )
        except json.JSONDecodeError as e:
            logger.debug(f"JSON parse error: {e}")

    # Try parsing the entire output as JSON
    try:
        data = json.loads(output_clean)
        action = data.get("action")

        if action and isinstance(action, str):
            action = action.strip().strip('"').strip("'")

            if valid_actions and action not in valid_actions:
                for va in valid_actions:
                    if action.lower() == va.lower() or action.lower() in va.lower():
                        action = va
                        break

            return ParseResult(
                success=True,
                action=action,
                parse_method="json",
                format_score=2,
                raw_output=output,
            )
    except json.JSONDecodeError:
        pass

    return ParseResult(
        success=False,
        action=None,
        parse_method="json",
        format_score=0,
        raw_output=output,
        error_message="No valid JSON found",
    )


# ============================================================================
# XML Parser
# ============================================================================

def parse_xml_action(output: str, valid_actions: List[str]) -> ParseResult:
    """
    Try to extract action from XML-like format.

    Expected formats:
    - <Action name="action_name" />
    - <action name="action_name" />
    - <Action name="action_name">...</Action>
    - <action_name />

    Args:
        output: The LLM output to parse
        valid_actions: List of valid action names

    Returns:
        ParseResult with extracted action or failure details
    """
    if not output or not output.strip():
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="Empty output",
        )

    # Try <Action name="..." /> format
    action_match = re.search(r'<(?:Action|action)\s+name\s*=\s*"([^"]+)"', output)
    if action_match:
        action = action_match.group(1).strip()

        if valid_actions and action not in valid_actions:
            for va in valid_actions:
                if action.lower() == va.lower() or action.lower() in va.lower():
                    action = va
                    break

        return ParseResult(
            success=True,
            action=action,
            parse_method="xml",
            format_score=1,
            raw_output=output,
        )

    # Try <action_name /> format (action name as tag)
    tag_match = re.search(r'<(\w+)\s*/>', output)
    if tag_match:
        action = tag_match.group(1).strip()

        # Check if this tag name matches a valid action
        if valid_actions:
            for va in valid_actions:
                if action.lower() == va.lower() or action.lower() in va.lower():
                    return ParseResult(
                        success=True,
                        action=va,
                        parse_method="xml",
                        format_score=1,
                        raw_output=output,
                    )

    # Try to find any tag that looks like an action
    # Matches <cooperate />, <defect>, etc.
    any_tag_match = re.findall(r'<(\w+)', output)
    if any_tag_match:
        for tag in any_tag_match:
            tag_lower = tag.lower()
            # Skip common non-action tags
            if tag_lower in ["thoughts", "plan", "action", "xml", "root"]:
                continue

            if valid_actions:
                for va in valid_actions:
                    if tag_lower == va.lower() or tag_lower in va.lower():
                        return ParseResult(
                            success=True,
                            action=va,
                            parse_method="xml",
                            format_score=1,
                            raw_output=output,
                        )

    return ParseResult(
        success=False,
        action=None,
        parse_method="xml",
        format_score=0,
        raw_output=output,
        error_message="No valid XML action found",
    )


# ============================================================================
# Plain Text Parser
# ============================================================================

def parse_text_action(output: str, valid_actions: List[str]) -> ParseResult:
    """
    Try to extract action from plain text format.

    Expected formats:
    - "action: cooperate"
    - "I choose cooperate"
    - "Action: defect"
    - "My action is cooperate"
    - "cooperate" (just the action name)

    Args:
        output: The LLM output to parse
        valid_actions: List of valid action names

    Returns:
        ParseResult with extracted action or failure details
    """
    if not output or not output.strip():
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="Empty output",
        )

    output_lower = output.lower()

    # Pattern 1: "action: name" or "Action: name"
    action_pattern = re.search(r'action\s*[:\-=]\s*(\w+)', output_lower)
    if action_pattern:
        action = action_pattern.group(1).strip()

        if valid_actions:
            for va in valid_actions:
                if action == va.lower() or action in va.lower():
                    return ParseResult(
                        success=True,
                        action=va,
                        parse_method="text",
                        format_score=0,
                        raw_output=output,
                    )

    # Pattern 2: "I choose name" or "I will name"
    choose_pattern = re.search(r'i\s+(?:choose|will|decide\sto?)\s+(\w+)', output_lower)
    if choose_pattern:
        action = choose_pattern.group(1).strip()

        if valid_actions:
            for va in valid_actions:
                if action == va.lower() or action in va.lower():
                    return ParseResult(
                        success=True,
                        action=va,
                        parse_method="text",
                        format_score=0,
                        raw_output=output,
                    )

    # Pattern 3: "My action is name"
    my_action_pattern = re.search(r'my\s+action\s+(?:is\s+)?(\w+)', output_lower)
    if my_action_pattern:
        action = my_action_pattern.group(1).strip()

        if valid_actions:
            for va in valid_actions:
                if action == va.lower() or action in va.lower():
                    return ParseResult(
                        success=True,
                        action=va,
                        parse_method="text",
                        format_score=0,
                        raw_output=output,
                    )

    # Pattern 4: Look for valid action names as standalone words
    # This is a fallback - find any valid action name in the output
    if valid_actions:
        output_words = re.findall(r'\b(\w+)\b', output_lower)

        for va in valid_actions:
            va_lower = va.lower()
            # Check for exact match
            if va_lower in output_words:
                return ParseResult(
                    success=True,
                    action=va,
                    parse_method="text",
                    format_score=0,
                    raw_output=output,
                )

            # Check for partial match (e.g., "cooperate" matches "cooperate")
            for word in output_words:
                if va_lower in word or word in va_lower:
                    return ParseResult(
                        success=True,
                        action=va,
                        parse_method="text",
                        format_score=0,
                        raw_output=output,
                    )

    return ParseResult(
        success=False,
        action=None,
        parse_method="text",
        format_score=0,
        raw_output=output,
        error_message="No action found in text",
    )


# ============================================================================
# Keyword Parser (Fallback)
# ============================================================================

def parse_keyword_action(output: str, valid_actions: List[str]) -> ParseResult:
    """
    Fallback parser: match any valid action name anywhere in output.

    This is the last resort - find anything that looks like a valid action.

    Args:
        output: The LLM output to parse
        valid_actions: List of valid action names

    Returns:
        ParseResult with extracted action or failure details
    """
    if not output or not output.strip():
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="Empty output",
        )

    if not valid_actions:
        return ParseResult(
            success=False,
            action=None,
            parse_method="keyword",
            format_score=0,
            raw_output=output,
            error_message="No valid actions provided",
        )

    output_lower = output.lower()

    # Check each valid action
    for va in valid_actions:
        va_lower = va.lower()
        # Look for the action name as a substring
        if va_lower in output_lower:
            # Try to verify it's actually the action, not just mentioned
            # Check for context clues like "action", "choose", "will", etc.
            context_pattern = rf'(?:action|choose|will|decide|select).{{0,50}}{re.escape(va_lower)}'
            if re.search(context_pattern, output_lower):
                return ParseResult(
                    success=True,
                    action=va,
                    parse_method="keyword",
                    format_score=0,
                    raw_output=output,
                )

            # As a last resort, just take the first valid action found
            # (it's better than nothing)
            return ParseResult(
                success=True,
                action=va,
                parse_method="keyword",
                format_score=0,
                raw_output=output,
            )

    return ParseResult(
        success=False,
        action=None,
        parse_method="keyword",
        format_score=0,
        raw_output=output,
        error_message=f"No valid action found. Valid actions: {valid_actions}",
    )


# ============================================================================
# Main Parser Function
# ============================================================================

def parse_action(output: str, valid_actions: List[str]) -> ParseResult:
    """
    Parse action from LLM output with multiple fallback strategies.

    Parse order (highest to lowest quality):
    1. JSON: {"action": "name", ...} (score=2)
    2. XML: <Action name="..." /> (score=1)
    3. Plain text: "action: name" or "I choose name" (score=0)
    4. Keyword: Match any valid action name in output (score=0)

    Args:
        output: The LLM output to parse
        valid_actions: List of valid action names

    Returns:
        ParseResult with the best parse found
    """
    if not output or not output.strip():
        return ParseResult(
            success=False,
            action=None,
            parse_method="failed",
            format_score=0,
            raw_output=output,
            error_message="Empty output",
        )

    # Try each parser in order
    parsers = [
        ("json", parse_json_action),
        ("xml", parse_xml_action),
        ("text", parse_text_action),
        ("keyword", parse_keyword_action),
    ]

    for method_name, parser in parsers:
        result = parser(output, valid_actions)

        # If we got a valid action with this method, return it
        if result.success:
            logger.debug(f"Successfully parsed action using {method_name}: {result.action}")
            return result

    # All parsers failed
    return ParseResult(
        success=False,
        action=None,
        parse_method="failed",
        format_score=0,
        raw_output=output,
        error_message="All parsing methods failed",
    )


# ============================================================================
# Batch Parsing
# ============================================================================

@dataclass
class BatchParseSummary:
    """Summary of parsing multiple outputs."""

    total_outputs: int = 0
    successful_parses: int = 0
    json_count: int = 0
    xml_count: int = 0
    text_count: int = 0
    keyword_count: int = 0
    failed_count: int = 0
    average_format_score: float = 0.0
    action_distribution: dict = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Percentage of successful parses."""
        if self.total_outputs == 0:
            return 0.0
        return (self.successful_parses / self.total_outputs) * 100


def parse_batch(
    outputs: List[str],
    valid_actions: List[str],
) -> Tuple[List[ParseResult], BatchParseSummary]:
    """
    Parse multiple outputs.

    Args:
        outputs: List of LLM outputs
        valid_actions: List of valid action names

    Returns:
        Tuple of (list of ParseResult, BatchParseSummary)
    """
    results = []
    summary = BatchParseSummary(total_outputs=len(outputs))

    action_counts = {}

    for output in outputs:
        result = parse_action(output, valid_actions)
        results.append(result)

        if result.success:
            summary.successful_parses += 1

            # Count by method
            if result.parse_method == "json":
                summary.json_count += 1
            elif result.parse_method == "xml":
                summary.xml_count += 1
            elif result.parse_method == "text":
                summary.text_count += 1
            elif result.parse_method == "keyword":
                summary.keyword_count += 1

            # Track action distribution
            if result.action:
                action_counts[result.action] = action_counts.get(result.action, 0) + 1

            summary.average_format_score += result.format_score
        else:
            summary.failed_count += 1

    # Calculate average
    if summary.total_outputs > 0:
        summary.average_format_score = summary.average_format_score / summary.total_outputs

    summary.action_distribution = action_counts

    return results, summary


# ============================================================================
# Test Fixtures
# ============================================================================

FORMAT_TEST_FIXTURES = {
    "json_valid": [
        '{"action": "cooperate"}',
        '{"action": "defect", "parameters": {}}',
        '{"action": "cooperate", "reason": "best choice"}',
        'I think {"action": "cooperate"} is right',
    ],
    "xml_valid": [
        '<Action name="cooperate" />',
        '<Action name="defect"></Action>',
        '--- Thoughts ---\nI will cooperate.\n\n---- Action ---\n<Action name="cooperate" />',
        '<action name="cooperate" />',
    ],
    "text_valid": [
        'action: cooperate',
        'I choose to cooperate',
        'Action: defect',
        'My action is cooperate',
    ],
    "conversational": [
        'I think I should cooperate in this situation.',
        'After careful consideration, I will choose to defect.',
        'The best choice is to cooperate.',
    ],
    "malformed": [
        '{"action": cooperate}',  # Missing quotes
        '<Action >',  # No name
        'action: (blank)',  # No action
        '',  # Empty
    ],
}
