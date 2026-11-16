"""Rule engine for automatic event triggering based on thresholds.

The rule engine evaluates simulation state against configured rules
and generates events when conditions are met.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from fos.core.external_event import ExternalEvent, ExternalEventType, EventSource, Severity


class ConditionOperator(Enum):
    """Operators for rule conditions."""

    EQ = "eq"  # equal
    NE = "ne"  # not equal
    GT = "gt"  # greater than
    GE = "ge"  # greater than or equal
    LT = "lt"  # less than
    LE = "le"  # less than or equal
    IN = "in"  # in list
    NOT_IN = "not_in"  # not in list
    CONTAINS = "contains"  # string contains


@dataclass
class RuleCondition:
    """A single condition in a rule.

    Example:
        field="resources.food"
        operator=ConditionOperator.LT
        value=100
    """

    field: str  # Path to field in context, e.g., "resources.food" or "agents.length"
    operator: ConditionOperator
    value: Any

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate this condition against the context.

        Args:
            context: The simulation state context.

        Returns:
            True if condition is met.
        """
        field_value = self._get_nested_field(context, self.field)

        if field_value is None:
            return False

        return self._compare(field_value, self.operator, self.value)

    def _get_nested_field(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get a nested field from a dictionary using dot notation.

        Supports special properties for collections:
        - length: returns len(list)
        - count: returns len(list)
        - first: returns list[0]
        - last: returns list[-1]
        """
        keys = field_path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list):
                if key.isdigit():
                    idx = int(key)
                    value = value[idx] if 0 <= idx < len(value) else None
                elif key == "length" or key == "count":
                    value = len(value)
                elif key == "first":
                    value = value[0] if value else None
                elif key == "last":
                    value = value[-1] if value else None
                else:
                    return None
            else:
                return None
        return value

    def _compare(self, field_value: Any, operator: ConditionOperator, rule_value: Any) -> bool:
        """Compare field value against rule value using operator."""
        if operator == ConditionOperator.EQ:
            return field_value == rule_value
        if operator == ConditionOperator.NE:
            return field_value != rule_value
        if operator == ConditionOperator.GT:
            return field_value > rule_value
        if operator == ConditionOperator.GE:
            return field_value >= rule_value
        if operator == ConditionOperator.LT:
            return field_value < rule_value
        if operator == ConditionOperator.LE:
            return field_value <= rule_value
        if operator == ConditionOperator.IN:
            return field_value in rule_value
        if operator == ConditionOperator.NOT_IN:
            return field_value not in rule_value
        if operator == ConditionOperator.CONTAINS:
            return str(rule_value) in str(field_value)
        return False


@dataclass
class RuleAction:
    """Action to perform when a rule is triggered."""

    event_type: ExternalEventType
    source: EventSource = EventSource.MANUAL
    severity: Severity = Severity.MEDIUM
    title_template: str = ""
    content_template: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    """A rule that triggers events based on conditions."""

    id: str
    name: str
    description: str = ""
    conditions: List[RuleCondition] = field(default_factory=list)
    action: RuleAction = field(default_factory=lambda: RuleAction(
        event_type=ExternalEventType.MANUAL,
        title_template="Rule triggered",
        content_template="A rule condition was met.",
    ))
    enabled: bool = True
    cooldown_seconds: int = 300  # Minimum time between triggers
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0

    @classmethod
    def create(
        cls,
        name: str,
        conditions: List[RuleCondition],
        action: RuleAction,
        description: str = "",
        enabled: bool = True,
        cooldown_seconds: int = 300,
    ) -> "Rule":
        """Factory method to create a new Rule."""
        return cls(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            conditions=conditions,
            action=action,
            enabled=enabled,
            cooldown_seconds=cooldown_seconds,
        )

    def can_trigger(self) -> bool:
        """Check if rule can be triggered (cooldown elapsed)."""
        if not self.enabled:
            return False
        if self.last_triggered is None:
            return True

        elapsed = (datetime.now() - self.last_triggered).total_seconds()
        return elapsed >= self.cooldown_seconds

    def trigger(self, context: Dict[str, Any]) -> Optional[ExternalEvent]:
        """Trigger this rule and create an event.

        Args:
            context: Current simulation state.

        Returns:
            ExternalEvent if triggered, None otherwise.
        """
        if not self.can_trigger():
            return None

        for condition in self.conditions:
            if not condition.evaluate(context):
                return None

        # All conditions met - create event
        title = self._render_template(self.action.title_template, context)
        content = self._render_template(self.action.content_template, context)

        event = ExternalEvent.create(
            event_type=self.action.event_type,
            source=self.action.source,
            title=title,
            content=content,
            severity=self.action.severity,
            metadata={**self.action.metadata, "rule_id": self.id, "rule_name": self.name},
        )

        self.last_triggered = datetime.now()
        self.trigger_count += 1

        return event

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """Render a template string with context values."""
        result = template
        for key, value in context.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result


class RuleEngine:
    """Engine for evaluating rules against simulation state."""

    def __init__(self) -> None:
        self._rules: Dict[str, Rule] = {}

    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the engine.

        Args:
            rule: The rule to add.
        """
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule from the engine.

        Args:
            rule_id: ID of the rule to remove.

        Returns:
            True if rule was removed, False if not found.
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """Get a rule by ID."""
        return self._rules.get(rule_id)

    def get_all_rules(self) -> List[Rule]:
        """Get all rules."""
        return list(self._rules.values())

    def get_enabled_rules(self) -> List[Rule]:
        """Get all enabled rules."""
        return [r for r in self._rules.values() if r.enabled]

    def evaluate(self, context: Dict[str, Any]) -> List[ExternalEvent]:
        """Evaluate all rules against the context.

        Args:
            context: Current simulation state.

        Returns:
            List of events triggered by matching rules.
        """
        events = []
        for rule in self.get_enabled_rules():
            event = rule.trigger(context)
            if event:
                events.append(event)
        return events

    def clear(self) -> None:
        """Remove all rules."""
        self._rules.clear()


# Predefined rules for common scenarios
def create_default_rules() -> List[Rule]:
    """Create a set of default rules for common scenarios."""
    return [
        Rule.create(
            name="High Resource Scarcity",
            conditions=[
                RuleCondition(
                    field="resource_pressure",
                    operator=ConditionOperator.GT,
                    value=0.8,
                ),
            ],
            action=RuleAction(
                event_type=ExternalEventType.MARKET,
                severity=Severity.HIGH,
                title_template="Resource Shortage Alert",
                content_template="Resource pressure exceeded 80%. Consider intervention.",
            ),
            description="Triggered when resource pressure is critically high.",
        ),
        Rule.create(
            name="Social Tension Warning",
            conditions=[
                RuleCondition(
                    field="social_tension",
                    operator=ConditionOperator.GT,
                    value=0.7,
                ),
            ],
            action=RuleAction(
                event_type=ExternalEventType.NEWS,
                severity=Severity.HIGH,
                title_template="Social Tension Warning",
                content_template="Social tension exceeded 70%. Early intervention recommended.",
            ),
            description="Triggered when social tension is elevated.",
        ),
    ]
