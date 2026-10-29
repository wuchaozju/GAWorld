"""Minimal base action stubs for Pipeline B scenes.

Provides SendMessageAction and YieldAction with NAME/DESC/INSTRUCTION.
See docs/plans/policy-cascade-port-investigation.md

Contains: SendMessageAction, YieldAction
"""

from fos.i18n import T


class SendMessageAction:
    NAME = T("prompts.actions.send_message.name")
    DESC = T("prompts.actions.send_message.desc")
    INSTRUCTION = T("prompts.actions.send_message.instruction")


class YieldAction:
    NAME = T("prompts.actions.yield.name")
    DESC = T("prompts.actions.yield.desc")
    INSTRUCTION = T("prompts.actions.yield.instruction")
