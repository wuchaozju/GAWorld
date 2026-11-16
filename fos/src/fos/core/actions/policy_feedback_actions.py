"""Minimal policy feedback action stubs for Pipeline B scenes.

Provides policy cascade action classes with NAME/DESC/INSTRUCTION.
See docs/plans/policy-cascade-port-investigation.md

Contains: AnnouncePolicyAdjustmentAction, ConsultPeerAction,
    EscalateComplaintAction, NotifySubordinateAction, ReportUpwardAction
"""

from fos.i18n import T


class AnnouncePolicyAdjustmentAction:
    NAME = T("prompts.actions.announce_policy_adjustment.name")
    DESC = T("prompts.actions.announce_policy_adjustment.desc")
    INSTRUCTION = T("prompts.actions.announce_policy_adjustment.instruction")


class ConsultPeerAction:
    NAME = T("prompts.actions.consult_peer.name")
    DESC = T("prompts.actions.consult_peer.desc")
    INSTRUCTION = T("prompts.actions.consult_peer.instruction")


class EscalateComplaintAction:
    NAME = T("prompts.actions.escalate_complaint.name")
    DESC = T("prompts.actions.escalate_complaint.desc")
    INSTRUCTION = T("prompts.actions.escalate_complaint.instruction")


class NotifySubordinateAction:
    NAME = T("prompts.actions.notify_subordinate.name")
    DESC = T("prompts.actions.notify_subordinate.desc")
    INSTRUCTION = T("prompts.actions.notify_subordinate.instruction")


class ReportUpwardAction:
    NAME = T("prompts.actions.report_upward.name")
    DESC = T("prompts.actions.report_upward.desc")
    INSTRUCTION = T("prompts.actions.report_upward.instruction")
