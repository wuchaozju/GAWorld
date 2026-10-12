"""Structured research-to-experiment drafting helpers."""

from __future__ import annotations

import re
from typing import Any

from fos.i18n import T

from .types import TemplateSuggestion


SCENARIO_KEYWORDS: dict[str, list[str]] = {
    "public_goods": [
        "public goods",
        "shared pool",
        "common pool",
        "commons",
        "contribute",
        "keep",
        "endowment",
        "contribution",
        "公共物品",
        "共享池",
        "共同池",
        "贡献",
        "保留",
        "代币",
    ],
    "prisoners_dilemma": [
        "prisoner's dilemma",
        "prisoners dilemma",
        "prisoner’s dilemma",
        "confess",
        "remain silent",
        "betray",
        "defect",
        "cooperate",
        "silent",
        "囚徒困境",
        "背叛",
        "坦白",
        "沉默",
    ],
    "battle_of_the_sexes": [
        "battle of the sexes",
        "coordinate",
        "opera",
        "football",
        "couple",
        "协调",
        "歌剧",
        "足球",
    ],
    "stag_hunt": [
        "stag hunt",
        "stag",
        "hare",
        "hunt",
        "cooperate for the high reward",
        "鹿猎",
        "野兔",
        "狩猎",
    ],
    "coordination_game": [
        "coordination game",
        "coordination failure",
        "minimum effort",
        "effort level",
        "match the same option",
        "choose the same color",
        "协调博弈",
        "协调失败",
        "最小努力",
        "努力水平",
        "匹配相同选项",
    ],
    "policy_erosion": [
        "policy cascade",
        "policy erosion",
        "hierarchy",
        "directive",
        "reinterpret",
        "distort",
        "block the policy",
        "transmit the policy",
        "政策",
        "层级",
        "传递政策",
        "扭曲",
        "阻断",
    ],
    "social_norm_disruption": [
        "social norm",
        "new rule",
        "compliance",
        "resistance",
        "norm violation",
        "规范",
        "新规则",
        "遵从",
        "抵制",
    ],
    "echo_chamber": [
        "echo chamber",
        "polarization",
        "ingroup",
        "outgroup",
        "opinion dynamics",
        "回音室",
        "极化",
        "群内",
        "群外",
        "观点",
    ],
    "resource_scarcity": [
        "resource scarcity",
        "scarcity",
        "hoard",
        "share resources",
        "limited resources",
        "resource shortage",
        "资源稀缺",
        "囤积",
        "分享资源",
    ],
    "open_discussion": [
        "open discussion",
        "free discussion",
        "conversation",
        "debate topic",
        "deliberation",
        "开放讨论",
        "自由讨论",
        "对话",
        "辩论",
    ],
    "council_chamber": [
        "council",
        "proposal",
        "vote",
        "deliberation",
        "abstain",
        "议会",
        "提案",
        "投票",
        "审议",
        "弃权",
    ],
    "contagion": [
        "contagion",
        "infection",
        "infected",
        "susceptible",
        "recovery",
        "spread through the network",
        "behavior spread",
        "social contagion",
        "传染",
        "感染",
        "易感",
        "恢复",
        "传播",
    ],
}


DEFAULT_SCENARIO_ACTIONS: dict[str, list[dict[str, str]]] = {
    "public_goods": [
        {"name": "contribute", "description": T("prompts.actions.ai_scientist.contribute", locale="en")},
        {"name": "keep", "description": T("prompts.actions.ai_scientist.keep", locale="en")},
    ],
    "prisoners_dilemma": [
        {"name": "cooperate", "description": T("prompts.actions.ai_scientist.cooperate", locale="en")},
        {"name": "defect", "description": T("prompts.actions.ai_scientist.defect", locale="en")},
    ],
    "battle_of_the_sexes": [
        {"name": "option_a", "description": T("prompts.actions.ai_scientist.option_a", locale="en")},
        {"name": "option_b", "description": T("prompts.actions.ai_scientist.option_b", locale="en")},
    ],
    "stag_hunt": [
        {"name": "stag", "description": T("prompts.actions.ai_scientist.stag", locale="en")},
        {"name": "hare", "description": T("prompts.actions.ai_scientist.hare", locale="en")},
    ],
    "coordination_game": [
        {"name": "option_a", "description": T("prompts.actions.ai_scientist.option_a", locale="en")},
        {"name": "option_b", "description": T("prompts.actions.ai_scientist.option_b", locale="en")},
    ],
    "policy_erosion": [
        {"name": "transmit_faithfully", "description": T("prompts.actions.ai_scientist.transmit_faithfully", locale="en")},
        {"name": "reinterpret_downward", "description": T("prompts.actions.ai_scientist.reinterpret_downward", locale="en")},
        {"name": "comply_directive", "description": T("prompts.actions.ai_scientist.comply_directive", locale="en")},
        {"name": "resist_quietly", "description": T("prompts.actions.ai_scientist.resist_quietly", locale="en")},
    ],
    "social_norm_disruption": [
        {"name": "comply_publicly", "description": T("prompts.actions.ai_scientist.comply_publicly", locale="en")},
        {"name": "comply_covertly_resist", "description": T("prompts.actions.ai_scientist.comply_covertly_resist", locale="en")},
        {"name": "resist_openly", "description": T("prompts.actions.ai_scientist.resist_openly", locale="en")},
        {"name": "persuade_others", "description": T("prompts.actions.ai_scientist.persuade_others", locale="en")},
    ],
    "echo_chamber": [
        {"name": "express_opinion", "description": T("prompts.actions.ai_scientist.express_opinion", locale="en")},
        {"name": "reinforce_ingroup", "description": T("prompts.actions.ai_scientist.reinforce_ingroup", locale="en")},
        {"name": "challenge_outgroup", "description": T("prompts.actions.ai_scientist.challenge_outgroup", locale="en")},
        {"name": "disengage", "description": T("prompts.actions.ai_scientist.disengage", locale="en")},
    ],
    "resource_scarcity": [
        {"name": "share_resources", "description": T("prompts.actions.ai_scientist.share_resources", locale="en")},
        {"name": "hoard", "description": T("prompts.actions.ai_scientist.hoard", locale="en")},
        {"name": "propose_trade", "description": T("prompts.actions.ai_scientist.propose_trade", locale="en")},
        {"name": "form_contract", "description": T("prompts.actions.ai_scientist.form_contract", locale="en")},
    ],
    "open_discussion": [
        {"name": "speak", "description": T("prompts.actions.ai_scientist.speak", locale="en")},
    ],
    "council_chamber": [
        {"name": "speak", "description": T("prompts.actions.ai_scientist.speak", locale="en")},
        {"name": "vote_yes", "description": T("prompts.actions.ai_scientist.vote_yes", locale="en")},
        {"name": "vote_no", "description": T("prompts.actions.ai_scientist.vote_no", locale="en")},
        {"name": "abstain", "description": T("prompts.actions.ai_scientist.abstain", locale="en")},
    ],
    "contagion": [
        {"name": "move", "description": T("prompts.actions.ai_scientist.move", locale="en")},
        {"name": "speak", "description": T("prompts.actions.ai_scientist.speak", locale="en")},
    ],
}

CUSTOM_STRUCTURE_ACTIONS: dict[str, list[dict[str, str]]] = {
    "proposal_response_exchange": [
        {"name": "propose_split", "description": T("prompts.actions.ai_scientist.propose_split", locale="en")},
        {"name": "approve_split", "description": T("prompts.actions.ai_scientist.approve_split", locale="en")},
        {"name": "reject_split", "description": T("prompts.actions.ai_scientist.reject_split", locale="en")},
    ],
    "competitive_pressure_choice": [
        {"name": "choose_compete", "description": T("prompts.actions.ai_scientist.choose_compete", locale="en")},
        {"name": "choose_yield", "description": T("prompts.actions.ai_scientist.choose_yield", locale="en")},
    ],
    "shared_target_threshold": [
        {"name": "contribute_to_target", "description": T("prompts.actions.ai_scientist.contribute_to_target", locale="en")},
        {"name": "keep_private_reserves", "description": T("prompts.actions.ai_scientist.keep_private_reserves", locale="en")},
        {"name": "delegate_choice", "description": T("prompts.actions.ai_scientist.delegate_choice", locale="en")},
    ],
    "majority_visibility_pressure": [
        {"name": "align_with_visible_majority", "description": T("prompts.actions.ai_scientist.align_with_visible_majority", locale="en")},
        {"name": "state_independent_answer", "description": T("prompts.actions.ai_scientist.state_independent_answer", locale="en")},
    ],
    "threshold_adoption_process": [
        {"name": "adopt_behavior", "description": T("prompts.actions.ai_scientist.adopt_behavior", locale="en")},
        {"name": "wait_for_more_adoption", "description": T("prompts.actions.ai_scientist.wait_for_more_adoption", locale="en")},
    ],
    "escalating_bidding": [
        {"name": "increase_bid", "description": T("prompts.actions.ai_scientist.increase_bid", locale="en")},
        {"name": "exit_bidding", "description": T("prompts.actions.ai_scientist.exit_bidding", locale="en")},
    ],
    "attendance_capacity_avoidance": [
        {"name": "attend", "description": T("prompts.actions.ai_scientist.attend", locale="en")},
        {"name": "stay_away", "description": T("prompts.actions.ai_scientist.stay_away", locale="en")},
    ],
    "minority_side_choice": [
        {"name": "choose_side_a", "description": T("prompts.actions.ai_scientist.choose_side_a", locale="en")},
        {"name": "choose_side_b", "description": T("prompts.actions.ai_scientist.choose_side_b", locale="en")},
    ],
    "common_pool_extraction": [
        {"name": "extract_resource", "description": T("prompts.actions.ai_scientist.extract_resource", locale="en")},
        {"name": "restrain_extraction", "description": T("prompts.actions.ai_scientist.restrain_extraction", locale="en")},
        {"name": "monitor_or_sanction", "description": T("prompts.actions.ai_scientist.monitor_or_sanction", locale="en")},
    ],
    "sanctioning_public_goods": [
        {"name": "contribute_to_public_pool", "description": T("prompts.actions.ai_scientist.contribute_to_public_pool", locale="en")},
        {"name": "withhold_contribution", "description": T("prompts.actions.ai_scientist.withhold_contribution", locale="en")},
        {"name": "punish_free_rider", "description": T("prompts.actions.ai_scientist.punish_free_rider", locale="en")},
    ],
    "spatial_relocation_preference": [
        {"name": "stay_put", "description": T("prompts.actions.ai_scientist.stay_put", locale="en")},
        {"name": "relocate", "description": T("prompts.actions.ai_scientist.relocate", locale="en")},
    ],
    "sequential_information_cascade": [
        {"name": "follow_private_signal", "description": T("prompts.actions.ai_scientist.follow_private_signal", locale="en")},
        {"name": "follow_observed_majority", "description": T("prompts.actions.ai_scientist.follow_observed_majority", locale="en")},
    ],
    "organizational_garbage_can": [
        {"name": "attach_problem", "description": T("prompts.actions.ai_scientist.attach_problem", locale="en")},
        {"name": "attach_solution", "description": T("prompts.actions.ai_scientist.attach_solution", locale="en")},
        {"name": "defer_or_drift", "description": T("prompts.actions.ai_scientist.defer_or_drift", locale="en")},
    ],
    "weighted_opinion_averaging": [
        {"name": "update_belief", "description": T("prompts.actions.ai_scientist.update_belief", locale="en")},
        {"name": "hold_current_belief", "description": T("prompts.actions.ai_scientist.hold_current_belief", locale="en")},
    ],
    "collective_motion_alignment": [
        {"name": "align_heading", "description": T("prompts.actions.ai_scientist.align_heading", locale="en")},
        {"name": "separate_to_avoid_collision", "description": T("prompts.actions.ai_scientist.separate_to_avoid_collision", locale="en")},
        {"name": "cohere_with_group", "description": T("prompts.actions.ai_scientist.cohere_with_group", locale="en")},
    ],
    "resource_search_trade_ecology": [
        {"name": "move_and_harvest", "description": T("prompts.actions.ai_scientist.move_and_harvest", locale="en")},
        {"name": "trade_resources", "description": T("prompts.actions.ai_scientist.trade_resources", locale="en")},
        {"name": "save_or_consume", "description": T("prompts.actions.ai_scientist.save_or_consume", locale="en")},
    ],
    "recruitment_switching": [
        {"name": "stay_with_current_option", "description": T("prompts.actions.ai_scientist.stay_with_current_option", locale="en")},
        {"name": "switch_due_to_recruitment", "description": T("prompts.actions.ai_scientist.switch_due_to_recruitment", locale="en")},
    ],
    "bystander_help_diffusion": [
        {"name": "provide_help", "description": T("prompts.actions.ai_scientist.provide_help", locale="en")},
        {"name": "wait_for_others", "description": T("prompts.actions.ai_scientist.wait_for_others", locale="en")},
    ],
    "authority_obedience_conflict": [
        {"name": "comply_with_order", "description": T("prompts.actions.ai_scientist.comply_with_order", locale="en")},
        {"name": "refuse_order", "description": T("prompts.actions.ai_scientist.refuse_order", locale="en")},
        {"name": "withdraw_from_task", "description": T("prompts.actions.ai_scientist.withdraw_from_task", locale="en")},
    ],
    "intergroup_competition_superordinate_goal": [
        {"name": "cooperate_with_ingroup", "description": T("prompts.actions.ai_scientist.cooperate_with_ingroup", locale="en")},
        {"name": "compete_with_outgroup", "description": T("prompts.actions.ai_scientist.compete_with_outgroup", locale="en")},
        {"name": "cooperate_across_groups", "description": T("prompts.actions.ai_scientist.cooperate_across_groups", locale="en")},
    ],
    "social_comparison_adjustment": [
        {"name": "compare_with_peers", "description": T("prompts.actions.ai_scientist.compare_with_peers", locale="en")},
        {"name": "adjust_self_evaluation", "description": T("prompts.actions.ai_scientist.adjust_self_evaluation", locale="en")},
        {"name": "hold_current_self_view", "description": T("prompts.actions.ai_scientist.hold_current_self_view", locale="en")},
    ],
    "liquidity_run_coordination": [
        {"name": "withdraw_early", "description": T("prompts.actions.ai_scientist.withdraw_early", locale="en")},
        {"name": "keep_deposit", "description": T("prompts.actions.ai_scientist.keep_deposit", locale="en")},
    ],
    "asymmetric_quality_market": [
        {"name": "quote_trade_price", "description": T("prompts.actions.ai_scientist.quote_trade_price", locale="en")},
        {"name": "certify_or_signal_quality", "description": T("prompts.actions.ai_scientist.certify_or_signal_quality", locale="en")},
        {"name": "refuse_trade", "description": T("prompts.actions.ai_scientist.refuse_trade", locale="en")},
    ],
    "adaptive_asset_market": [
        {"name": "forecast_and_trade", "description": T("prompts.actions.ai_scientist.forecast_and_trade", locale="en")},
        {"name": "switch_trading_rule", "description": T("prompts.actions.ai_scientist.switch_trading_rule", locale="en")},
        {"name": "hold_position", "description": T("prompts.actions.ai_scientist.hold_position", locale="en")},
    ],
    "noise_arbitrage_market": [
        {"name": "trade_on_noise_signal", "description": T("prompts.actions.ai_scientist.trade_on_noise_signal", locale="en")},
        {"name": "arbitrage_against_mispricing", "description": T("prompts.actions.ai_scientist.arbitrage_against_mispricing", locale="en")},
        {"name": "reduce_exposure", "description": T("prompts.actions.ai_scientist.reduce_exposure", locale="en")},
    ],
    "insider_market_making": [
        {"name": "submit_informed_order", "description": T("prompts.actions.ai_scientist.submit_informed_order", locale="en")},
        {"name": "submit_noise_order", "description": T("prompts.actions.ai_scientist.submit_noise_order", locale="en")},
        {"name": "update_market_quote", "description": T("prompts.actions.ai_scientist.update_market_quote", locale="en")},
    ],
    "exploration_exploitation_learning": [
        {"name": "explore_new_option", "description": T("prompts.actions.ai_scientist.explore_new_option", locale="en")},
        {"name": "exploit_known_option", "description": T("prompts.actions.ai_scientist.exploit_known_option", locale="en")},
    ],
    "supply_chain_bullwhip": [
        {"name": "place_replenishment_order", "description": T("prompts.actions.ai_scientist.place_replenishment_order", locale="en")},
        {"name": "ship_available_inventory", "description": T("prompts.actions.ai_scientist.ship_available_inventory", locale="en")},
        {"name": "hold_buffer_stock", "description": T("prompts.actions.ai_scientist.hold_buffer_stock", locale="en")},
    ],
    "innovation_diffusion_marketing": [
        {"name": "adopt_product", "description": T("prompts.actions.ai_scientist.adopt_product", locale="en")},
        {"name": "delay_adoption", "description": T("prompts.actions.ai_scientist.delay_adoption", locale="en")},
        {"name": "promote_to_peers", "description": T("prompts.actions.ai_scientist.promote_to_peers", locale="en")},
    ],
    "common_pool_governance": [
        {"name": "harvest_resource", "description": T("prompts.actions.ai_scientist.harvest_resource", locale="en")},
        {"name": "monitor_compliance", "description": T("prompts.actions.ai_scientist.monitor_compliance", locale="en")},
        {"name": "sanction_rule_breaker", "description": T("prompts.actions.ai_scientist.sanction_rule_breaker", locale="en")},
    ],
    "collective_action_free_rider": [
        {"name": "contribute_to_collective_action", "description": T("prompts.actions.ai_scientist.contribute_to_collective_action", locale="en")},
        {"name": "free_ride_on_others", "description": T("prompts.actions.ai_scientist.free_ride_on_others", locale="en")},
        {"name": "offer_selective_incentive", "description": T("prompts.actions.ai_scientist.offer_selective_incentive", locale="en")},
    ],
    "spatial_price_competition": [
        {"name": "choose_market_position", "description": T("prompts.actions.ai_scientist.choose_market_position", locale="en")},
        {"name": "set_price", "description": T("prompts.actions.ai_scientist.set_price", locale="en")},
        {"name": "buy_nearest_offer", "description": T("prompts.actions.ai_scientist.buy_nearest_offer", locale="en")},
    ],
    "reference_dependent_risk_choice": [
        {"name": "choose_safe_option", "description": T("prompts.actions.ai_scientist.choose_safe_option", locale="en")},
        {"name": "choose_risky_option", "description": T("prompts.actions.ai_scientist.choose_risky_option", locale="en")},
    ],
    "endowment_statusquo_exchange": [
        {"name": "keep_endowed_item", "description": T("prompts.actions.ai_scientist.keep_endowed_item", locale="en")},
        {"name": "offer_exchange", "description": T("prompts.actions.ai_scientist.offer_exchange", locale="en")},
    ],
}


STOPWORDS = {
    "the", "and", "that", "with", "from", "this", "these", "those", "their",
    "while", "between", "which", "participants", "subject", "study", "paper",
    "research", "method", "methods", "result", "results", "using", "based",
    "into", "through", "where", "when", "what", "were", "have", "has", "had",
    "will", "would", "could", "should", "into", "than", "then", "they", "them",
}

CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

NOISE_SECTION_TITLES = {
    "references",
    "reference",
    "bibliography",
    "appendix",
    "appendices",
    "acknowledgments",
    "acknowledgements",
    "glossary",
    "essay study questions",
    "study questions",
    "keywords",
}

SECTION_PRIORITY_WEIGHTS = {
    "title": 2.4,
    "abstract": 2.0,
    "摘要": 2.0,
    "introduction": 1.2,
    "引言": 1.2,
    "background": 1.3,
    "背景设定": 1.3,
    "methods": 1.8,
    "method": 1.8,
    "methodology": 1.8,
    "materials and methods": 1.8,
    "方法": 1.8,
    "results": 0.9,
    "结果": 0.9,
    "discussion": 0.8,
    "讨论": 0.8,
    "conclusion": 0.7,
    "结论": 0.7,
    "excerpt": 0.8,
}

SCENARIO_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "public_goods": {
        "aliases": ["public goods", "public goods game", "共同池", "公共物品"],
        "roles": ["participants", "players", "group members", "subjects"],
        "actions": ["contribute", "keep", "private account", "shared pool", "common pool"],
        "payoffs": ["multiplier", "distributed equally", "endowment", "punishment points"],
        "mechanisms": ["anonymous", "repeated rounds", "shared account", "public account"],
    },
    "prisoners_dilemma": {
        "aliases": ["prisoner's dilemma", "prisoners dilemma", "prisoner’s dilemma", "囚徒困境"],
        "roles": ["two players", "pairs of participants", "suspects"],
        "actions": ["cooperate", "defect", "betray", "remain silent", "confess", "matrix game"],
        "payoffs": ["mutual cooperation", "mutual defection", "incentive to defect", "joint decision"],
        "mechanisms": ["pairwise", "without knowing the partner's current move", "repeated interaction"],
    },
    "coordination_game": {
        "aliases": ["coordination game", "minimum effort", "tacit coordination", "协调博弈"],
        "roles": ["participants", "players", "neighbors"],
        "actions": ["choose one effort level", "match", "same option", "shared menu"],
        "payoffs": ["higher payoffs when choices matched", "coordination failure"],
        "mechanisms": ["small groups", "repeated choices", "strategic uncertainty"],
    },
    "contagion": {
        "aliases": ["contagion", "spread of behavior", "social contagion", "传染"],
        "roles": ["participants", "neighbors", "contacts", "susceptible", "infected"],
        "actions": ["adopt", "move", "speak", "exposed", "infected"],
        "payoffs": ["cumulative adoption", "infection", "recovery"],
        "mechanisms": ["local network", "repeated local exposure", "behavior spreads", "online social network"],
    },
}

SCENARIO_STRUCTURE_HINTS: dict[str, str] = {
    "public_goods": "threshold_public_good_collective_target",
    "prisoners_dilemma": "dyadic_cooperate_defect",
    "coordination_game": "coordination_matching",
    "contagion": "contagion_spread",
}

STRUCTURE_FAMILY_MAP: dict[str, str] = {
    "proposal_response_exchange": "dyadic_bargaining",
    "competitive_pressure_choice": "conflict_anti_coordination",
    "shared_target_threshold": "threshold_public_good_collective_target",
    "sanctioning_public_goods": "threshold_public_good_collective_target",
    "common_pool_extraction": "common_pool_resource_dilemma",
    "majority_visibility_pressure": "social_influence_conformity",
    "threshold_adoption_process": "diffusion_adoption_cascade",
    "sequential_information_cascade": "sequential_social_learning",
    "attendance_capacity_avoidance": "attendance_capacity_avoidance",
    "minority_side_choice": "attendance_capacity_avoidance",
    "escalating_bidding": "auction_escalation",
    "dyadic_cooperate_defect": "dyadic_cooperate_defect",
    "coordination_matching": "coordination_matching",
    "contagion_spread": "contagion_spread",
    "spatial_relocation_preference": "spatial_relocation_preference",
    "organizational_garbage_can": "organizational_choice_streams",
    "weighted_opinion_averaging": "opinion_averaging_consensus",
    "collective_motion_alignment": "collective_motion_alignment",
    "resource_search_trade_ecology": "resource_search_trade_ecology",
    "recruitment_switching": "recruitment_switching",
    "bystander_help_diffusion": "emergency_help_diffusion",
    "authority_obedience_conflict": "authority_obedience_conflict",
    "intergroup_competition_superordinate_goal": "intergroup_competition_superordinate_goal",
    "social_comparison_adjustment": "social_comparison_adjustment",
    "liquidity_run_coordination": "bank_run_liquidity_coordination",
    "asymmetric_quality_market": "asymmetric_information_market",
    "adaptive_asset_market": "adaptive_financial_market",
    "noise_arbitrage_market": "adaptive_financial_market",
    "insider_market_making": "market_microstructure_informed_trading",
    "exploration_exploitation_learning": "exploration_exploitation_learning",
    "supply_chain_bullwhip": "supply_chain_bullwhip",
    "innovation_diffusion_marketing": "innovation_diffusion_marketing",
    "common_pool_governance": "common_pool_resource_dilemma",
    "collective_action_free_rider": "collective_action_free_rider",
    "spatial_price_competition": "spatial_competition",
    "reference_dependent_risk_choice": "reference_dependent_choice",
    "endowment_statusquo_exchange": "endowment_statusquo_exchange",
    "operational_coordination": "open_ended_custom",
    "generic": "open_ended_custom",
}

STRUCTURE_DISPLAY_TEXTS: dict[str, dict[str, str]] = {
    "dyadic_bargaining": {"en": "Dyadic bargaining", "zh": "双边议价"},
    "conflict_anti_coordination": {"en": "Conflict / anti-coordination", "zh": "冲突 / 反协调"},
    "threshold_public_good_collective_target": {"en": "Threshold public good / collective target", "zh": "阈值型公共物品 / 集体目标"},
    "social_influence_conformity": {"en": "Social influence / conformity", "zh": "社会影响 / 从众"},
    "diffusion_adoption_cascade": {"en": "Diffusion / adoption cascade", "zh": "扩散 / 采纳级联"},
    "sequential_social_learning": {"en": "Sequential information cascade", "zh": "顺序信息级联"},
    "attendance_capacity_avoidance": {"en": "Attendance / minority avoidance", "zh": "出席拥挤规避 / 少数派选择"},
    "common_pool_resource_dilemma": {"en": "Common-pool resource dilemma", "zh": "公共资源困境"},
    "auction_escalation": {"en": "Auction / escalation", "zh": "拍卖 / 升级"},
    "dyadic_cooperate_defect": {"en": "Cooperate-defect dilemma", "zh": "合作-背叛困境"},
    "coordination_matching": {"en": "Coordination / matching", "zh": "协调 / 匹配"},
    "contagion_spread": {"en": "Contagion / spread", "zh": "传染 / 传播"},
    "spatial_relocation_preference": {"en": "Spatial relocation under local preference", "zh": "局部偏好下的空间搬迁"},
    "organizational_choice_streams": {"en": "Organizational garbage-can choice", "zh": "组织垃圾桶式决策"},
    "opinion_averaging_consensus": {"en": "Opinion averaging / consensus", "zh": "意见平均 / 共识形成"},
    "collective_motion_alignment": {"en": "Collective motion / local alignment", "zh": "群体运动 / 局部对齐"},
    "resource_search_trade_ecology": {"en": "Resource search / trade ecology", "zh": "资源搜索 / 交易生态"},
    "recruitment_switching": {"en": "Recruitment switching", "zh": "招募切换"},
    "emergency_help_diffusion": {"en": "Bystander help / responsibility diffusion", "zh": "旁观援助 / 责任扩散"},
    "authority_obedience_conflict": {"en": "Authority obedience / moral conflict", "zh": "权威服从 / 道德冲突"},
    "intergroup_competition_superordinate_goal": {"en": "Intergroup competition / superordinate goal", "zh": "群际竞争 / 超级目标"},
    "social_comparison_adjustment": {"en": "Social comparison / self-adjustment", "zh": "社会比较 / 自我调整"},
    "bank_run_liquidity_coordination": {"en": "Bank run / liquidity coordination", "zh": "银行挤兑 / 流动性协调"},
    "asymmetric_information_market": {"en": "Asymmetric-information market", "zh": "信息不对称市场"},
    "adaptive_financial_market": {"en": "Adaptive heterogeneous asset market", "zh": "自适应异质资产市场"},
    "market_microstructure_informed_trading": {"en": "Informed trading / market making", "zh": "知情交易 / 做市"},
    "exploration_exploitation_learning": {"en": "Exploration / exploitation learning", "zh": "探索 / 利用学习"},
    "supply_chain_bullwhip": {"en": "Supply-chain bullwhip", "zh": "供应链牛鞭效应"},
    "innovation_diffusion_marketing": {"en": "Innovation diffusion / market adoption", "zh": "创新扩散 / 市场采纳"},
    "collective_action_free_rider": {"en": "Collective action / free-rider dilemma", "zh": "集体行动 / 搭便车困境"},
    "spatial_competition": {"en": "Spatial competition", "zh": "空间竞争"},
    "reference_dependent_choice": {"en": "Reference-dependent risk choice", "zh": "参照依赖风险选择"},
    "endowment_statusquo_exchange": {"en": "Endowment / status quo exchange", "zh": "禀赋 / 现状偏好交易"},
    "open_ended_custom": {"en": "Open-ended custom", "zh": "开放式自定义"},
}

CUSTOM_ACTION_LIBRARY: list[dict[str, Any]] = [
    {
        "name": "share_status_update",
        "description": T("prompts.actions.ai_scientist_custom.share_status_update", locale="en"),
        "patterns": [r"状态同步", r"广播", r"共享内存", r"共享", r"告知", r"回复", r"同步更新", r"notify", r"share", r"broadcast", r"update"],
    },
    {
        "name": "reroute_traffic",
        "description": T("prompts.actions.ai_scientist_custom.reroute_traffic", locale="en"),
        "patterns": [r"重定向", r"绕行", r"引导", r"疏导", r"开放应急车道", r"route", r"reroute", r"redirect", r"traffic"],
    },
    {
        "name": "request_signal_priority",
        "description": T("prompts.actions.ai_scientist_custom.request_signal_priority", locale="en"),
        "patterns": [r"信号灯", r"信号优先", r"绿灯", r"配时", r"绿色通道", r"priority", r"signal", r"green corridor"],
    },
    {
        "name": "dispatch_response_resources",
        "description": T("prompts.actions.ai_scientist_custom.dispatch_response_resources", locale="en"),
        "patterns": [r"救护车", r"消防车", r"警车", r"调度", r"出发", r"dispatch", r"resource", r"rescue"],
    },
    {
        "name": "inspect_hazard_zone",
        "description": T("prompts.actions.ai_scientist_custom.inspect_hazard_zone", locale="en"),
        "patterns": [r"侦察", r"热成像", r"气体传感器", r"确认", r"扫描", r"三维环境模型", r"inspect", r"scan", r"sensor"],
    },
    {
        "name": "establish_safety_perimeter",
        "description": T("prompts.actions.ai_scientist_custom.establish_safety_perimeter", locale="en"),
        "patterns": [r"路障", r"隔离区", r"封锁", r"扩大隔离区", r"isolation", r"barrier", r"perimeter", r"blockade"],
    },
    {
        "name": "mitigate_hazard",
        "description": T("prompts.actions.ai_scientist_custom.mitigate_hazard", locale="en"),
        "patterns": [r"吸附", r"处置", r"泄漏", r"危险源", r"mitigate", r"contain", r"leak"],
    },
    {
        "name": "broadcast_public_guidance",
        "description": T("prompts.actions.ai_scientist_custom.broadcast_public_guidance", locale="en"),
        "patterns": [r"导航", r"电子屏", r"社交媒体", r"推送", r"个性化绕行", r"关闭门窗", r"public", r"guidance", r"alert"],
    },
    {
        "name": "replan_strategy",
        "description": T("prompts.actions.ai_scientist_custom.replan_strategy", locale="en"),
        "patterns": [r"调整", r"修正", r"升级", r"反馈循环", r"监测用户是否采纳", r"adaptive", r"replan", r"adjust"],
    },
]

CUSTOM_ACTION_DISPLAY_NAMES = {
    "share_status_update": "状态同步",
    "reroute_traffic": "交通重定向",
    "request_signal_priority": "信号优先请求",
    "dispatch_response_resources": "应急资源调度",
    "inspect_hazard_zone": "危险区勘测",
    "establish_safety_perimeter": "建立隔离区",
    "mitigate_hazard": "危险源处置",
    "broadcast_public_guidance": "公众信息引导",
    "replan_strategy": "动态重规划",
}

LOCALIZED_ACTION_TEXTS: dict[str, dict[str, str]] = {
    "contribute": {"en_label": "Contribute", "en_description": "Contribute some of your resources to the shared pool.", "zh_label": "贡献到公共池", "zh_description": "将一部分资源投入共享池。"},
    "keep": {"en_label": "Keep", "en_description": "Keep your resources for yourself.", "zh_label": "保留资源", "zh_description": "将资源保留给自己。"},
    "cooperate": {"en_label": "Cooperate", "en_description": "Choose the cooperative option.", "zh_label": "合作", "zh_description": "选择合作选项。"},
    "defect": {"en_label": "Defect", "en_description": "Choose the self-interested option.", "zh_label": "背叛", "zh_description": "选择更自利的选项。"},
    "propose_split": {"en_label": "Propose split", "en_description": "Propose how to divide the available resource.", "zh_label": "提出分配方案", "zh_description": "提出如何分配可用资源。"},
    "approve_split": {"en_label": "Approve split", "en_description": "Approve the proposed split.", "zh_label": "接受方案", "zh_description": "接受当前提出的分配方案。"},
    "reject_split": {"en_label": "Reject split", "en_description": "Reject the proposed split and block the allocation.", "zh_label": "拒绝方案", "zh_description": "拒绝当前方案，使其无法生效。"},
    "choose_compete": {"en_label": "Choose compete", "en_description": "Choose the more competitive strategy.", "zh_label": "选择竞争策略", "zh_description": "选择更激进或更有竞争性的策略。"},
    "choose_yield": {"en_label": "Choose yield", "en_description": "Choose the more yielding strategy.", "zh_label": "选择退让策略", "zh_description": "选择更克制或更退让的策略。"},
    "option_a": {"en_label": "Option A", "en_description": "Choose the first focal option.", "zh_label": "选项 A", "zh_description": "选择第一个焦点选项。"},
    "option_b": {"en_label": "Option B", "en_description": "Choose the second focal option.", "zh_label": "选项 B", "zh_description": "选择第二个焦点选项。"},
    "stag": {"en_label": "Stag", "en_description": "Choose the risky but high-payoff cooperative option.", "zh_label": "猎鹿", "zh_description": "选择高收益但需要协作的冒险选项。"},
    "hare": {"en_label": "Hare", "en_description": "Choose the safer but lower-payoff option.", "zh_label": "逐兔", "zh_description": "选择更稳妥但收益较低的选项。"},
    "speak": {"en_label": "Speak", "en_description": "Say something to the group.", "zh_label": "发言", "zh_description": "向其他参与者表达观点或信息。"},
    "vote_yes": {"en_label": "Vote Yes", "en_description": "Vote in favor of the proposal.", "zh_label": "投赞成票", "zh_description": "对提案投赞成票。"},
    "vote_no": {"en_label": "Vote No", "en_description": "Vote against the proposal.", "zh_label": "投反对票", "zh_description": "对提案投反对票。"},
    "abstain": {"en_label": "Abstain", "en_description": "Neither vote yes nor no.", "zh_label": "弃权", "zh_description": "不投赞成也不投反对。"},
    "move": {"en_label": "Move", "en_description": "Move to a nearby location.", "zh_label": "移动", "zh_description": "移动到邻近位置。"},
    "share_resources": {"en_label": "Share resources", "en_description": "Share some resources with others.", "zh_label": "分享资源", "zh_description": "与其他人分享一部分资源。"},
    "hoard": {"en_label": "Hoard", "en_description": "Keep resources for yourself.", "zh_label": "囤积资源", "zh_description": "将资源优先保留给自己。"},
    "propose_trade": {"en_label": "Propose trade", "en_description": "Offer a trade or exchange.", "zh_label": "提出交换", "zh_description": "提出交易或交换建议。"},
    "form_contract": {"en_label": "Form contract", "en_description": "Propose a cooperative agreement.", "zh_label": "建立合作协议", "zh_description": "提出合作协议或共同安排。"},
    "express_opinion": {"en_label": "Express opinion", "en_description": "Share your current view.", "zh_label": "表达观点", "zh_description": "表达当前的立场或看法。"},
    "reinforce_ingroup": {"en_label": "Reinforce ingroup", "en_description": "Amplify similar views within your group.", "zh_label": "强化群内立场", "zh_description": "在本群体内部强化相近观点。"},
    "challenge_outgroup": {"en_label": "Challenge outgroup", "en_description": "Challenge opposing views.", "zh_label": "质疑外群体", "zh_description": "质疑对立群体或相反观点。"},
    "disengage": {"en_label": "Disengage", "en_description": "Withdraw from engagement.", "zh_label": "退出互动", "zh_description": "减少或退出当前互动。"},
    "transmit_faithfully": {"en_label": "Transmit faithfully", "en_description": "Pass the directive on exactly as received.", "zh_label": "如实传达", "zh_description": "按原样向下传达指令。"},
    "reinterpret_downward": {"en_label": "Reinterpret downward", "en_description": "Modify the directive while passing it down.", "zh_label": "下传时重释", "zh_description": "在向下传递时调整或重释指令。"},
    "comply_directive": {"en_label": "Comply with directive", "en_description": "Implement the directive as instructed.", "zh_label": "执行指令", "zh_description": "按照要求执行指令。"},
    "resist_quietly": {"en_label": "Resist quietly", "en_description": "Appear compliant while resisting in practice.", "zh_label": "表面服从", "zh_description": "表面上服从，但实际中进行抵制。"},
    "align_with_visible_majority": {"en_label": "Align with majority", "en_description": "Publicly align with the visible majority position.", "zh_label": "从众作答", "zh_description": "公开给出与多数一致的判断。"},
    "state_independent_answer": {"en_label": "State independent answer", "en_description": "State an independent answer even if it differs from the majority.", "zh_label": "坚持独立判断", "zh_description": "即使与多数不同，也坚持给出独立判断。"},
    "adopt_behavior": {"en_label": "Adopt behavior", "en_description": "Adopt the behavior once enough others already have.", "zh_label": "采纳行为", "zh_description": "当周围已有足够多人行动后采纳该行为。"},
    "wait_for_more_adoption": {"en_label": "Wait for more adoption", "en_description": "Wait for additional adoption before joining.", "zh_label": "继续观望", "zh_description": "暂不加入，等待更多他人先行动。"},
    "delegate_choice": {"en_label": "Delegate choice", "en_description": "Delegate the decision to another actor or automated process.", "zh_label": "委托决策", "zh_description": "将决策委托给其他角色或自动化过程。"},
    "contribute_to_target": {"en_label": "Contribute to target", "en_description": "Contribute resources toward the shared target.", "zh_label": "贡献到共同目标", "zh_description": "将资源投入共同目标。"},
    "keep_private_reserves": {"en_label": "Keep private reserves", "en_description": "Keep resources for private use.", "zh_label": "保留私人资源", "zh_description": "将资源保留给自己。"},
    "share_status_update": {"en_label": "Share status update", "en_description": "Share incident status, state changes, or coordination updates with other agents.", "zh_label": "状态同步", "zh_description": "向其他智能体共享事件状态、变化信息或协调更新。"},
    "reroute_traffic": {"en_label": "Reroute traffic", "en_description": "Reroute traffic flow away from the incident area and toward fallback corridors.", "zh_label": "交通重定向", "zh_description": "将交通流从事故区域重新引导到备用通道。"},
    "request_signal_priority": {"en_label": "Request signal priority", "en_description": "Request signal timing changes or priority access for emergency movement.", "zh_label": "信号优先请求", "zh_description": "请求调整信号配时或为应急通行开辟优先通道。"},
    "dispatch_response_resources": {"en_label": "Dispatch response resources", "en_description": "Dispatch or reallocate emergency resources based on updated incident conditions.", "zh_label": "应急资源调度", "zh_description": "根据事故变化调度或重新分配应急资源。"},
    "inspect_hazard_zone": {"en_label": "Inspect hazard zone", "en_description": "Inspect, scan, or model the incident zone to assess hazards.", "zh_label": "危险区勘测", "zh_description": "勘测、扫描或建模事故区域以评估风险。"},
    "establish_safety_perimeter": {"en_label": "Establish safety perimeter", "en_description": "Deploy barriers or expand isolation zones to protect people and infrastructure.", "zh_label": "建立隔离区", "zh_description": "部署路障或扩大隔离带以保护人员和设施。"},
    "mitigate_hazard": {"en_label": "Mitigate hazard", "en_description": "Contain, absorb, or otherwise mitigate the hazardous material release.", "zh_label": "危险源处置", "zh_description": "控制、吸附或以其他方式减轻危险物泄漏。"},
    "broadcast_public_guidance": {"en_label": "Broadcast public guidance", "en_description": "Push public guidance, route advice, or safety warnings to affected users.", "zh_label": "公众信息引导", "zh_description": "向受影响人群推送绕行建议或安全提醒。"},
    "replan_strategy": {"en_label": "Replan strategy", "en_description": "Replan actions when conditions change, feedback arrives, or hazard levels escalate.", "zh_label": "动态重规划", "zh_description": "在条件变化、收到反馈或风险升级时重新规划行动。"},
    "increase_bid": {"en_label": "Increase bid", "en_description": "Increase the current bid to remain competitive or reduce losses.", "zh_label": "继续加价", "zh_description": "提高当前出价，以保持竞争地位或减少损失。"},
    "exit_bidding": {"en_label": "Exit bidding", "en_description": "Withdraw from further bidding and accept the current payoff or loss.", "zh_label": "停止竞价", "zh_description": "停止继续出价，并接受当前收益或损失。"},
    "attend": {"en_label": "Attend", "en_description": "Go to the venue, bar, or shared site this round.", "zh_label": "前往参与", "zh_description": "本轮前往酒吧、会场或共享地点。"},
    "stay_away": {"en_label": "Stay away", "en_description": "Stay away this round to avoid overcrowding.", "zh_label": "暂不前往", "zh_description": "本轮不前往，以避免拥挤。"},
    "choose_side_a": {"en_label": "Choose side A", "en_description": "Choose the first side, market direction, or venue.", "zh_label": "选择 A 侧", "zh_description": "选择第一个方向、场所或一侧。"},
    "choose_side_b": {"en_label": "Choose side B", "en_description": "Choose the second side, market direction, or venue.", "zh_label": "选择 B 侧", "zh_description": "选择第二个方向、场所或一侧。"},
    "extract_resource": {"en_label": "Extract resource", "en_description": "Take some amount from the common finite resource pool.", "zh_label": "提取资源", "zh_description": "从共享的有限资源池中提取资源。"},
    "restrain_extraction": {"en_label": "Restrain extraction", "en_description": "Limit extraction to preserve the resource stock.", "zh_label": "克制提取", "zh_description": "限制提取量以保全资源存量。"},
    "monitor_or_sanction": {"en_label": "Monitor or sanction", "en_description": "Monitor usage or sanction over-extraction.", "zh_label": "监督或惩罚", "zh_description": "监督资源使用或惩罚过度提取。"},
    "contribute_to_public_pool": {"en_label": "Contribute to public pool", "en_description": "Contribute resources to the public pool.", "zh_label": "投入公共池", "zh_description": "向公共池投入资源。"},
    "withhold_contribution": {"en_label": "Withhold contribution", "en_description": "Keep resources instead of contributing to the pool.", "zh_label": "拒绝投入", "zh_description": "保留资源而不投入公共池。"},
    "punish_free_rider": {"en_label": "Punish free rider", "en_description": "Spend resources to punish a free rider after contributions are observed.", "zh_label": "惩罚搭便车者", "zh_description": "在观察到贡献后付出成本惩罚搭便车者。"},
    "stay_put": {"en_label": "Stay put", "en_description": "Stay in the current location if the neighborhood is acceptable.", "zh_label": "留在原地", "zh_description": "如果邻域可接受，则留在当前位置。"},
    "relocate": {"en_label": "Relocate", "en_description": "Move to a new empty location when the local neighborhood is unsatisfactory.", "zh_label": "搬迁", "zh_description": "当局部邻域不满意时搬到新的空位置。"},
    "follow_private_signal": {"en_label": "Follow private signal", "en_description": "Choose according to the private signal.", "zh_label": "依据私人信号", "zh_description": "根据自己的私人信号做选择。"},
    "follow_observed_majority": {"en_label": "Follow observed majority", "en_description": "Ignore the private signal and follow earlier public choices.", "zh_label": "跟随前人选择", "zh_description": "忽略私人信号，跟随前面公开的选择。"},
    "attach_problem": {"en_label": "Attach problem", "en_description": "Attach a waiting problem to the current choice opportunity.", "zh_label": "挂接问题", "zh_description": "将当前问题挂接到可用的选择机会。"},
    "attach_solution": {"en_label": "Attach solution", "en_description": "Push an available solution into the current choice opportunity.", "zh_label": "挂接方案", "zh_description": "将现有方案推入当前选择机会。"},
    "defer_or_drift": {"en_label": "Defer or drift", "en_description": "Let the issue drift unresolved until another opportunity appears.", "zh_label": "延期或漂移", "zh_description": "暂不解决，让问题漂移到后续机会窗口。"},
    "update_belief": {"en_label": "Update belief", "en_description": "Update the current belief using neighbors' weighted opinions.", "zh_label": "更新观点", "zh_description": "根据邻居观点的加权平均更新自身观点。"},
    "hold_current_belief": {"en_label": "Hold current belief", "en_description": "Keep the current belief unchanged this round.", "zh_label": "保持原观点", "zh_description": "本轮保持当前观点不变。"},
    "align_heading": {"en_label": "Align heading", "en_description": "Adjust direction toward the average local heading.", "zh_label": "对齐方向", "zh_description": "将运动方向调整为邻域平均方向。"},
    "separate_to_avoid_collision": {"en_label": "Separate to avoid collision", "en_description": "Move away slightly to avoid collisions.", "zh_label": "避碰分离", "zh_description": "略微远离邻居以避免碰撞。"},
    "cohere_with_group": {"en_label": "Cohere with group", "en_description": "Move toward the nearby group center.", "zh_label": "靠拢群体", "zh_description": "向局部群体中心靠近。"},
    "move_and_harvest": {"en_label": "Move and harvest", "en_description": "Move through space and harvest local resources.", "zh_label": "移动并采集", "zh_description": "在空间中移动并采集局部资源。"},
    "trade_resources": {"en_label": "Trade resources", "en_description": "Trade resources with another nearby agent.", "zh_label": "交易资源", "zh_description": "与附近其他智能体进行资源交易。"},
    "save_or_consume": {"en_label": "Save or consume", "en_description": "Decide whether to save, consume, or invest current resources.", "zh_label": "储存或消耗", "zh_description": "决定储存、消耗或投资当前资源。"},
    "stay_with_current_option": {"en_label": "Stay with current option", "en_description": "Remain with the current source, restaurant, or market side.", "zh_label": "留在当前选项", "zh_description": "继续停留在当前食源、餐厅或市场一侧。"},
    "switch_due_to_recruitment": {"en_label": "Switch due to recruitment", "en_description": "Switch to the other option because of recruitment or random exploration.", "zh_label": "受招募影响切换", "zh_description": "由于同伴招募或随机探索而切换到另一选项。"},
    "provide_help": {"en_label": "Provide help", "en_description": "Step in to provide help during the emergency or urgent event.", "zh_label": "提供帮助", "zh_description": "在紧急事件中主动出手提供帮助。"},
    "wait_for_others": {"en_label": "Wait for others", "en_description": "Wait because someone else may intervene first or the situation is ambiguous.", "zh_label": "等待他人行动", "zh_description": "因他人可能先行动或局势含混而暂时观望。"},
    "comply_with_order": {"en_label": "Comply with order", "en_description": "Comply with the authority's instruction despite discomfort.", "zh_label": "服从命令", "zh_description": "即使感到不适也继续服从权威指令。"},
    "refuse_order": {"en_label": "Refuse order", "en_description": "Refuse to continue once the moral or perceived risk threshold is crossed.", "zh_label": "拒绝命令", "zh_description": "在道德或风险阈值被触发后拒绝继续执行。"},
    "withdraw_from_task": {"en_label": "Withdraw from task", "en_description": "Exit the task entirely instead of continuing under authority pressure.", "zh_label": "退出任务", "zh_description": "不再继续任务，直接退出当前安排。"},
    "cooperate_with_ingroup": {"en_label": "Cooperate with ingroup", "en_description": "Strengthen coordination and identity within the local group.", "zh_label": "组内合作", "zh_description": "加强本组内部的协作与身份认同。"},
    "compete_with_outgroup": {"en_label": "Compete with outgroup", "en_description": "Compete with the rival group over scarce rewards or status.", "zh_label": "与外群体竞争", "zh_description": "围绕稀缺奖励或地位与外群体竞争。"},
    "cooperate_across_groups": {"en_label": "Cooperate across groups", "en_description": "Coordinate across group boundaries to achieve a superordinate goal.", "zh_label": "跨群体合作", "zh_description": "为了共同的超级目标开展跨群体合作。"},
    "compare_with_peers": {"en_label": "Compare with peers", "en_description": "Compare current opinion, performance, or status with similar peers.", "zh_label": "与同伴比较", "zh_description": "将当前观点、表现或地位与相似同伴进行比较。"},
    "adjust_self_evaluation": {"en_label": "Adjust self-evaluation", "en_description": "Adjust self-evaluation, confidence, or opinion after comparison.", "zh_label": "调整自我评价", "zh_description": "在比较后调整自我评价、自信或观点。"},
    "hold_current_self_view": {"en_label": "Hold current self-view", "en_description": "Maintain the current self-view despite comparison pressure.", "zh_label": "保持当前自我判断", "zh_description": "在比较压力下仍维持当前自我判断。"},
    "withdraw_early": {"en_label": "Withdraw early", "en_description": "Withdraw the deposit or claim liquidity before others do.", "zh_label": "提前取款", "zh_description": "在他人之前提取存款或流动性。"},
    "keep_deposit": {"en_label": "Keep deposit", "en_description": "Leave the deposit in place and continue holding the claim.", "zh_label": "继续持有存款", "zh_description": "继续持有存款，不提前提取。"},
    "quote_trade_price": {"en_label": "Quote trade price", "en_description": "Offer or accept a price under uncertain product quality.", "zh_label": "报价交易", "zh_description": "在质量不确定的情况下给出或接受价格。"},
    "certify_or_signal_quality": {"en_label": "Certify or signal quality", "en_description": "Use reputation, warranty, or certification to signal quality.", "zh_label": "认证或传递质量信号", "zh_description": "通过声誉、保修或认证传递质量信息。"},
    "refuse_trade": {"en_label": "Refuse trade", "en_description": "Walk away from the trade when quality is too uncertain.", "zh_label": "拒绝交易", "zh_description": "当质量信息过于不确定时拒绝交易。"},
    "forecast_and_trade": {"en_label": "Forecast and trade", "en_description": "Forecast the next price and trade using the current strategy.", "zh_label": "预测并交易", "zh_description": "根据当前策略预测价格并进行交易。"},
    "switch_trading_rule": {"en_label": "Switch trading rule", "en_description": "Switch to a different forecasting or trading rule after poor performance.", "zh_label": "切换交易规则", "zh_description": "在表现不佳后切换预测或交易规则。"},
    "hold_position": {"en_label": "Hold position", "en_description": "Keep the current position or stay out of the market this round.", "zh_label": "保持仓位", "zh_description": "本轮保持当前仓位或暂不交易。"},
    "trade_on_noise_signal": {"en_label": "Trade on noise signal", "en_description": "Trade on sentiment, rumor, or another noisy directional signal.", "zh_label": "根据信噪交易", "zh_description": "依据情绪、传闻或其他噪声信号交易。"},
    "arbitrage_against_mispricing": {"en_label": "Arbitrage against mispricing", "en_description": "Trade against perceived deviations from fundamental value.", "zh_label": "逆向套利纠偏", "zh_description": "针对偏离基本面的价格进行逆向套利。"},
    "reduce_exposure": {"en_label": "Reduce exposure", "en_description": "Reduce exposure when funding risk or crowd pressure becomes too high.", "zh_label": "降低敞口", "zh_description": "当资金风险或群体压力过高时降低头寸敞口。"},
    "submit_informed_order": {"en_label": "Submit informed order", "en_description": "Place an informed order without revealing private information too quickly.", "zh_label": "提交知情订单", "zh_description": "在不过快暴露私有信息的情况下提交知情订单。"},
    "submit_noise_order": {"en_label": "Submit noise order", "en_description": "Submit an uninformed or random order.", "zh_label": "提交噪声订单", "zh_description": "提交随机或无信息优势的订单。"},
    "update_market_quote": {"en_label": "Update market quote", "en_description": "Update the market quote from incoming order flow.", "zh_label": "更新做市报价", "zh_description": "根据订单流变化更新做市报价。"},
    "explore_new_option": {"en_label": "Explore new option", "en_description": "Try an uncertain new option with possible long-run upside.", "zh_label": "探索新方案", "zh_description": "尝试不确定但可能带来长期收益的新方案。"},
    "exploit_known_option": {"en_label": "Exploit known option", "en_description": "Use a reliable existing option with stable short-run returns.", "zh_label": "利用现有方案", "zh_description": "使用已有且短期稳定的方案。"},
    "place_replenishment_order": {"en_label": "Place replenishment order", "en_description": "Place a replenishment order based on local inventory and visible demand.", "zh_label": "下达补货订单", "zh_description": "根据本地库存和可见需求下达补货订单。"},
    "ship_available_inventory": {"en_label": "Ship available inventory", "en_description": "Ship available stock to the next downstream node.", "zh_label": "发运现有库存", "zh_description": "将现有库存发往下游节点。"},
    "hold_buffer_stock": {"en_label": "Hold buffer stock", "en_description": "Adjust safety stock buffers to manage delay and uncertainty.", "zh_label": "保留缓冲库存", "zh_description": "调整安全库存以应对延迟和不确定性。"},
    "adopt_product": {"en_label": "Adopt product", "en_description": "Adopt or purchase the innovation in the current period.", "zh_label": "采纳产品", "zh_description": "在当前时期采纳或购买该创新产品。"},
    "delay_adoption": {"en_label": "Delay adoption", "en_description": "Wait for more information or social proof before adopting.", "zh_label": "延迟采纳", "zh_description": "在获得更多信息或社会证明前暂缓采纳。"},
    "promote_to_peers": {"en_label": "Promote to peers", "en_description": "Transmit adoption information through word of mouth or visible usage.", "zh_label": "向同伴传播", "zh_description": "通过口碑或可见使用向同伴传播采纳信息。"},
    "harvest_resource": {"en_label": "Harvest resource", "en_description": "Harvest from the common resource under the current local rules.", "zh_label": "采集资源", "zh_description": "在当前本地规则下从公共资源中采集。"},
    "monitor_compliance": {"en_label": "Monitor compliance", "en_description": "Monitor whether others follow the shared rules.", "zh_label": "监督合规", "zh_description": "监督其他人是否遵守共享规则。"},
    "sanction_rule_breaker": {"en_label": "Sanction rule breaker", "en_description": "Apply a sanction to someone who violates the agreed rules.", "zh_label": "惩罚违规者", "zh_description": "对违反共同规则的人实施惩罚。"},
    "contribute_to_collective_action": {"en_label": "Contribute to collective action", "en_description": "Pay a cost to support the group's shared objective.", "zh_label": "为集体行动付出成本", "zh_description": "为群体共同目标付出个人成本。"},
    "free_ride_on_others": {"en_label": "Free-ride on others", "en_description": "Avoid paying the cost while hoping others still mobilize.", "zh_label": "搭便车", "zh_description": "不付出成本而希望他人仍然行动。"},
    "offer_selective_incentive": {"en_label": "Offer selective incentive", "en_description": "Use targeted incentives or penalties to increase participation.", "zh_label": "提供选择性激励", "zh_description": "通过定向激励或惩罚提高参与率。"},
    "choose_market_position": {"en_label": "Choose market position", "en_description": "Choose a location or product position in the competitive space.", "zh_label": "选择市场位置", "zh_description": "在竞争空间中选择位置或产品定位。"},
    "set_price": {"en_label": "Set price", "en_description": "Set a selling price while accounting for transport or mismatch costs.", "zh_label": "设定价格", "zh_description": "在考虑距离或匹配成本的情况下设定价格。"},
    "buy_nearest_offer": {"en_label": "Buy nearest offer", "en_description": "Choose the nearest or most attractive offer as a consumer.", "zh_label": "购买最近报价", "zh_description": "作为消费者选择最近或最有吸引力的报价。"},
    "choose_safe_option": {"en_label": "Choose safe option", "en_description": "Choose the safer or more certain option.", "zh_label": "选择安全选项", "zh_description": "选择更安全或更确定的选项。"},
    "choose_risky_option": {"en_label": "Choose risky option", "en_description": "Choose the riskier option with more variance or upside.", "zh_label": "选择风险选项", "zh_description": "选择波动更大但潜在收益更高的选项。"},
    "keep_endowed_item": {"en_label": "Keep endowed item", "en_description": "Keep the endowed item or current allocation.", "zh_label": "保留已拥有物品", "zh_description": "保留已经拥有的物品或当前配置。"},
    "offer_exchange": {"en_label": "Offer exchange", "en_description": "Offer to exchange, buy, or sell despite the status quo.", "zh_label": "提出交换", "zh_description": "在现状偏好下仍尝试买卖或交换。"},
}

LOCALIZED_SECTION_TITLES = {
    "abstract": {"en": "Abstract", "zh": "摘要"},
    "methods": {"en": "Methods", "zh": "方法"},
    "method": {"en": "Methods", "zh": "方法"},
    "results": {"en": "Results", "zh": "结果"},
    "discussion": {"en": "Discussion", "zh": "讨论"},
    "background": {"en": "Background", "zh": "背景设定"},
    "introduction": {"en": "Introduction", "zh": "引言"},
    "conclusion": {"en": "Conclusion", "zh": "结论"},
    "参与智能体及其角色": {"en": "Agents and Roles", "zh": "参与智能体及其角色"},
    "交互流程与决策机制": {"en": "Interaction Flow and Decision Logic", "zh": "交互流程与决策机制"},
    "技术特征解析": {"en": "Technical Characteristics", "zh": "技术特征解析"},
}


def clean_text(raw_text: str) -> str:
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_chinese_language(language: str | None) -> bool:
    return str(language or "").lower().startswith("zh")


def _localize_text(en_text: str, zh_text: str, language: str | None) -> str:
    return zh_text if _is_chinese_language(language) else en_text


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text)).strip().lower()


def _extract_document_title_candidate(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    first_lines = [line.strip() for line in cleaned.splitlines()[:12] if line.strip()]
    explicit = _extract_scene_title(cleaned)
    if explicit:
        return explicit
    for line in first_lines:
        lowered = line.lower()
        if len(line) < 8 or len(line) > 180:
            continue
        if re.search(r"(copyright|jstor|doi|sage publications|offprint|terms and conditions)", lowered):
            continue
        if re.fullmatch(r"[\W_]+", line):
            continue
        return line
    return first_lines[0] if first_lines else ""


def _normalize_section_key(title: str | None) -> str:
    if not title:
        return "excerpt"
    lowered = str(title).strip().lower()
    if lowered.startswith("excerpt"):
        return "excerpt"
    return lowered


def _section_weight(title: str | None) -> float:
    key = _normalize_section_key(title)
    return SECTION_PRIORITY_WEIGHTS.get(key, 0.6)


def _is_noise_section(title: str | None) -> bool:
    key = _normalize_section_key(title)
    return key in NOISE_SECTION_TITLES


def _sanitize_source_sections(sections: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for index, item in enumerate(sections or [], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or f"Excerpt {index}"
        if _is_noise_section(title):
            continue
        excerpt = clean_text(str(item.get("excerpt", "")).strip())
        if not excerpt:
            continue
        sanitized.append(
            {
                "id": str(item.get("id", f"section-{index}")).strip() or f"section-{index}",
                "title": title,
                "excerpt": excerpt[:1200],
                "page": item.get("page"),
            }
        )
    return sanitized[:16]


def _build_priority_text(text: str, sections: list[dict[str, Any]] | None = None) -> str:
    cleaned = _strip_document_noise(clean_text(text))
    sanitized = _sanitize_source_sections(sections)
    title = _extract_document_title_candidate(cleaned)

    weighted_blocks: list[str] = []
    if title:
        weighted_blocks.extend([title] * int(round(_section_weight("title"))))

    if sanitized:
        ranked = sorted(
            sanitized,
            key=lambda section: (_section_weight(section.get("title")), -len(str(section.get("excerpt", "")))),
            reverse=True,
        )
        for section in ranked[:6]:
            weight = max(1, int(round(_section_weight(section.get("title")))))
            weighted_blocks.extend([str(section.get("excerpt", ""))] * weight)
    else:
        paragraphs = [piece.strip() for piece in re.split(r"\n{2,}", cleaned) if piece.strip()]
        weighted_blocks.extend(paragraphs[:4])

    priority_text = clean_text("\n\n".join(weighted_blocks))
    return priority_text or cleaned


def _tokenize_for_similarity(text: str) -> set[str]:
    return {
        token for token in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", str(text or "").lower())
        if len(token) >= 2 and token not in STOPWORDS
    }


def _semantic_list_overlap(left: list[str], right: list[str]) -> float:
    left_tokens = set().union(*[_tokenize_for_similarity(item) for item in left if item]) if left else set()
    right_tokens = set().union(*[_tokenize_for_similarity(item) for item in right if item]) if right else set()
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / float(len(left_tokens | right_tokens))


def _structure_family(structure_type: str | None) -> str:
    key = str(structure_type or "").strip()
    return STRUCTURE_FAMILY_MAP.get(key, key or "open_ended_custom")


def _localize_structure_label(structure_type: str | None, language: str | None) -> str:
    family = _structure_family(structure_type)
    mapping = STRUCTURE_DISPLAY_TEXTS.get(family)
    if not mapping:
        return family.replace("_", " ")
    return mapping["zh"] if _is_chinese_language(language) else mapping["en"]


def _term_match_ratio(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = _normalize_match_text(text)
    hits = sum(1 for term in terms if _normalize_match_text(term) in lowered)
    return hits / float(len(terms))


def _scenario_keyword_score(text: str, scenario_id: str) -> float:
    return _term_match_ratio(text, SCENARIO_KEYWORDS.get(scenario_id, []))


def _signature_component_scores(
    text: str,
    title: str,
    scenario_id: str,
) -> tuple[dict[str, float], list[str]]:
    signature = SCENARIO_SIGNATURES.get(scenario_id, {})
    reasons: list[str] = []
    title_score = _term_match_ratio(title, signature.get("aliases", []))
    alias_score = _term_match_ratio(text, signature.get("aliases", []))
    role_score = _term_match_ratio(text, signature.get("roles", []))
    action_score = _term_match_ratio(text, signature.get("actions", []))
    payoff_score = _term_match_ratio(text, signature.get("payoffs", []))
    mechanism_score = _term_match_ratio(text, signature.get("mechanisms", []))
    keyword_score = _scenario_keyword_score(text, scenario_id)

    if title_score >= 0.2:
        reasons.append("title match")
    if action_score >= 0.2:
        reasons.append("action structure")
    if role_score >= 0.2:
        reasons.append("role labels")
    if payoff_score >= 0.2:
        reasons.append("payoff rules")
    if mechanism_score >= 0.2:
        reasons.append("mechanism clues")
    if keyword_score >= 0.2:
        reasons.append("keywords")

    return (
        {
            "title": title_score,
            "aliases": alias_score,
            "roles": role_score,
            "actions": action_score,
            "payoffs": payoff_score,
            "mechanisms": mechanism_score,
            "keywords": keyword_score,
        },
        reasons,
    )


def score_template(
    text: str,
    template: dict[str, Any],
    *,
    title: str = "",
    semantic_schema: dict[str, Any] | None = None,
) -> tuple[float, str]:
    scenario_id = str(template.get("id", "")).strip()
    haystack = " ".join(
        [
            str(template.get("name", "")),
            str(template.get("description", "")),
            str(template.get("category", "")),
            " ".join(str(action.get("name", "")) for action in template.get("actions", []) if isinstance(action, dict)),
        ]
    ).lower()
    words = {
        word for word in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", text.lower())
        if len(word) >= 2 and word not in STOPWORDS
    }
    lexical_hits = sum(1 for word in words if word in haystack)
    lexical_score = float(lexical_hits) / float(max(len(words), 1))

    components, reasons = _signature_component_scores(text, title, scenario_id)
    semantic_schema = semantic_schema or {}
    participant_texts = [
        " ".join(str(item.get(part, "")) for part in ("label", "description")).strip()
        for item in semantic_schema.get("participants", [])
        if isinstance(item, dict)
    ]
    action_texts = [
        " ".join(str(item.get(part, "")) for part in ("name", "description")).strip()
        for item in semantic_schema.get("choices", [])
        if isinstance(item, dict)
    ]
    template_action_texts = [
        " ".join(str(action.get(part, "")) for part in ("name", "description")).strip()
        for action in template.get("actions", [])
        if isinstance(action, dict)
    ] + SCENARIO_SIGNATURES.get(scenario_id, {}).get("actions", [])
    mechanism_texts = [
        *[str(item) for item in semantic_schema.get("payoff_rules", [])],
        *[str(item) for item in semantic_schema.get("constraints", [])],
        *[str(item) for item in semantic_schema.get("information_structure", [])],
        *[str(item) for item in semantic_schema.get("interaction_topology", [])],
    ]
    signature = SCENARIO_SIGNATURES.get(scenario_id, {})
    action_overlap = _semantic_list_overlap(action_texts, template_action_texts)
    role_overlap = _semantic_list_overlap(participant_texts, signature.get("roles", []))
    mechanism_overlap = _semantic_list_overlap(
        mechanism_texts,
        [*signature.get("payoffs", []), *signature.get("mechanisms", [])],
    )
    topology_overlap = _semantic_list_overlap(
        [str(item) for item in semantic_schema.get("interaction_topology", [])],
        signature.get("mechanisms", []),
    )
    detected_family = _structure_family((semantic_schema.get("interaction_structure") or {}).get("type"))
    template_family = SCENARIO_STRUCTURE_HINTS.get(scenario_id, "")
    structure_score = 0.0
    structure_conflict = False
    if template_family:
        if detected_family in {"", "open_ended_custom"}:
            structure_score = 0.25
        elif detected_family == template_family:
            structure_score = 1.0
            reasons.append("structure family")
        else:
            structure_conflict = True
            reasons.append("structure conflict")

    score = (
        components["title"] * 0.08
        + components["aliases"] * 0.16
        + components["actions"] * 0.12
        + components["roles"] * 0.06
        + components["payoffs"] * 0.10
        + components["mechanisms"] * 0.08
        + components["keywords"] * 0.05
        + lexical_score * 0.05
        + action_overlap * 0.12
        + role_overlap * 0.05
        + mechanism_overlap * 0.07
        + topology_overlap * 0.03
        + structure_score * 0.13
    )

    if components["title"] >= 0.45:
        score = max(score, 0.38)
    elif components["title"] >= 0.2 and (components["actions"] >= 0.2 or components["mechanisms"] >= 0.2):
        score = max(score, 0.30)

    if structure_conflict:
        score *= 0.28

    if scenario_id == "prisoners_dilemma" and any(term in text.lower() for term in ("accept", "reject", "offer", "aggressive", "yield")):
        score *= 0.45
    if scenario_id == "stag_hunt" and any(term in text.lower() for term in ("accept", "reject", "offer", "auction", "bid")):
        score *= 0.4
    if scenario_id == "public_goods" and any(term in text.lower() for term in ("shared target", "collective loss", "delegate the decision")):
        score *= 0.78

    reason = ", ".join(_dedupe_strings(reasons, limit=5)) if reasons else "light lexical overlap"
    return min(score, 0.99), reason


def suggest_templates(
    text: str,
    scenarios: list[dict[str, Any]],
    top_k: int = 3,
    *,
    source_sections: list[dict[str, Any]] | None = None,
    semantic_schema: dict[str, Any] | None = None,
    language: str | None = None,
) -> list[TemplateSuggestion]:
    results: list[TemplateSuggestion] = []
    cleaned = _build_priority_text(text, source_sections)
    title = _extract_document_title_candidate(cleaned)

    for scenario in scenarios:
        score, reason = score_template(cleaned, scenario, title=title, semantic_schema=semantic_schema)
        if score <= 0:
            continue
        results.append(
            TemplateSuggestion(
                id=str(scenario.get("id", "")),
                name=str(scenario.get("name", "")),
                category=str(scenario.get("category", "")),
                description=str(scenario.get("description", "")),
                score=score,
                reason=_localize_text(
                    f"Matched {reason} (score={score:.2f}).",
                    f"匹配依据：{reason}（得分 {score:.2f}）。",
                    language,
                ),
            )
        )

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:max(1, top_k)]


def _extract_scene_title(text: str) -> str | None:
    cleaned = clean_text(text)
    patterns = [
        r"(?:场景名称|标题|实验名称)\s*[:：]\s*([^\n]+)",
        r"(?:scene title|scenario title|title)\s*[:：]\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_named_section(text: str, labels: list[str]) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    boundary = r"(?:场景名称|背景设定|参与智能体及其角色|交互流程与决策机制|技术特征解析|阶段一|阶段二|阶段三|阶段四|Abstract|摘要|Methods?|方法|Results?|Conclusion|$)"
    joined = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"(?is)(?:{joined})\s*[:：]?\s*(.+?)(?=\n\s*(?:{boundary})\s*[:：]?)")
    match = pattern.search(cleaned)
    return clean_text(match.group(1)) if match else ""


def _parse_numeric_count(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return max(1, int(raw))
    total = 0
    for char in raw:
        if char in CHINESE_NUMBER_MAP:
            total += CHINESE_NUMBER_MAP[char]
    return total or None


def _infer_count_from_text(text: str) -> int | None:
    patterns = [
        r"(\d+)\s*(?:台|个|组|名|辆|支)",
        r"([一二两三四五六七八九十]+)\s*(?:台|个|组|名|辆|支)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _parse_numeric_count(match.group(1))
    return None


def _extract_sub_agents(body: str, parent_label: str) -> list[dict[str, Any]]:
    sub_agents: list[dict[str, Any]] = []
    pattern = re.compile(r"(?m)^\s*[*\-]\s*([A-Za-z0-9][A-Za-z0-9\-_]*(?:（[^）]+）|\([^)]+\))?)\s*[:：]\s*(.+)$")
    for match in pattern.finditer(body):
        label = match.group(1).strip()
        summary = clean_text(match.group(2))
        sub_agents.append(
            {
                "label": label,
                "description": summary[:260] or f"Sub-agent within {parent_label}.",
                "count": 1,
            }
        )
    return sub_agents


def extract_role_blocks(text: str) -> list[dict[str, Any]]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    role_section = _extract_named_section(cleaned, ["参与智能体及其角色", "智能体及其角色", "agents and roles", "agents"])
    haystack = role_section or cleaned
    pattern = re.compile(r"(?ms)^\s*(\d+)[\.\u3001]\s*([^\n]+)\n(.*?)(?=^\s*\d+[\.\u3001]\s*[^\n]+\n|\Z)")

    roles: list[dict[str, Any]] = []
    for match in pattern.finditer(haystack):
        heading = clean_text(match.group(2))
        body = clean_text(match.group(3))
        if not heading:
            continue

        sub_agents = _extract_sub_agents(body, heading)
        if sub_agents:
            roles.extend(sub_agents)
            continue

        role_summary_parts: list[str] = []
        function_match = re.search(r"(?:核心职能|职责|职能)\s*[:：]\s*([^\n]+)", body)
        behavior_match = re.search(r"(?:行为逻辑|决策逻辑|工作逻辑)\s*[:：]\s*(.+?)(?:\n\s*[*\-]|$)", body, re.S)
        if function_match:
            role_summary_parts.append(clean_text(function_match.group(1)))
        if behavior_match:
            role_summary_parts.append(clean_text(behavior_match.group(1))[:220])
        if not role_summary_parts:
            role_summary_parts.append(body[:240])

        roles.append(
            {
                "label": heading,
                "description": " ".join(part for part in role_summary_parts if part).strip(),
                "count": _infer_count_from_text(body) or 1,
            }
        )

    return roles[:10]


def extract_stage_blocks(text: str) -> list[dict[str, str]]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    pattern = re.compile(r"(?ms)^\s*[*\-]?\s*(阶段[一二三四五六七八九十0-9]+)\s*[:：]\s*([^\n]+)\n(.*?)(?=^\s*[*\-]?\s*阶段[一二三四五六七八九十0-9]+\s*[:：]|\Z)")
    stages: list[dict[str, str]] = []
    for match in pattern.finditer(cleaned):
        stages.append(
            {
                "title": clean_text(match.group(1)),
                "window": clean_text(match.group(2)),
                "body": clean_text(match.group(3))[:500],
            }
        )
    return stages[:8]


def build_source_outline(text: str) -> dict[str, Any]:
    title = _extract_scene_title(text) or _extract_document_title_candidate(text)
    background = _extract_named_section(text, ["背景设定", "background"])
    roles = extract_role_blocks(text)
    stages = extract_stage_blocks(text)
    return {
        "title": title,
        "background": background[:800] if background else "",
        "roles": roles,
        "stages": stages,
    }


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _humanize_action_name(name: str) -> str:
    return re.sub(r"[_\s]+", " ", str(name or "")).strip()


def _display_action_name(name: str, use_chinese: bool) -> str:
    if use_chinese and name in CUSTOM_ACTION_DISPLAY_NAMES:
        return CUSTOM_ACTION_DISPLAY_NAMES[name]
    return _humanize_action_name(name)


def _localize_action_item(name: str, description: str, language: str | None) -> dict[str, str]:
    normalized_key = re.sub(r"\s+", "_", str(name or "").strip().lower()).strip("_")
    reverse_zh = {
        values["zh_label"]: key
        for key, values in LOCALIZED_ACTION_TEXTS.items()
        if values.get("zh_label")
    }
    action_key = reverse_zh.get(str(name).strip(), normalized_key)
    localized = LOCALIZED_ACTION_TEXTS.get(action_key)
    if not localized:
        return {
            "name": str(name or "").strip(),
            "description": str(description or "").strip(),
        }
    if _is_chinese_language(language):
        return {
            "name": localized.get("zh_label", str(name or "").strip()),
            "description": localized.get("zh_description", str(description or "").strip()),
        }
    return {
        "name": localized.get("en_label", _humanize_action_name(name).title()),
        "description": localized.get("en_description", str(description or "").strip()),
    }


def _localize_section_title(title: str, language: str | None) -> str:
    key = str(title or "").strip().lower()
    mapped = LOCALIZED_SECTION_TITLES.get(key) or LOCALIZED_SECTION_TITLES.get(str(title or "").strip())
    if not mapped:
        return str(title or "").strip()
    return mapped["zh"] if _is_chinese_language(language) else mapped["en"]


def _compact_excerpt(text: str, limit: int = 220) -> str:
    compact = clean_text(text)
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _strip_document_noise(text: str) -> str:
    paragraphs = [piece.strip() for piece in re.split(r"\n{2,}", clean_text(text)) if piece.strip()]
    noise_patterns = [
        r"jstor",
        r"terms and conditions",
        r"stable url",
        r"copyright",
        r"sage publications",
        r"publisher contact",
        r"http[:/]",
        r"www\.",
        r"trademark office",
        r"for more information on jstor",
        r"essay study questions",
        r"study questions",
        r"glossary",
        r"bibliography",
    ]
    filtered: list[str] = []
    stop_after_noise_heading = False
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if stop_after_noise_heading:
            continue
        if lowered in NOISE_SECTION_TITLES:
            stop_after_noise_heading = lowered in {"references", "reference", "bibliography", "appendix", "appendices", "glossary"}
            continue
        if sum(1 for pattern in noise_patterns if re.search(pattern, lowered)) >= 1:
            continue
        if re.fullmatch(r"(references|bibliography|appendix|appendices|glossary|essay study questions|study questions)\s*", lowered):
            stop_after_noise_heading = True
            continue
        filtered.append(paragraph)
    return clean_text("\n\n".join(filtered)) or clean_text(text)


def _detect_interaction_structure(text: str, outline: dict[str, Any] | None = None) -> dict[str, Any]:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    threshold_groups = [
        [
            "threshold",
            "threshold model",
            "adoption threshold",
            "riot threshold",
            "number or proportion of others",
            "how many other actors",
            "阈值",
            "阈值模型",
            "参与阈值",
            "达到或超过自己的阈值",
        ],
        [
            "adopt",
            "join",
            "participate once enough",
            "wait for more",
            "participate",
            "join collective action",
            "加入",
            "采纳",
            "观望",
            "等待更多",
            "参与行动",
            "参与抗议",
            "抗议",
            "罢工",
            "请愿",
            "转发",
        ],
        [
            "cascade",
            "diffusion",
            "spread",
            "collective behavior",
            "enough others",
            "after others",
            "已有多少人参与",
            "参与人数",
            "扩散",
            "级联",
            "集体行为",
            "当足够多人",
        ],
    ]
    shared_target_groups = [
        ["contribute", "contribution", "shared target", "group target", "common target", "collective risk", "public good", "公共目标", "集体风险", "共同目标"],
        ["keep", "private account", "private use", "hold back resources", "私有账户", "保留资源", "私用"],
        ["delegate", "delegation", "collective loss", "shared loss", "catastrophic loss", "委托", "集体损失", "共同损失"],
    ]
    contagion_needles = ("contagion", "infection", "infected", "susceptible", "recovery", "exposure", "neighbors", "network")
    threshold_core_hit = any(term in lowered for term in threshold_groups[0])
    threshold_hits = sum(1 for group in threshold_groups if any(term in lowered for term in group))
    shared_target_hits = sum(1 for group in shared_target_groups if any(term in lowered for term in group))
    contagion_hint_hits = sum(1 for term in contagion_needles if term in lowered)
    strong_threshold_collective_terms = (
        "threshold models of collective behavior",
        "collective behavior",
        "riot threshold",
        "number or proportion of others",
        "how many other actors choose which alternative",
        "participation spreads",
        "threshold model",
        "集体行为",
        "阈值模型",
        "参与人数达到",
        "已有多少人参与",
    )
    strong_threshold_collective_hit = any(term in lowered for term in strong_threshold_collective_terms)
    if threshold_core_hit and threshold_hits >= 2 and (contagion_hint_hits == 0 or strong_threshold_collective_hit) and (
        shared_target_hits < 2 or strong_threshold_collective_hit
    ):
        return {"type": "threshold_adoption_process", "confidence": threshold_hits}
    generic_rules = [
        (
            "dyadic_cooperate_defect",
            [
                ["prisoner's dilemma", "prisoners dilemma", "cooperate", "defect"],
                ["two players", "pairs of participants", "joint decision", "pairwise"],
                ["mutual cooperation", "mutual defection", "incentive to defect", "without knowing the partner's current move"],
            ],
            2,
        ),
        (
            "proposal_response_exchange",
            [
                ["proposer", "first player", "allocator", "sender", "initiator"],
                ["responder", "second player", "receiver", "reviewer"],
                ["offer", "proposal", "allocate", "split", "division"],
                ["accept", "approve", "reject", "refuse"],
            ],
            3,
        ),
        (
            "competitive_pressure_choice",
            [
                ["aggressive strategy", "compete", "fight", "attack", "contest", "hawk"],
                ["yield", "avoid conflict", "retreat", "de-escalate", "dove"],
                ["conflict cost", "injury cost", "contested resource", "resource value"],
            ],
            2,
        ),
        (
            "shared_target_threshold",
            [
                ["contribute", "contribution", "shared target", "group target", "common target", "collective risk"],
                ["keep", "private account", "private use", "hold back resources"],
                ["threshold", "collective loss", "shared loss", "catastrophic loss", "group fails"],
            ],
            2,
        ),
        (
            "majority_visibility_pressure",
            [
                ["majority", "group answer", "visible others", "public response", "publicly", "asch", "多数人", "公开作答"],
                ["conform", "go along", "match the group", "independent answer", "disagree publicly", "从众", "坚持私人判断"],
                ["judgment", "line comparison", "visible responses", "social pressure", "线段长度", "group pressure", "modification of judgments"],
            ],
            2,
        ),
        (
            "bystander_help_diffusion",
            [
                ["bystander", "emergency", "help", "intervene", "bystander effect", "旁观者", "紧急情况", "提供帮助"],
                ["diffusion of responsibility", "someone else will help", "others may act first", "责任扩散", "别人会帮", "已经有人行动"],
                ["severity", "cost of helping", "witnesses", "seriousness", "事件严重性", "行动成本", "旁观者数量"],
            ],
            2,
        ),
        (
            "authority_obedience_conflict",
            [
                ["obedience", "authority", "command", "experimenter", "服从", "权威", "命令"],
                ["moral conflict", "discomfort", "refuse", "withdraw", "道德冲突", "不适", "拒绝继续", "退出成本"],
                ["learner", "executor", "shock level", "teacher", "执行者", "受影响对象", "层级压力", "责任转移"],
            ],
            2,
        ),
        (
            "intergroup_competition_superordinate_goal",
            [
                ["ingroup", "outgroup", "camp", "two groups", "group identity", "内群体", "外群体", "两个群体"],
                ["competition", "scarce resource", "hostility", "rival", "竞争", "稀缺资源", "敌意"],
                ["superordinate goal", "joint task", "across groups", "共同目标", "超级目标", "跨群体合作"],
            ],
            2,
        ),
        (
            "social_comparison_adjustment",
            [
                ["social comparison", "compare", "similar others", "peer performance", "社会比较", "比较他人", "相似他人"],
                ["self-evaluation", "confidence", "ability judgment", "自我评价", "自信", "能力判断"],
                ["opinion", "norm", "adjust", "group standard", "观点", "规范", "主流标准", "调整自身"],
            ],
            2,
        ),
        (
            "contagion_spread",
            [
                ["contagion", "infection", "infected", "susceptible", "recovery"],
                ["neighbors", "network", "exposure", "spread"],
                ["adopt", "behavior", "cumulative adoption"],
            ],
            2,
        ),
        (
            "threshold_adoption_process",
            [
                ["threshold", "threshold model", "adoption threshold", "number or proportion of others", "riot threshold", "阈值", "阈值模型", "参与阈值"],
                ["adopt", "join", "participate once enough", "wait for more", "participate", "加入", "采纳", "观望", "等待更多", "参与行动", "参与抗议"],
                ["cascade", "diffusion", "spread", "collective behavior", "已有多少人参与", "参与人数", "扩散", "级联", "集体行为"],
            ],
            2,
        ),
        (
            "attendance_capacity_avoidance",
            [
                ["el farol", "bar problem", "酒吧", "attendance history", "historical attendance"],
                ["go to the bar", "attend", "stay away", "是否去", "是否前往"],
                ["crowded", "overcrowded", "less than 60", "capacity", "拥挤", "容量", "60%"],
            ],
            2,
        ),
        (
            "minority_side_choice",
            [
                ["minority game", "minority side", "少数派博弈", "少数派"],
                ["two options", "two restaurants", "two directions", "两个选项", "两个餐厅", "两个方向"],
                ["minority wins", "less crowded side", "人数较少的一边获胜", "人数较少的一侧获胜"],
            ],
            2,
        ),
        (
            "common_pool_governance",
            [
                ["ostrom", "governing the commons", "local rule", "self-governance", "ostrom", "地方规则", "自组织治理"],
                ["monitor", "monitoring", "graduated sanctions", "conflict resolution", "监督", "分级惩罚", "冲突解决"],
                ["resource users", "forest", "fishery", "irrigation", "资源使用者", "森林", "渔场", "灌溉系统"],
            ],
            2,
        ),
        (
            "common_pool_extraction",
            [
                ["commons", "common pool", "common resource", "shared pasture", "fishery", "公共资源", "共同资源", "公地"],
                ["extract", "harvest", "overuse", "depletion", "提取", "采集", "过度使用", "枯竭"],
                ["quota", "governance", "punishment", "配额", "治理", "惩罚"],
            ],
            2,
        ),
        (
            "sanctioning_public_goods",
            [
                ["public goods", "public pool", "shared account", "公共品", "公共池", "共享账户"],
                ["contribute", "keep", "free rider", "贡献", "保留", "搭便车"],
                ["punish", "punishment", "sanction", "惩罚", "制裁"],
            ],
            2,
        ),
        (
            "collective_action_free_rider",
            [
                ["collective action", "interest group", "lobby", "集体行动", "利益集团", "公共目标"],
                ["free rider", "free-ride", "selective incentive", "搭便车", "选择性激励"],
                ["large group", "organization cost", "mobilization", "大群体", "组织成本", "动员"],
            ],
            2,
        ),
        (
            "spatial_relocation_preference",
            [
                ["segregation", "grid", "neighborhood", "邻居", "邻域", "网格", "隔离"],
                ["move", "relocate", "empty cell", "搬家", "搬迁", "空位置"],
                ["same type", "similar neighbors", "同类邻居", "相似邻居"],
            ],
            2,
        ),
        (
            "sequential_information_cascade",
            [
                ["information cascade", "herd behavior", "herd", "informational cascades", "信息级联", "羊群效应"],
                ["sequentially", "in order", "early movers", "按顺序", "前面的人", "顺序决策"],
                ["private signal", "ignore own signal", "follow previous choices", "私人信号", "忽略自己的信号", "跟随前人选择"],
            ],
            2,
        ),
        (
            "organizational_garbage_can",
            [
                ["garbage can", "choice opportunity", "garbage-can model", "垃圾桶模型", "选择机会"],
                ["problems", "solutions", "participants", "问题", "解决方案", "参与者"],
                ["randomly meet", "drift", "meeting", "随机相遇", "漂移", "会议"],
            ],
            2,
        ),
        (
            "weighted_opinion_averaging",
            [
                ["degroot", "consensus", "opinion dynamics", "de groot", "共识", "观点动力学"],
                ["weighted average", "average of neighbors", "加权平均", "邻居平均"],
                ["update opinion", "opinion update", "更新观点", "更新意见"],
            ],
            2,
        ),
        (
            "liquidity_run_coordination",
            [
                ["bank run", "bank runs", "deposit insurance", "liquidity", "银行挤兑", "存款保险", "流动性"],
                ["withdraw early", "withdraw deposit", "keep deposit", "提前取款", "继续持有存款"],
                ["panic", "others withdraw", "self-fulfilling", "恐慌", "别人会取款", "自我实现预期"],
            ],
            2,
        ),
        (
            "asymmetric_quality_market",
            [
                ["lemons", "quality uncertainty", "used car", "二手车", "质量不确定", "柠檬市场"],
                ["seller knows quality", "buyer does not know", "private quality", "卖家知道质量", "买家不知道"],
                ["reputation", "certification", "adverse selection", "声誉", "认证", "逆向选择"],
            ],
            2,
        ),
        (
            "adaptive_asset_market",
            [
                ["artificial stock market", "heterogeneous expectations", "fundamentalist", "chartist", "人工股票市场", "异质预期", "基本面交易者", "趋势交易者"],
                ["forecast rule", "trend following", "mean reversion", "strategy switching", "预测规则", "趋势跟随", "均值回归", "策略切换"],
                ["price history", "price dynamics", "bubble", "volatility clustering", "价格历史", "泡沫", "波动聚集"],
            ],
            2,
        ),
        (
            "noise_arbitrage_market",
            [
                ["noise trader", "arbitrageur", "mispricing", "噪声交易者", "套利者", "错误定价"],
                ["sentiment", "funding constraint", "limits to arbitrage", "情绪", "资金约束", "套利限制"],
                ["bubble", "deviation from fundamental", "crowd pressure", "泡沫", "偏离基本面", "群体压力"],
            ],
            2,
        ),
        (
            "insider_market_making",
            [
                ["insider trading", "informed trader", "market maker", "内幕交易", "知情交易者", "做市商"],
                ["noise trader", "order flow", "continuous auction", "噪声交易者", "订单流", "连续拍卖"],
                ["private value", "hide information", "price impact", "私有信息", "隐藏信息", "价格冲击"],
            ],
            2,
        ),
        (
            "exploration_exploitation_learning",
            [
                ["exploration", "exploitation", "organizational learning", "探索", "利用", "组织学习"],
                ["innovation", "path dependence", "short-term", "长期收益", "路径依赖", "短期收益"],
                ["new option", "known option", "experiment", "新方案", "现有方案", "试错"],
            ],
            2,
        ),
        (
            "supply_chain_bullwhip",
            [
                ["beer game", "bullwhip", "retailer", "wholesaler", "beer distribution", "牛鞭效应", "零售商", "批发商"],
                ["inventory", "backlog", "lead time", "订单延迟", "库存", "缺货", "提前期"],
                ["factory", "distributor", "downstream demand", "工厂", "分销商", "下游需求"],
            ],
            2,
        ),
        (
            "innovation_diffusion_marketing",
            [
                ["bass diffusion", "diffusion of innovations", "innovators", "early adopters", "bass 模型", "创新扩散", "创新者", "早期采纳者"],
                ["advertising", "word of mouth", "imitation", "adoption curve", "广告", "口碑", "模仿", "采纳曲线"],
                ["consumer", "purchase", "late majority", "laggards", "消费者", "购买", "后期多数", "落后者"],
            ],
            2,
        ),
        (
            "spatial_price_competition",
            [
                ["hotelling", "linear city", "spatial competition", "hotelling", "线性城市", "空间竞争"],
                ["location", "transport cost", "distance cost", "位置选择", "运输成本", "距离成本"],
                ["two firms", "middle", "minimum differentiation", "两家店", "中间靠拢", "最小差异化"],
            ],
            2,
        ),
        (
            "reference_dependent_risk_choice",
            [
                ["prospect theory", "loss aversion", "framing effect", "前景理论", "损失厌恶", "框架效应"],
                ["safe option", "risky option", "certainty", "安全选项", "风险选项", "确定性"],
                ["gain", "loss", "reference point", "收益", "损失", "参照点"],
            ],
            2,
        ),
        (
            "endowment_statusquo_exchange",
            [
                ["endowment effect", "status quo bias", "wta", "wtp", "禀赋效应", "现状偏好", "愿受价格", "愿付价格"],
                ["owning", "owned item", "seller", "buyer", "已经拥有", "持有者", "买方", "卖方"],
                ["exchange", "trade", "mug", "cup", "交易阻滞", "交换", "杯子"],
            ],
            2,
        ),
        (
            "collective_motion_alignment",
            [
                ["boids", "flocking", "vicsek", "collective motion", "群体运动", "鸟群", "鱼群"],
                ["align", "avoid collision", "cohesion", "对齐", "避碰", "凝聚"],
                ["heading", "velocity", "noise", "direction", "moving agent", "local group center", "方向", "速度", "噪声"],
            ],
            2,
        ),
        (
            "resource_search_trade_ecology",
            [
                ["sugarscape", "artificial society", "sugar", "糖景观", "人工社会", "糖资源"],
                ["metabolism", "vision", "harvest", "trade", "代谢率", "视野", "采集", "贸易"],
                ["wealth", "inequality", "disease", "财富", "不平等", "疾病"],
            ],
            2,
        ),
        (
            "recruitment_switching",
            [
                ["kirman", "recruitment", "ants", "ant recruitment", "招募", "蚂蚁"],
                ["two food sources", "two restaurants", "两个食物源", "两个餐厅"],
                ["switch", "herding", "集中到一边", "切换", "羊群"],
            ],
            2,
        ),
        (
            "coordination_matching",
            [
                ["coordination", "match", "same option", "effort level"],
                ["players", "participants", "small groups", "neighbors"],
                ["coordination failure", "shared menu", "tacit coordination"],
            ],
            2,
        ),
        (
            "escalating_bidding",
            [
                ["auction", "bid", "bidder", "outbid"],
                ["highest bidder", "second highest bidder", "both pay", "payment rule"],
                ["increment", "raise", "withdraw", "stop bidding"],
            ],
            2,
        ),
    ]
    for structure_type, signal_groups, threshold in generic_rules:
        group_hits = sum(1 for group in signal_groups if any(term in lowered for term in group))
        if structure_type == "threshold_adoption_process" and not any(term in lowered for term in signal_groups[0]):
            continue
        if group_hits >= threshold:
            return {"type": structure_type, "confidence": group_hits}

    roles = (outline or {}).get("roles") or []
    stages = (outline or {}).get("stages") or []
    operational_terms = [
        "重定向",
        "绕行",
        "信号优先",
        "绿色通道",
        "救护车",
        "消防车",
        "警车",
        "隔离区",
        "广播",
        "推送",
        "应急",
        "traffic",
        "reroute",
        "signal priority",
        "emergency response",
        "hazard",
    ]
    operational_hits = sum(1 for term in operational_terms if term in cleaned or term in lowered)
    if (operational_hits >= 2 and (len(roles) >= 2 or len(stages) >= 2)) or operational_hits >= 3:
        return {"type": "operational_coordination", "confidence": max(len(roles), len(stages), operational_hits)}

    return {"type": "generic", "confidence": 0}


def _collect_matching_sentences(
    text: str,
    patterns: list[str],
    *,
    limit: int = 4,
) -> list[str]:
    matches: list[str] = []
    for sentence in _split_sentence_candidates(text):
        for pattern in patterns:
            if re.search(pattern, sentence, re.IGNORECASE):
                matches.append(sentence.strip())
                break
        if len(matches) >= limit:
            break
    return _dedupe_strings(matches, limit=limit)


def _infer_ontology_primitives(
    *,
    participants: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    payoff_rules: list[str],
    constraints: list[str],
    information_structure: list[str],
    interaction_topology: list[str],
    outcomes: list[str],
    structure_type: str | None,
) -> dict[str, list[str]]:
    participant_labels = " ".join(str(item.get("label", "")) for item in participants if isinstance(item, dict)).lower()
    action_labels = " ".join(
        " ".join(str(item.get(part, "")) for part in ("name", "description"))
        for item in actions
        if isinstance(item, dict)
    ).lower()
    mechanisms_text = " ".join([*payoff_rules, *constraints, *information_structure, *interaction_topology]).lower()
    outcomes_text = " ".join(outcomes).lower()
    structure_family = _structure_family(structure_type)

    participant_primitives: list[str] = []
    if structure_family in {"dyadic_bargaining", "dyadic_cooperate_defect"} or any(term in participant_labels for term in ("two players", "proposer", "responder", "initiator", "reviewer")):
        participant_primitives.append("双方")
    if any(term in participant_labels for term in ("participants", "players", "group members", "subjects")):
        participant_primitives.append("小组")
    if any(term in participant_labels for term in ("neighbors", "network", "contacts")):
        participant_primitives.append("网络节点")
    if any(term in participant_labels for term in ("auctioneer", "confederates", "majority")):
        participant_primitives.append("中介")
    if not participant_primitives:
        participant_primitives.append("个体")

    action_primitives: list[str] = []
    action_map = {
        "选择": ("choose", "decide", "defect", "cooperate", "option"),
        "分配": ("allocate", "split", "proposal"),
        "报价": ("bid", "raise"),
        "接受": ("accept", "approve"),
        "拒绝": ("reject", "refuse"),
        "贡献": ("contribute", "shared pool"),
        "保留": ("keep", "private"),
        "投票": ("vote", "abstain"),
        "采纳": ("adopt", "join"),
        "等待": ("wait", "hold back"),
        "惩罚": ("punish", "punishment"),
        "协调": ("coordinate", "match", "reroute"),
        "交流": ("speak", "share", "broadcast", "status update"),
    }
    for label, needles in action_map.items():
        if any(needle in action_labels for needle in needles):
            action_primitives.append(label)
    if structure_family == "dyadic_bargaining":
        action_primitives.extend(["分配", "接受", "拒绝"])
    elif structure_family == "threshold_public_good_collective_target":
        action_primitives.extend(["贡献", "保留"])
    elif structure_family == "auction_escalation":
        action_primitives.extend(["报价", "等待"])

    mechanism_primitives: list[str] = []
    mechanism_map = {
        "同步": ("same round", "simultaneous", "joint decision"),
        "异步": ("sequential", "first player", "second player"),
        "一次性": ("one-shot", "single round"),
        "重复轮次": ("repeated", "many rounds", "each round"),
        "双边": ("two players", "pairwise"),
        "群体": ("group", "public account", "shared target"),
        "网络": ("network", "neighbors", "topology"),
        "公共信息": ("public response", "visible majority", "shared memory"),
        "私有信息": ("without knowing", "private account"),
        "阈值": ("threshold", "collective risk", "enough others"),
        "收益矩阵": ("payoff", "mutual cooperation", "mutual defection", "matrix"),
        "预算": ("budget", "tokens", "endowment"),
        "惩罚": ("punishment", "reduce another member"),
        "传播": ("spread", "infection", "contagion"),
    }
    for label, needles in mechanism_map.items():
        if any(needle in mechanisms_text for needle in needles):
            mechanism_primitives.append(label)

    outcome_primitives: list[str] = []
    outcome_map = {
        "收益": ("payoff", "reward", "benefit", "cooperation"),
        "损失": ("loss", "penalty", "cost", "catastrophic"),
        "达标/失败": ("threshold", "avoid the loss", "fails", "success"),
        "扩散规模": ("cascade size", "cumulative adoption", "spread"),
        "协调成功率": ("coordination success", "match", "stable pattern"),
        "从众率": ("conformity", "alignment", "majority"),
    }
    for label, needles in outcome_map.items():
        if any(needle in outcomes_text or needle in mechanisms_text for needle in needles):
            outcome_primitives.append(label)

    structure_candidates = [structure_family]
    return {
        "participant_primitives": _dedupe_strings(participant_primitives, limit=6),
        "action_primitives": _dedupe_strings(action_primitives, limit=8),
        "mechanism_primitives": _dedupe_strings(mechanism_primitives, limit=10),
        "outcome_primitives": _dedupe_strings(outcome_primitives, limit=6),
        "structure_candidates": _dedupe_strings(structure_candidates, limit=4),
    }


def _extract_generic_role_mentions(text: str, language: str | None = None) -> list[dict[str, Any]]:
    lowered = text.lower()
    role_specs = [
        ("auctioneer", "Runs the auction and enforces the rules.", "拍卖主持者，负责执行规则和收取支付。", 1),
        ("bidders", "Players who decide whether to keep bidding or stop.", "竞价者，需要决定继续出价还是停止竞价。", 2),
        ("first player", "Makes the initial proposal or first move.", "负责提出初始方案或先手决策。", 1),
        ("second player", "Responds to the initial proposal or first move.", "负责对初始方案或先手动作做出回应。", 1),
        ("initiator", "Starts the exchange or puts the first proposal on the table.", "发起交换或首先提出方案的角色。", 1),
        ("reviewer", "Evaluates whether to approve, reject, or counter the proposal.", "负责评估并接受、拒绝或回应方案的角色。", 1),
        ("confederates", "Members of the majority group whose visible responses shape social pressure.", "构成多数意见、制造社会压力的群体成员。", 3),
        ("majority", "The visible majority position in the group.", "群体中可见的多数立场。", 3),
        ("two players", "A pair of players making interdependent repeated choices.", "一对进行相互依赖重复决策的参与者。", 2),
        ("players", "Players making repeated decisions in the experiment.", "实验中的决策参与者。", 2),
        ("participants", "Participants making repeated decisions in the experiment.", "实验中的决策参与者。", 4),
        ("managers", "Managers responding to organizational constraints and incentives.", "在组织约束和激励下做决策的管理者。", 3),
        ("workers", "Workers responding to tasks, information, and incentives.", "根据任务、信息和激励做决策的执行者。", 4),
        ("residents", "Residents responding to local conditions and information.", "根据地方条件和信息做出反应的居民。", 4),
        ("citizens", "Citizens making decisions in the modeled setting.", "在建模情境中作出选择的公民。", 4),
    ]
    roles: list[dict[str, Any]] = []
    for label, en_desc, zh_desc, default_count in role_specs:
        if re.search(rf"\b{re.escape(label.rstrip('s'))}(?:s)?\b", lowered):
            roles.append(
                {
                    "label": label,
                    "description": _localize_text(en_desc, zh_desc, language),
                    "count": default_count,
                }
            )
    if any(role["label"] not in {"players", "participants"} for role in roles):
        roles = [role for role in roles if role["label"] not in {"players", "participants"}]
    return roles[:6]


def _default_actions_for_scenario(scenario_id: str | None, language: str | None = None) -> list[dict[str, str]]:
    defaults = DEFAULT_SCENARIO_ACTIONS.get(str(scenario_id or "").strip(), [])
    return [
        _localize_action_item(item.get("name", ""), item.get("description", ""), language)
        for item in defaults
        if isinstance(item, dict)
    ]


def _default_actions_for_structure(structure_type: str | None, language: str | None = None) -> list[dict[str, str]]:
    defaults = CUSTOM_STRUCTURE_ACTIONS.get(str(structure_type or "").strip(), [])
    if not defaults and str(structure_type or "").strip() == "operational_coordination":
        defaults = [
            {
                "name": "reroute_traffic",
                "description": _localize_text(
                    "Redirect local flow toward safer or less congested routes.",
                    "将局部流量重定向至更安全或更通畅的路线。",
                    language,
                ),
            },
            {
                "name": "request_signal_priority",
                "description": _localize_text(
                    "Grant temporary signal priority for emergency movement.",
                    "为紧急通行授予临时信号优先权。",
                    language,
                ),
            },
            {
                "name": "share_status_update",
                "description": _localize_text(
                    "Publish alerts or routing updates to nearby participants.",
                    "向附近参与者发布警报或路线更新。",
                    language,
                ),
            },
            {
                "name": "dispatch_response_resources",
                "description": _localize_text(
                    "Dispatch emergency resources based on the latest shared state.",
                    "根据最新共享状态调度应急资源。",
                    language,
                ),
            },
            {
                "name": "inspect_hazard_zone",
                "description": _localize_text(
                    "Inspect the incident zone to confirm hazards and update the shared model.",
                    "检查事故区域以确认危险并更新共享模型。",
                    language,
                ),
            },
        ]
    return [
        _localize_action_item(item.get("name", ""), item.get("description", ""), language)
        for item in defaults
        if isinstance(item, dict)
    ]


def _default_agents_for_scenario(scenario_id: str | None, language: str | None = None) -> list[dict[str, Any]]:
    scenario_id = str(scenario_id or "").strip()
    if scenario_id == "public_goods":
        return [
            {"label": "participants", "description": _localize_text("Participants deciding how much to contribute or keep each round.", "每轮决定贡献多少或保留多少资源的参与者。", language), "count": 4},
        ]
    if scenario_id == "prisoners_dilemma":
        return [
            {"label": "players", "description": _localize_text("Two players choosing between cooperation and defection.", "在合作与背叛之间做选择的两名参与者。", language), "count": 2},
        ]
    if scenario_id == "coordination_game":
        return [
            {"label": "players", "description": _localize_text("Players trying to coordinate on the same choice.", "尝试在同一选项上达成协调的参与者。", language), "count": 4},
        ]
    if scenario_id == "contagion":
        return [
            {"label": "participants", "description": _localize_text("Participants embedded in a network who can expose or adopt behaviors.", "嵌入网络、会相互暴露并采纳行为的参与者。", language), "count": 10},
        ]
    return []


def _default_agents_for_structure(structure_type: str | None, language: str | None = None) -> list[dict[str, Any]]:
    structure_type = str(structure_type or "").strip()
    if structure_type == "proposal_response_exchange":
        return [
            {"label": "initiator", "description": _localize_text("Makes the opening proposal or first move.", "负责提出初始方案或先手动作。", language), "count": 1},
            {"label": "reviewer", "description": _localize_text("Approves, rejects, or responds to that proposal.", "负责接受、拒绝或回应该方案。", language), "count": 1},
        ]
    if structure_type == "competitive_pressure_choice":
        return [
            {"label": "players", "description": _localize_text("Players choosing between stronger competition and safer restraint.", "在强竞争与克制退让之间做选择的参与者。", language), "count": 2},
        ]
    if structure_type == "shared_target_threshold":
        return [
            {"label": "participants", "description": _localize_text("Participants deciding how much to contribute toward a shared target.", "围绕共同目标决定贡献水平的参与者。", language), "count": 4},
        ]
    if structure_type == "majority_visibility_pressure":
        return [
            {"label": "subject", "description": _localize_text("The focal participant making public judgments.", "在公开情境中给出判断的核心被试。", language), "count": 1},
            {"label": "majority confederates", "description": _localize_text("Visible majority members whose responses create social pressure.", "通过一致作答施加社会压力的多数成员。", language), "count": 3},
        ]
    if structure_type == "threshold_adoption_process":
        return [
            {"label": "participants", "description": _localize_text("Individuals with different adoption thresholds.", "具有不同采纳阈值的个体。", language), "count": 10},
        ]
    if structure_type == "escalating_bidding":
        return [
            {"label": "auctioneer", "description": _localize_text("Runs the auction and enforces the payment rule.", "负责主持拍卖并执行支付规则。", language), "count": 1},
            {"label": "bidders", "description": _localize_text("Bid against each other while deciding whether to continue or stop.", "在继续出价与停止之间做决定的竞价者。", language), "count": 2},
        ]
    if structure_type == "attendance_capacity_avoidance":
        return [
            {"label": "attendees", "description": _localize_text("Agents who independently decide whether to attend a congestible venue.", "独立决定是否前往拥挤场所的参与者。", language), "count": 100},
        ]
    if structure_type == "minority_side_choice":
        return [
            {"label": "players", "description": _localize_text("Agents choosing between two sides while trying to end up in the minority.", "在两个选项中选择并尽量落在少数派一侧的参与者。", language), "count": 101},
        ]
    if structure_type == "common_pool_extraction":
        return [
            {"label": "resource users", "description": _localize_text("Agents extracting from the same finite common-pool resource.", "从同一有限公共资源池中提取资源的参与者。", language), "count": 8},
        ]
    if structure_type == "sanctioning_public_goods":
        return [
            {"label": "contributors", "description": _localize_text("Agents deciding both contributions and whether to punish free riders.", "既要决定贡献又要决定是否惩罚搭便车者的参与者。", language), "count": 4},
        ]
    if structure_type == "spatial_relocation_preference":
        return [
            {"label": "residents", "description": _localize_text("Residents who move when local neighborhood composition is unsatisfactory.", "当局部邻里构成不满意时会搬迁的居民。", language), "count": 50},
        ]
    if structure_type == "sequential_information_cascade":
        return [
            {"label": "decision makers", "description": _localize_text("Agents choosing sequentially after observing earlier public actions.", "按顺序决策并观察前人公开选择的个体。", language), "count": 10},
        ]
    if structure_type == "organizational_garbage_can":
        return [
            {"label": "participants", "description": _localize_text("Organizational members who drift in and out of choice opportunities.", "在不同选择机会中流动出现的组织成员。", language), "count": 6},
            {"label": "problems", "description": _localize_text("Problems waiting to be attached to available decision opportunities.", "等待被挂接到决策机会上的问题流。", language), "count": 4},
            {"label": "solutions", "description": _localize_text("Solutions circulating independently of the problems they may solve.", "独立于问题而流动的解决方案流。", language), "count": 4},
        ]
    if structure_type == "weighted_opinion_averaging":
        return [
            {"label": "agents", "description": _localize_text("Opinion holders who repeatedly average over their neighbors' views.", "反复根据邻居观点加权平均来更新意见的个体。", language), "count": 12},
        ]
    if structure_type == "collective_motion_alignment":
        return [
            {"label": "moving agents", "description": _localize_text("Self-propelled agents aligning movement with local neighbors.", "依据局部邻居信息调整运动方向的自驱动个体。", language), "count": 30},
        ]
    if structure_type == "resource_search_trade_ecology":
        return [
            {"label": "foragers", "description": _localize_text("Agents moving through space to harvest, consume, and trade resources.", "在空间中移动、采集、消耗并交易资源的个体。", language), "count": 25},
        ]
    if structure_type == "recruitment_switching":
        return [
            {"label": "recruits", "description": _localize_text("Agents who can remain with or switch between two equivalent options through recruitment.", "会在两种等价选项之间因招募而停留或切换的个体。", language), "count": 50},
        ]
    if structure_type == "bystander_help_diffusion":
        return [
            {"label": "bystanders", "description": _localize_text("Witnesses who decide whether to intervene in an emergency.", "在紧急事件中决定是否出手干预的旁观者。", language), "count": 8},
        ]
    if structure_type == "authority_obedience_conflict":
        return [
            {"label": "authority", "description": _localize_text("Issues commands and applies hierarchy pressure.", "发出指令并施加层级压力的权威角色。", language), "count": 1},
            {"label": "executors", "description": _localize_text("Receive orders and decide whether to comply or refuse.", "接收命令并决定服从或拒绝的执行者。", language), "count": 1},
            {"label": "affected parties", "description": _localize_text("Those affected by the executor's choice or task outcome.", "受到执行者选择或任务结果影响的对象。", language), "count": 1},
        ]
    if structure_type == "intergroup_competition_superordinate_goal":
        return [
            {"label": "group A members", "description": _localize_text("Members of the first group with their own local identity.", "具有本组身份认同的第一群体成员。", language), "count": 6},
            {"label": "group B members", "description": _localize_text("Members of the second group that may become a rival or partner.", "可能成为竞争者或合作方的第二群体成员。", language), "count": 6},
        ]
    if structure_type == "social_comparison_adjustment":
        return [
            {"label": "agents", "description": _localize_text("Individuals comparing their opinions, abilities, or status with similar peers.", "将自己的观点、能力或地位与相似同伴比较的个体。", language), "count": 10},
        ]
    if structure_type == "liquidity_run_coordination":
        return [
            {"label": "depositors", "description": _localize_text("Depositors deciding whether to withdraw early or keep their funds in the bank.", "决定提前取款还是继续持有存款的储户。", language), "count": 20},
            {"label": "bank", "description": _localize_text("The intermediary transforming short-term withdrawals into long-term assets.", "进行短存长贷转换的中介银行。", language), "count": 1},
        ]
    if structure_type == "asymmetric_quality_market":
        return [
            {"label": "sellers", "description": _localize_text("Sellers who privately know the quality of the asset or good.", "私下知道商品或资产真实质量的卖家。", language), "count": 6},
            {"label": "buyers", "description": _localize_text("Buyers inferring quality from price, reputation, and signals.", "根据价格、声誉和信号推断质量的买家。", language), "count": 6},
        ]
    if structure_type == "adaptive_asset_market":
        return [
            {"label": "traders", "description": _localize_text("Traders using heterogeneous forecasting rules and adapting after observed profits.", "使用异质预测规则并根据收益持续调整的交易者。", language), "count": 20},
        ]
    if structure_type == "noise_arbitrage_market":
        return [
            {"label": "noise traders", "description": _localize_text("Traders who follow sentiment, rumor, or mistaken beliefs.", "依据情绪、传闻或错误信念交易的噪声交易者。", language), "count": 10},
            {"label": "arbitrageurs", "description": _localize_text("Traders who try to exploit mispricing but face funding and timing risk.", "试图利用错误定价但受资金和时机风险约束的套利者。", language), "count": 6},
        ]
    if structure_type == "insider_market_making":
        return [
            {"label": "informed trader", "description": _localize_text("A trader with private information about underlying value.", "掌握标的真实价值私有信息的交易者。", language), "count": 1},
            {"label": "noise traders", "description": _localize_text("Uninformed traders who generate background order flow.", "生成背景订单流的无信息交易者。", language), "count": 10},
            {"label": "market maker", "description": _localize_text("Sets prices in response to incoming order flow.", "根据订单流变化设定价格的做市商。", language), "count": 1},
        ]
    if structure_type == "exploration_exploitation_learning":
        return [
            {"label": "teams", "description": _localize_text("Teams or agents deciding between uncertain exploration and reliable exploitation.", "在不确定探索与可靠利用之间做决策的团队或个体。", language), "count": 8},
        ]
    if structure_type == "supply_chain_bullwhip":
        return [
            {"label": "retailer", "description": _localize_text("Observes customer demand and places local replenishment orders.", "观察消费者需求并下达补货订单的零售商。", language), "count": 1},
            {"label": "wholesaler", "description": _localize_text("Buffers and forwards orders further upstream.", "缓冲并向上游继续传递订单的批发商。", language), "count": 1},
            {"label": "distributor", "description": _localize_text("Coordinates midstream inventory and delivery delays.", "协调中游库存与配送延迟的分销商。", language), "count": 1},
            {"label": "factory", "description": _localize_text("Produces supply with manufacturing and shipping delays.", "在生产与运输延迟下提供供给的工厂。", language), "count": 1},
        ]
    if structure_type == "innovation_diffusion_marketing":
        return [
            {"label": "consumers", "description": _localize_text("Potential adopters with different innovation propensity and social influence.", "具有不同创新倾向和社会影响敏感度的潜在消费者。", language), "count": 20},
        ]
    if structure_type == "common_pool_governance":
        return [
            {"label": "resource users", "description": _localize_text("Local users sharing and governing the same resource system.", "共同使用并治理同一资源系统的本地使用者。", language), "count": 8},
            {"label": "monitors", "description": _localize_text("Actors who observe rule compliance and trigger sanctions.", "观察规则执行并触发惩罚的监督者。", language), "count": 2},
        ]
    if structure_type == "collective_action_free_rider":
        return [
            {"label": "members", "description": _localize_text("Group members deciding whether to bear the cost of collective mobilization.", "决定是否承担集体动员成本的群体成员。", language), "count": 12},
        ]
    if structure_type == "spatial_price_competition":
        return [
            {"label": "firms", "description": _localize_text("Firms choosing market position and price in a shared competitive space.", "在共同竞争空间中选择位置与价格的企业。", language), "count": 2},
            {"label": "consumers", "description": _localize_text("Consumers choosing offers based on distance and price.", "依据距离和价格进行选择的消费者。", language), "count": 20},
        ]
    if structure_type == "reference_dependent_risk_choice":
        return [
            {"label": "decision makers", "description": _localize_text("Agents whose risk choices depend on framing, gains, and losses.", "其风险决策受表述方式、收益和损失影响的个体。", language), "count": 10},
        ]
    if structure_type == "endowment_statusquo_exchange":
        return [
            {"label": "owners", "description": _localize_text("Agents who begin with an endowed item or protected status quo.", "起始时拥有某个物品或既得状态的个体。", language), "count": 5},
            {"label": "buyers", "description": _localize_text("Agents who may want the item but value it differently before owning it.", "在拥有前对该物品估值不同、可能想购买的个体。", language), "count": 5},
        ]
    return []


def _filter_noisy_actions(
    actions: list[dict[str, Any]] | None,
    *,
    language: str | None = None,
) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for item in actions or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        description = str(item.get("description", "")).strip()
        if _looks_like_noise_label(name):
            continue
        if description and len(description) > 220 and _looks_like_noise_label(description[:120]):
            continue
        if not name:
            continue
        if "Explicit action inventory recovered from the source text" in description or "从原文的明确动作清单中恢复的动作" in description:
            filtered.append({"name": name, "description": description})
            continue
        localized = _localize_action_item(name, description or name, language)
        if _looks_like_noise_label(localized.get("name", "")):
            continue
        filtered.append(localized)
    return filtered[:8]


def _filter_noisy_agents(
    agents: list[dict[str, Any]] | None,
    *,
    language: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in agents or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        description = str(item.get("description", "")).strip()
        if _looks_like_noise_label(label):
            continue
        if not label:
            continue
        filtered.append(
            {
                "label": label,
                "description": description or _localize_text(
                    "Primary decision-making participants in the reconstructed experiment.",
                    "重建实验中的主要决策参与者。",
                    language,
                ),
                "count": max(1, int(item.get("count", 1) or 1)),
            }
        )
    return filtered[:8]


def build_semantic_schema(
    text: str,
    sections: list[dict[str, Any]] | None = None,
    outline: dict[str, Any] | None = None,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    cleaned = _strip_document_noise(clean_text(text))
    source_sections = _sanitize_source_sections(sections) if sections else split_source_sections(cleaned)
    source_outline = outline or build_source_outline(cleaned)
    title = str(source_outline.get("title") or _extract_document_title_candidate(cleaned) or "").strip()
    sentences = _split_sentence_candidates(cleaned)

    setting = str(source_outline.get("background") or "").strip()
    if not setting:
        setting = " ".join(sentences[:2]).strip()[:500]

    goal_sentences = _collect_matching_sentences(
        cleaned,
        [
            r"\b(research question|we study|this study|we examine|we investigate|illustrates|analysis)\b",
            r"(研究问题|本文研究|我们研究|用于说明|用于分析)",
        ],
        limit=2,
    )
    research_goal = goal_sentences[0] if goal_sentences else (title or setting[:220])

    decision_context = _collect_matching_sentences(
        cleaned,
        [
            r"\b(decide whether|choose between|choose|bid|vote|contribute|defect|cooperate|allocate|route|dispatch|offer|reject|accept|delegate|adopt)\b",
            r"(选择|决定是否|出价|投票|贡献|合作|背叛|调度|绕行|广播|报价|接受|拒绝|委托|采纳)",
        ],
        limit=3,
    )

    payoff_rules = _collect_matching_sentences(
        cleaned,
        [
            r"\b(pay|pays|payoff|loss|gain|reward|penalty|punishment|cost|multiplier|highest bidder|second highest bidder|threshold|catastrophic|both receive nothing)\b",
            r"(支付|收益|损失|奖励|惩罚|成本|倍数|最高出价者|次高出价者|阈值|灾难性)",
        ],
        limit=4,
    )

    constraints = _collect_matching_sentences(
        cleaned,
        [
            r"\b(must be made in multiples|must|cannot|upper limit|time limit|ends if|termination|specific length of time|threshold|if rejected)\b",
            r"(必须|不可|上限|时限|结束条件|终止|固定时间|阈值|拒绝后)",
        ],
        limit=4,
    )

    information_structure = _collect_matching_sentences(
        cleaned,
        [
            r"\b(without knowing|knowing the partner|information|observe|visibility|shared memory|feedback|majority judgment|public response)\b",
            r"(不知道|信息|观察|可见性|共享内存|反馈|多数判断|公开作答)",
        ],
        limit=3,
    )

    topology = _collect_matching_sentences(
        cleaned,
        [
            r"\b(network|neighbor|graph|topology|hierarchy|distributed|decentralized|small-world|threshold distribution)\b",
            r"(网络|邻居|拓扑|层级|分布式|去中心化|小世界|阈值分布)",
        ],
        limit=3,
    )

    interventions = _collect_matching_sentences(
        cleaned,
        [
            r"\b(intervention|treatment|manipulation|policy|signal timing|open an emergency lane|delegate|delegation)\b",
            r"(干预|处理组|操纵|政策|信号配时|开放应急车道|委托)",
        ],
        limit=3,
    )

    outcomes = _collect_matching_sentences(
        cleaned,
        [
            r"\b(cooperation|escalation|response time|compliance|performance|recovery|spread|coordination|conformity|adoption)\b",
            r"(合作|升级|响应时间|服从|绩效|恢复|传播|协同|从众|采纳)",
        ],
        limit=4,
    )

    participant_roles = _filter_noisy_agents(
        source_outline.get("roles") or _extract_generic_role_mentions(cleaned, language) or _extract_agents(cleaned, None),
        language=language,
    )
    actions = _filter_noisy_actions(
        _extract_actions_from_text(cleaned, None, source_outline, language),
        language=language,
    )
    key_variables = _extract_key_variables(cleaned)
    interaction_structure = _detect_interaction_structure(cleaned, source_outline)
    interaction_structure = {
        **interaction_structure,
        "family": _structure_family(interaction_structure.get("type")),
        "display_label": _localize_structure_label(interaction_structure.get("type"), language),
    }
    ontology = _infer_ontology_primitives(
        participants=participant_roles,
        actions=actions,
        payoff_rules=payoff_rules,
        constraints=constraints,
        information_structure=information_structure,
        interaction_topology=topology,
        outcomes=outcomes,
        structure_type=interaction_structure.get("type"),
    )

    evidence_map = {
        "research_goal": goal_sentences[:2],
        "setting": [setting] if setting else [],
        "participants": [
            str(item.get("description") or item.get("label") or "").strip()
            for item in participant_roles[:3]
            if str(item.get("description") or item.get("label") or "").strip()
        ],
        "decision_context": decision_context[:2],
        "actions": [
            str(item.get("description") or item.get("name") or "").strip()
            for item in actions[:4]
            if str(item.get("description") or item.get("name") or "").strip()
        ],
        "payoff_rules": payoff_rules[:2],
        "constraints": constraints[:2],
        "information_structure": information_structure[:2],
        "interaction_topology": topology[:2],
        "interaction_structure": [interaction_structure.get("display_label", "")] if interaction_structure.get("type") and interaction_structure.get("type") != "generic" else [],
        "key_variables": key_variables[:4],
        "outcomes": outcomes[:2],
    }

    return {
        "title": title,
        "research_goal": research_goal,
        "setting": setting,
        "participants": participant_roles,
        "decision_context": decision_context,
        "choices": actions,
        "payoff_rules": payoff_rules,
        "constraints": constraints,
        "information_structure": information_structure,
        "interaction_topology": topology,
        "interaction_structure": interaction_structure,
        "interventions": interventions,
        "outcomes": outcomes,
        "key_variables": key_variables,
        "ontology": ontology,
        "source_sections": source_sections,
        "outline": source_outline,
        "evidence_map": evidence_map,
    }


def split_source_sections(text: str) -> list[dict[str, Any]]:
    cleaned = _strip_document_noise(clean_text(text))
    if not cleaned:
        return []

    pattern = re.compile(
        r"(?im)^(abstract|摘要|introduction|引言|background|背景设定|methods?|methodology|方法|materials and methods|参与智能体及其角色|智能体及其角色|交互流程与决策机制|技术特征解析|results?|结果|discussion|讨论|conclusion|结论|references|bibliography|appendix|appendices|glossary|study questions|essay study questions)\s*$"
    )
    matches = list(pattern.finditer(cleaned))
    sections: list[dict[str, Any]] = []
    title = _extract_document_title_candidate(cleaned)

    if title:
        sections.append(
            {
                "id": "section-title",
                "title": "Title",
                "excerpt": title[:240],
            }
        )

    if matches:
        for index, match in enumerate(matches):
            title_text = match.group(1).strip()
            if _is_noise_section(title_text):
                continue
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
            body = clean_text(cleaned[start:end])
            if not body:
                continue
            sections.append(
                {
                    "id": f"section-{len(sections) + 1}",
                    "title": title_text,
                    "excerpt": body[:700],
                }
            )
    else:
        paragraphs = [piece.strip() for piece in re.split(r"\n{2,}", cleaned) if piece.strip()]
        if not paragraphs:
            paragraphs = [cleaned]
        for index, piece in enumerate(paragraphs[:10], start=1):
            if title and piece == title:
                continue
            sections.append(
                {
                    "id": f"excerpt-{len(sections) + 1}",
                    "title": f"Excerpt {index}",
                    "excerpt": piece[:700],
                }
            )
    return _sanitize_source_sections(sections)[:12]


def _split_sentence_candidates(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?。！？])\s+", clean_text(text))
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _dedupe_strings(values: list[str], *, limit: int = 10) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _split_choice_list(raw: str) -> list[str]:
    raw = re.sub(r"^[Tt]o\s+", "", raw.strip())
    raw = raw.strip(" .;:，。；、")
    pieces = re.split(r",|/|;|；|、|\bor\b|\band\b| versus | vs\.? |\u6216|\u4e0e", raw, flags=re.IGNORECASE)
    cleaned = []
    for piece in pieces:
        item = re.sub(r"^[\"'“”‘’\-\d\.\)\( ]+|[\"'“”‘’ ]+$", "", piece).strip()
        item = re.sub(r"^(choose|select|decide whether to|decide to)\s+", "", item, flags=re.IGNORECASE)
        if len(item) < 2:
            continue
        cleaned.append(item)
    return _dedupe_strings(cleaned, limit=6)


def _infer_custom_actions(
    text: str,
    outline: dict[str, Any] | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    cleaned = clean_text(text)
    structure = _detect_interaction_structure(cleaned, outline)
    structure_actions = _default_actions_for_structure(str(structure.get("type", "")), language)
    if structure_actions:
        return structure_actions
    if structure["type"] != "operational_coordination":
        return []

    role_text = " ".join(
        str(role.get("label", "")) + " " + str(role.get("description", ""))
        for role in (outline or {}).get("roles", [])
        if isinstance(role, dict)
    )
    stage_text = " ".join(
        str(stage.get("title", "")) + " " + str(stage.get("window", "")) + " " + str(stage.get("body", ""))
        for stage in (outline or {}).get("stages", [])
        if isinstance(stage, dict)
    )
    haystack = " ".join([cleaned, role_text, stage_text])

    ranked: list[tuple[int, dict[str, str]]] = []
    for item in CUSTOM_ACTION_LIBRARY:
        score = 0
        for pattern in item.get("patterns", []):
            matches = re.findall(pattern, haystack, re.IGNORECASE)
            score += len(matches)
        if score <= 0:
            continue
        ranked.append(
            (
                score,
                _localize_action_item(str(item["name"]), str(item["description"]), language),
            )
        )

    ranked.sort(key=lambda row: (-row[0], row[1]["name"]))
    return [item for _, item in ranked[:8]]


def _extract_actions_from_text(
    text: str,
    preferred_scenario_id: str | None,
    outline: dict[str, Any] | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    sentences = _split_sentence_candidates(text)
    actions: list[str] = []
    explicit_action_inventory = bool(
        re.search(r"(available actions?|action space|action rules?|动作包括|候选动作|可选动作|行动规则|智能体动作|操作包括)\s*[:：]?\s*", text, re.IGNORECASE)
    )

    patterns = [
        r"(?:action rules?|available actions?|action space|动作包括|候选动作|可选动作|行动规则|智能体动作|操作包括)\s*[:：]\s*([^.:\n]+)",
        r"choose between ([^.:\n]+)",
        r"decide whether to ([^.:\n]+)",
        r"can either ([^.:\n]+)",
        r"options? (?:were|are|include) ([^.:\n]+)",
        r"available actions? (?:were|are|include) ([^.:\n]+)",
        r"participants? (?:could|can) ([^.:\n]+)",
        r"\b(?:first player|initiator|allocator|sender|player 1)\b[^.:\n]{0,80}\b(?:offer|propose|allocate|split)\b([^.:\n]+)",
        r"\b(?:second player|reviewer|receiver|player 2)\b[^.:\n]{0,80}\b(?:accept|approve|reject|refuse)\b([^.:\n]+)",
        r"在([^。；\n]+?)之间选择",
        r"选择([^。；\n]+)",
    ]
    for sentence in sentences[:40]:
        for pattern in patterns:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if match:
                actions.extend(_split_choice_list(match.group(1)))

    generic_action_cues = [
        (r"\b(raise(?:\s+to)?|increase the bid|outbid|bid higher)\b", "increase_bid"),
        (r"\b(stop bidding|withdraw|stand pat|drop out|exit bidding)\b", "exit_bidding"),
        (r"\b(accept|accepted|approve|approved)\b", "approve_split"),
        (r"\b(reject|rejected|refuse|refused)\b", "reject_split"),
        (r"\b(offer|propose a split|make an offer|allocate|divide)\b", "propose_split"),
        (r"\b(compete|contest|aggressive strategy|fight)\b", "choose_compete"),
        (r"\b(yield|avoid conflict|retreat|de-escalate)\b", "choose_yield"),
        (r"\b(delegate|delegation)\b", "delegate_choice"),
        (r"\b(adopt|join the action|join once enough others|join the strike)\b", "adopt_behavior"),
        (r"\b(wait|hold back|wait for more)\b", "wait_for_more_adoption"),
        (r"\b(conform|match the majority|go along with the group)\b", "align_with_visible_majority"),
    ]
    for sentence in sentences[:40]:
        for pattern, action_name in generic_action_cues:
            if re.search(pattern, sentence, re.IGNORECASE):
                actions.append(action_name)

    normalized_actions: list[dict[str, str]] = [
        _localize_action_item(
            re.sub(r"\s+", "_", action.lower()).strip("_"),
            _localize_text(
                f"Action reconstructed from the source text: {action}.",
                f"根据原文重建的动作：{action}。",
                language,
            ),
            language,
        )
        for action in _dedupe_strings(actions, limit=6)
    ]

    if explicit_action_inventory and len(normalized_actions) >= 2:
        explicit_items = []
        for action in _dedupe_strings(actions, limit=8):
            action_key = re.sub(r"\s+", "_", action.lower()).strip("_")
            explicit_items.append(
                {
                    "name": action_key,
                    "description": _localize_text(
                        f"Explicit action inventory recovered from the source text: {action}.",
                        f"从原文的明确动作清单中恢复的动作：{action}。",
                        language,
                    ),
                }
            )
        return explicit_items[:8]

    inferred_custom = _infer_custom_actions(text, outline, language)
    known_names = {item["name"] for item in normalized_actions}
    for item in inferred_custom:
        if item["name"] not in known_names:
            normalized_actions.append(item)
            known_names.add(item["name"])

    lowered = text.lower()
    if normalized_actions:
        if preferred_scenario_id in {"prisoners_dilemma", "public_goods"}:
            defaults = _default_actions_for_scenario(preferred_scenario_id, language)
            if defaults:
                return defaults[:8]
        return normalized_actions[:8]

    scenario_defaults = DEFAULT_SCENARIO_ACTIONS.get(preferred_scenario_id or "", [])
    if "contribute" in lowered and ("keep" in lowered or "private account" in lowered):
        scenario_defaults = DEFAULT_SCENARIO_ACTIONS["public_goods"]
    else:
        structure_actions = _default_actions_for_structure(str(_detect_interaction_structure(text, outline).get("type", "")), language)
        if structure_actions:
            return structure_actions[:8]
    if (
        not scenario_defaults
        and any(term in lowered for term in ("offer", "split", "allocate"))
        and any(term in lowered for term in ("accept", "approve", "reject", "refuse"))
    ):
        return _default_actions_for_structure("proposal_response_exchange", language)[:8]
    elif (
        not scenario_defaults
        and any(term in lowered for term in ("aggressive strategy", "contest", "conflict cost"))
        and any(term in lowered for term in ("yield", "avoid conflict", "retreat"))
    ):
        return _default_actions_for_structure("competitive_pressure_choice", language)[:8]
    elif (
        not scenario_defaults
        and any(term in lowered for term in ("shared target", "group target", "collective loss", "collective risk", "threshold"))
        and any(term in lowered for term in ("contribute", "keep", "delegate"))
    ):
        return _default_actions_for_structure("shared_target_threshold", language)[:8]
    elif (
        not scenario_defaults
        and any(term in lowered for term in ("majority", "public response", "social pressure"))
        and any(term in lowered for term in ("conform", "independent answer", "go along"))
    ):
        return _default_actions_for_structure("majority_visibility_pressure", language)[:8]
    elif (
        not scenario_defaults
        and any(term in lowered for term in ("threshold", "enough others", "cascade", "diffusion"))
        and any(term in lowered for term in ("adopt", "join", "wait"))
    ):
        return _default_actions_for_structure("threshold_adoption_process", language)[:8]
    elif (
        not scenario_defaults
        and any(term in lowered for term in ("collision", "align", "cohesion", "local group center", "avoid collisions"))
        and any(term in lowered for term in ("moving agent", "flock", "bird", "fish", "heading", "velocity"))
    ):
        return _default_actions_for_structure("collective_motion_alignment", language)[:8]
    elif "vote yes" in lowered or "vote no" in lowered or "abstain" in lowered:
        scenario_defaults = DEFAULT_SCENARIO_ACTIONS["council_chamber"]
    elif "share" in lowered and "hoard" in lowered:
        scenario_defaults = DEFAULT_SCENARIO_ACTIONS["resource_scarcity"]
    elif "cooperate" in lowered and "defect" in lowered:
        scenario_defaults = DEFAULT_SCENARIO_ACTIONS["prisoners_dilemma"]
    return [
        _localize_action_item(item.get("name", ""), item.get("description", ""), language)
        for item in scenario_defaults
        if isinstance(item, dict)
    ]


def _extract_key_variables(text: str) -> list[str]:
    lowered = text.lower()
    variables: list[str] = []
    seeds = [
        ("trust", "trust"),
        ("risk", "risk"),
        ("cost", "cost"),
        ("benefit", "benefit"),
        ("auction", "auction dynamics"),
        ("bid", "bidding escalation"),
        ("escalation", "escalation"),
        ("loss", "loss exposure"),
        ("sunk cost", "sunk cost pressure"),
        ("reputation", "reputation"),
        ("status", "status"),
        ("information", "information"),
        ("norm", "norm"),
        ("compliance", "compliance"),
        ("opinion", "opinion"),
        ("polarization", "polarization"),
        ("resource", "resource"),
        ("network", "network"),
        ("hierarchy", "hierarchy"),
        ("policy", "policy meaning"),
        ("信任", "trust"),
        ("风险", "risk"),
        ("成本", "cost"),
        ("收益", "benefit"),
        ("声誉", "reputation"),
        ("地位", "status"),
        ("规范", "norm"),
        ("服从", "compliance"),
        ("观点", "opinion"),
        ("极化", "polarization"),
        ("资源", "resource"),
        ("网络", "network"),
        ("层级", "hierarchy"),
        ("政策", "policy meaning"),
    ]
    for needle, label in seeds:
        if needle in lowered or needle in text:
            variables.append(label)

    explicit_patterns = [
        r"(?:independent|dependent|key)\s+variables?\s*[:：]\s*([^\n.]+)",
        r"(?:变量|关键变量)\s*[:：]\s*([^\n。]+)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            variables.extend(_split_choice_list(match.group(1)))

    return _dedupe_strings(variables, limit=10)


def _extract_agent_count(text: str) -> int | None:
    patterns = [
        r"(\d+)\s+(?:participants|subjects|students|agents|players|citizens|residents|workers|members)",
        r"样本(?:量)?\s*(?:为|=)?\s*(\d+)",
        r"(\d+)\s*名(?:参与者|受试者|成员|居民|市民|公民|个体)",
        r"每层\s*(\d+)\s*(?:名)?(?:参与者|代理|人)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return max(1, int(match.group(1)))
            except Exception:
                continue
    return None


def _extract_agents(text: str, preferred_scenario_id: str | None) -> list[dict[str, Any]]:
    role_agents = extract_role_blocks(text)
    if role_agents:
        return role_agents

    count = _extract_agent_count(text)
    lowered = text.lower()

    cjk_role_map = [
        ("市民", "市民", "在城市情境中根据阈值决定是否参与行动的市民。"),
        ("居民", "居民", "在社区或城市情境中观察他人后再决定是否参与的居民。"),
        ("公民", "公民", "根据周围参与情况更新行为决策的公民。"),
        ("邻居", "邻居", "在局部观察网络中相互影响的邻居。"),
    ]
    cjk_roles: list[dict[str, Any]] = []
    for needle, label, description in cjk_role_map:
        if needle in text:
            cjk_roles.append({"label": label, "description": description, "count": count or 4})
    if cjk_roles:
        return cjk_roles[:4]

    if any(term in lowered for term in ("citizen", "citizens", "resident", "residents", "household", "households", "individual", "individuals", "actor", "actors")):
        label = "citizens" if "citizen" in lowered else "residents" if "resident" in lowered else "households"
        if "individual" in lowered:
            label = "individuals"
        elif "actor" in lowered:
            label = "actors"
        description = "Individuals deciding whether to join once public participation crosses their threshold."
        return [{"label": label, "description": description, "count": count or 4}]

    structure = _detect_interaction_structure(text)
    structure_agents = _default_agents_for_structure(str(structure.get("type", "")))
    if structure_agents:
        return structure_agents

    defaults = _default_agents_for_scenario(preferred_scenario_id)
    if defaults:
        return defaults

    if preferred_scenario_id == "policy_erosion":
        per_tier = count or 5
        return [
            {"label": "top tier officials", "description": T("prompts.roles.top_tier_officials", locale="en"), "count": per_tier},
            {"label": "middle managers", "description": T("prompts.roles.middle_managers", locale="en"), "count": per_tier},
            {"label": "frontline staff", "description": T("prompts.roles.frontline_staff", locale="en"), "count": per_tier},
        ]

    if preferred_scenario_id == "council_chamber":
        return [
            {"label": "council members", "description": T("prompts.roles.council_members", locale="en"), "count": count or 5},
        ]

    if preferred_scenario_id == "prisoners_dilemma" or "prisoner" in lowered:
        return [
            {"label": "players", "description": T("prompts.roles.prisoners_dilemma_players", locale="en"), "count": 2},
        ]

    if any(term in lowered for term in ("manager", "official", "employee", "worker", "resident", "citizen", "household")):
        roles: list[dict[str, Any]] = []
        role_map = [
            ("manager", "managers", "Actors with mid-level authority."),
            ("official", "officials", "Formal institutional decision-makers."),
            ("employee", "employees", "Workers implementing or reacting to decisions."),
            ("worker", "workers", "Workers responding to local incentives."),
            ("resident", "residents", "Community residents in the setting."),
            ("citizen", "citizens", "Citizens deciding how to act."),
            ("household", "households", "Household-level actors making decisions."),
        ]
        for needle, label, description in role_map:
            if needle in lowered:
                roles.append({"label": label, "description": description, "count": count or 4})
        if roles:
            return roles[:4]

    return [
        {"label": "participants", "description": T("prompts.roles.default_participants", locale="en"), "count": count or 4},
    ]


def _build_custom_scenario_description(
    text: str,
    outline: dict[str, Any],
    actions: list[dict[str, str]],
    agents: list[dict[str, Any]],
    language: str | None = None,
) -> str:
    structure = _detect_interaction_structure(text, outline)
    title = str(outline.get("title") or "").strip()
    background = str(outline.get("background") or "").strip()
    stages = outline.get("stages") or []
    agent_labels = [str(item.get("label", "")).strip() for item in agents if isinstance(item, dict) and item.get("label")]
    is_cjk = _is_chinese_language(language)
    action_labels = [
        _display_action_name(str(item.get("name", "")), is_cjk)
        for item in actions
        if isinstance(item, dict) and item.get("name")
    ]

    structure_templates = {
        "attendance_capacity_avoidance": (
            "描述了一个有限容量下的出席规避场景。个体会根据历史拥挤程度预测他人是否前往，并在“前往”与“暂不前往”之间做出选择，以避免陷入过度拥挤。",
            "reconstructs a congestible attendance setting in which agents predict whether others will attend and choose whether to go or stay away under a capacity constraint.",
        ),
        "minority_side_choice": (
            "描述了一个典型的少数派选择场景。所有个体都在两个选项之间做决定，而落在人数较少一侧的参与者会获得更好结果，因此系统会持续出现反协调与波动。",
            "reconstructs a minority-choice setting in which agents repeatedly pick between two sides and benefit from ending up on the less crowded side.",
        ),
        "common_pool_extraction": (
            "描述了一个有限公共资源的提取困境。个体的短期收益来自资源提取，但如果多数人都过度使用资源，整体资源存量会下降甚至枯竭。",
            "reconstructs a common-pool resource dilemma in which short-run gains come from extraction while cumulative overuse depletes the shared resource stock.",
        ),
        "sanctioning_public_goods": (
            "描述了一个带惩罚阶段的公共品博弈。参与者先决定是否向公共池贡献资源，再决定是否花费成本惩罚搭便车者，以观察合作能否被维持。",
            "reconstructs a public-goods contribution game with a punishment stage in which agents first decide contributions and then decide whether to sanction free riders.",
        ),
        "spatial_relocation_preference": (
            "描述了一个基于局部偏好的空间搬迁过程。个体只观察邻近单元的构成，当周围同类比例低于满意阈值时，会迁移到新的空位置。",
            "reconstructs a spatial relocation process in which agents inspect local neighborhood composition and move when similarity falls below an acceptable threshold.",
        ),
        "sequential_information_cascade": (
            "描述了一个顺序决策下的信息级联场景。后行动者既有私人信号，也能看到前面人的公开选择；当早期选择形成偏向时，后续个体可能忽略自己的信号并跟随前人。",
            "reconstructs a sequential information-cascade setting in which later agents observe earlier public choices and may ignore their private signals to follow the emerging herd.",
        ),
        "organizational_garbage_can": (
            "描述了一个垃圾桶式组织决策过程。问题、方案、参与者与选择机会并不按线性顺序配对，而是在有限注意力与偶然相遇中临时组合成决策。",
            "reconstructs a garbage-can organizational choice process in which problems, solutions, participants, and choice opportunities meet opportunistically rather than in a neat linear order.",
        ),
        "weighted_opinion_averaging": (
            "描述了一个基于邻居加权平均的意见更新过程。个体每轮根据周围人的观点和权重更新自己的判断，长期可能收敛到共识，也可能形成权威主导或局部极化。",
            "reconstructs a weighted opinion-averaging process in which agents update beliefs from neighbors and may converge to consensus or become dominated by influential nodes.",
        ),
        "collective_motion_alignment": (
            "描述了一个局部规则驱动的群体运动场景。个体通过局部感知不断执行方向对齐、避碰和靠拢群体等动作，从而在没有中央控制的情况下形成整体运动。",
            "reconstructs a local-alignment collective motion process in which self-propelled agents align heading, avoid collision, and cohere into a larger moving group without central control.",
        ),
        "resource_search_trade_ecology": (
            "描述了一个人工社会中的资源搜索与交易生态。个体在空间中移动、采集资源、进行消耗与交换，并在长期演化中产生财富差异、迁移和贸易网络。",
            "reconstructs an artificial-society resource ecology in which agents move, harvest, consume, and trade resources, producing longer-run inequality and exchange patterns.",
        ),
        "recruitment_switching": (
            "描述了一个招募驱动的双选项切换过程。个体会在两种看似等价的选项之间因随机探索和社会招募而持续聚集、切换并产生群体性偏向。",
            "reconstructs a recruitment-driven switching process in which agents cluster around one of two equivalent options and may later switch because of stochastic exploration and social recruitment.",
        ),
        "bystander_help_diffusion": (
            "描述了一个紧急情境中的旁观援助决策过程。每个个体都会观察事件严重程度、旁观者数量以及他人是否已经行动；群体越大，责任越容易扩散，从而抑制首个帮助行为的出现。",
            "reconstructs a bystander-help process in which agents observe emergency severity, group size, and whether others have already intervened, with larger groups diffusing responsibility and suppressing first action.",
        ),
        "authority_obedience_conflict": (
            "描述了一个权威命令与个人道德冲突并存的层级决策场景。执行者一边接收权威指令，一边承担逐步上升的不适、责任归属与退出成本，因此服从与拒绝会在过程里持续拉扯。",
            "reconstructs a hierarchical obedience setting in which executors receive authority commands while facing rising moral discomfort, responsibility transfer, and exit costs.",
        ),
        "intergroup_competition_superordinate_goal": (
            "描述了一个群际关系动态演化过程。系统先强化组内认同，再通过稀缺资源竞争放大群际敌意，最后通过需要跨群体合作的超级目标观察冲突能否被缓和。",
            "reconstructs an intergroup process that builds local identity, escalates conflict through resource competition, and then tests whether superordinate goals can restore cooperation.",
        ),
        "social_comparison_adjustment": (
            "描述了一个基于社会比较的自我评价与规范形成过程。个体会参考相似他人的表现或观点来调整自己的信心、判断和群体归属，多轮互动后可能形成主流标准或群体极化。",
            "reconstructs a social-comparison process in which agents adjust confidence, judgment, and belonging by comparing themselves with similar others, potentially generating norms or polarization over time.",
        ),
        "liquidity_run_coordination": (
            "描述了一个银行挤兑式流动性协调困境。只要储户相信他人会提前取款，自己的最佳反应也会变成赶紧取款，从而使原本稳定的系统因为预期自我实现而陷入挤兑。",
            "reconstructs a bank-run coordination problem in which depositors' beliefs about others' withdrawals can become self-fulfilling and trigger a liquidity crisis.",
        ),
        "asymmetric_quality_market": (
            "描述了一个质量信息不对称的交易市场。卖方知道商品质量，买方只能根据价格、信号和声誉来推断价值，这会驱动逆向选择并可能使高质量供给逐步退出市场。",
            "reconstructs an asymmetric-quality market in which sellers privately know quality while buyers infer value from price, signals, and reputation, creating adverse selection pressure.",
        ),
        "adaptive_asset_market": (
            "描述了一个由异质预期和策略更新驱动的资产市场。交易者根据不同预测规则形成价格预期、据此交易，并在观察绩效后调整或替换规则，因此市场价格会被参与者共同内生出来。",
            "reconstructs an adaptive asset market in which heterogeneous traders forecast prices with different rules, trade on those expectations, and revise strategies as performance changes.",
        ),
        "noise_arbitrage_market": (
            "描述了一个噪声交易者与套利者并存的金融市场。噪声交易者会因为情绪或错误信念推动价格偏离基本面，而套利者即使识别到错误定价，也会受到资金约束和逆势风险限制。",
            "reconstructs a financial market in which noise traders push prices away from fundamentals while arbitrageurs face funding limits and crowd risk when trading against mispricing.",
        ),
        "insider_market_making": (
            "描述了一个知情交易、噪声订单与做市定价共同作用的市场微观结构场景。知情交易者既想利用私有信息获利，又必须控制出手节奏以避免过快暴露信息。",
            "reconstructs a market-microstructure setting in which informed trading, noise order flow, and market making interact while the insider tries to exploit information without revealing it too quickly.",
        ),
        "exploration_exploitation_learning": (
            "描述了一个探索与利用之间的组织学习权衡。个体或团队既可以追求短期稳定回报，也可以尝试高不确定但可能带来长期突破的新方案，因此系统会在适应性与路径依赖之间摇摆。",
            "reconstructs an exploration-versus-exploitation learning problem in which teams balance short-run reliable returns against uncertain but potentially transformative new options.",
        ),
        "supply_chain_bullwhip": (
            "描述了一个多层供应链中的牛鞭效应场景。各节点只看得到局部库存与相邻订单，再叠加补货和运输延迟，小幅需求变化也可能被逐级放大成库存与缺货震荡。",
            "reconstructs a multi-stage supply-chain bullwhip setting in which each node observes only local inventory and neighboring orders, so small demand changes become amplified under delay.",
        ),
        "innovation_diffusion_marketing": (
            "描述了一个创新产品在市场中的采纳扩散过程。个体是否采纳既受广告等外部影响，也受口碑与可见采纳的内部影响，因此系统会形成从早期采纳到大众市场的扩散曲线。",
            "reconstructs an innovation-diffusion process in which adoption is driven by both external influence and social imitation, producing staged uptake across adopter groups.",
        ),
        "common_pool_governance": (
            "描述了一个带本地规则、监督和惩罚机制的公共资源治理过程。系统不仅关心资源是否被过度使用，也关心社区能否通过自组织规则稳定合作并维持资源再生。",
            "reconstructs a governed common-pool resource setting in which local rules, monitoring, and sanctions shape whether users can sustain cooperation and preserve regeneration.",
        ),
        "collective_action_free_rider": (
            "描述了一个典型的集体行动搭便车困境。群体中的每个人都能从公共目标中受益，但单个个体又都希望别人承担成本，因此系统会考察激励、惩罚和群体规模如何改变动员难度。",
            "reconstructs a collective-action free-rider dilemma in which everyone benefits from a public objective but each member prefers others to bear the mobilization cost.",
        ),
        "spatial_price_competition": (
            "描述了一个空间位置与价格共同决定竞争结果的市场。企业需要选择自己的位置和价格，而消费者会在距离成本与价格之间权衡，因此企业可能逐步向中间市场靠拢。",
            "reconstructs a spatial competition market in which firms choose positions and prices while consumers trade off distance and price, often creating pressure toward central clustering.",
        ),
        "reference_dependent_risk_choice": (
            "描述了一个参照点驱动的风险选择场景。个体对收益与损失的敏感度不对称，并且会受到问题表述方式影响，因此同一组客观选项在不同框架下可能触发不同风险偏好。",
            "reconstructs a reference-dependent risk-choice setting in which gains, losses, and framing change how agents evaluate safe versus risky options.",
        ),
        "endowment_statusquo_exchange": (
            "描述了一个禀赋效应与现状偏好共同作用的交易场景。个体一旦拥有某物，通常会抬高自己的保留估值，因此买卖双方的报价更容易错开，交易也更容易被阻滞。",
            "reconstructs an endowment-and-status-quo exchange setting in which ownership raises reservation value, widening the gap between willingness to accept and willingness to pay.",
        ),
    }

    if structure["type"] == "escalating_bidding":
        if is_cjk:
            return (
                f"{title or '该实验'} 描述了一个升级式竞价场景。参与者围绕一项拍卖目标不断加价，"
                "而关键规则是最高出价者和次高出价者都需要支付，这会制造沉没成本压力并诱发非合作升级。"
                f" 核心角色包括{ '、'.join(agent_labels[:4]) or '拍卖者与竞价者' }，每轮主要围绕"
                f"{ '、'.join(action_labels[:4]) or '继续加价、停止竞价' }等决策展开。"
            )[:700]
        return (
            f"{title or 'This experiment'} reconstructs an escalating auction setting in which participants compete for a prize while "
            "the highest bidder and the second-highest bidder both pay. The structure creates sunk-cost pressure and can drive "
            "noncooperative escalation. Core roles include "
            f"{', '.join(agent_labels[:4]) or 'an auctioneer and bidders'}, and each round centers on "
            f"{', '.join(action_labels[:4]) or 'raising the bid or stopping'}."
        )[:700]

    if structure["type"] == "threshold_adoption_process":
        if is_cjk:
            return (
                f"{title or '该实验'} 描述了一个基于阈值触发的集体行为扩散场景。"
                f"{_compact_excerpt(background, limit=180) if background else ''}"
                f" 每个智能体会根据自己观察到的已参与人数或参与比例，判断是否达到个人阈值；"
                "一旦外部参与规模跨过阈值，更多个体会被触发加入，从而形成扩散或级联。"
                f" 核心智能体包括{'、'.join(agent_labels[:6]) or '具有不同阈值的个体'}，"
                f"关键动作通常围绕{'、'.join(action_labels[:4]) or '加入行动、继续观望'}展开。"
            )[:700]
        return (
            f"{title or 'This experiment'} reconstructs a threshold-driven collective behavior process. "
            f"{_compact_excerpt(background, limit=180) if background else ''} "
            "Each actor observes how many others have already joined and compares that public participation level against an individual threshold. "
            "Once enough others participate, additional actors are triggered to join, producing diffusion or cascade dynamics. "
            f"Core agents include {', '.join(agent_labels[:6]) or 'individuals with heterogeneous thresholds'}, and the main actions revolve around "
            f"{', '.join(action_labels[:4]) or 'joining the action or waiting for more participation'}."
        )[:700]

    if structure["type"] in structure_templates:
        zh_body, en_body = structure_templates[structure["type"]]
        if is_cjk:
            base = f"{title or '该实验'} {zh_body}"
            if background:
                base += f" {_compact_excerpt(background, limit=150)}"
            if agent_labels:
                base += f" 核心智能体包括{'、'.join(agent_labels[:6])}。"
            if action_labels:
                base += f" 关键动作通常围绕{'、'.join(action_labels[:4])}展开。"
            return base[:700]
        base = f"{title or 'This experiment'} {en_body}"
        if background:
            base += f" {_compact_excerpt(background, limit=150)}"
        if agent_labels:
            base += f" Core agents include {', '.join(agent_labels[:6])}."
        if action_labels:
            base += f" The main actions revolve around {', '.join(action_labels[:4])}."
        return base[:700]

    if is_cjk:
        parts: list[str] = []
        if title:
            parts.append(f"{title} 描述了一个高时效、多角色协同的应急决策场景。")
        if background:
            parts.append(_compact_excerpt(background, limit=180))
        if agent_labels:
            parts.append(f"核心智能体包括{ '、'.join(agent_labels[:6]) }。")
        if action_labels:
            parts.append(f"系统需要围绕{ '、'.join(action_labels[:6]) }等关键动作持续协商、执行并根据现场反馈动态调整。")
        if stages:
            stage_titles = "、".join(
                str(item.get("title", "")).strip()
                for item in stages[:4]
                if isinstance(item, dict) and item.get("title")
            )
            if stage_titles:
                parts.append(f"整体流程覆盖{stage_titles}等阶段，强调分布式协作、快速重规划与闭环响应。")
        return " ".join(part for part in parts if part).strip()[:700]

    parts = []
    if title:
        parts.append(f"{title} is a time-critical multi-agent coordination scenario.")
    if background:
        parts.append(_compact_excerpt(background, limit=180))
    if agent_labels:
        parts.append(f"Core agents include {', '.join(agent_labels[:6])}.")
    if action_labels:
        parts.append(
            "The reconstructed action space centers on "
            f"{', '.join(action_labels[:6])} so the agents can coordinate, execute, and adapt as conditions change."
        )
    if stages:
        stage_titles = ", ".join(
            str(item.get("title", "")).strip()
            for item in stages[:4]
            if isinstance(item, dict) and item.get("title")
        )
        if stage_titles:
            parts.append(f"The source describes staged coordination across {stage_titles}.")
    return " ".join(part for part in parts if part).strip()[:700]


def _extract_research_question(text: str) -> str:
    cleaned = clean_text(text)
    structure = _detect_interaction_structure(cleaned)
    patterns = [
        r"(?:research question|question)\s*[:：]\s*([^\n]+)",
        r"(?:研究问题)\s*[:：]\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if structure["type"] == "escalating_bidding":
        return "How do pay-the-top-two auction rules create escalation and noncooperative bidding behavior?"
    return cleaned[:700]


def _extract_policy_text(text: str) -> str | None:
    sentences = _split_sentence_candidates(text)
    for sentence in sentences:
        if re.search(r"\b(policy|directive|rule|mandate)\b", sentence, re.IGNORECASE) or re.search(r"(政策|指令|规则|规定)", sentence):
            return sentence[:400]
    return sentences[0][:400] if sentences else None


def _infer_recommended_params(
    text: str,
    recommended_scenario_id: str | None,
    actions: list[dict[str, str]],
) -> dict[str, Any]:
    if not recommended_scenario_id:
        return {}

    cleaned = clean_text(text)
    lowered = cleaned.lower()
    params: dict[str, Any] = {}
    custom_structure = str(_detect_interaction_structure(cleaned).get("type", ""))

    if recommended_scenario_id == "public_goods":
        tokens_match = re.search(r"(\d+)\s+(tokens?|points?|credits?|units?)\s+(?:per round|each round|endowment)", lowered)
        if tokens_match:
            params["tokens_per_round"] = int(tokens_match.group(1))
            params["resource_name"] = tokens_match.group(2)
        multiplier_match = re.search(r"multiplier[^0-9]{0,20}(\d+(?:\.\d+)?)", lowered)
        if multiplier_match:
            params["multiplier"] = float(multiplier_match.group(1))
        deduction_match = re.search(r"(?:deduction|punishment|reduce)[^0-9]{0,25}(\d+)", lowered)
        if deduction_match:
            params["deduction_budget_per_phase"] = int(deduction_match.group(1))
        if "anonymous" in lowered or "匿名" in cleaned:
            params["deduction_anonymous"] = True

    elif recommended_scenario_id == "policy_erosion":
        policy_text = _extract_policy_text(cleaned)
        if policy_text:
            params["policy_text"] = policy_text
        count = _extract_agent_count(cleaned)
        if count:
            params["num_agents_per_tier"] = count
        if re.search(r"(distort|reinterpret|rewrite|扭曲|改写|再解释)", cleaned, re.IGNORECASE):
            params["cascade_mode"] = "distortion_cascade"

    elif recommended_scenario_id == "open_discussion":
        params["topic"] = _extract_research_question(cleaned)[:400]

    elif recommended_scenario_id == "council_chamber":
        params["proposal_text"] = _extract_policy_text(cleaned) or _extract_research_question(cleaned)[:400]
        rounds_match = re.search(r"(\d+)\s+(?:rounds?|轮)", cleaned, re.IGNORECASE)
        if rounds_match:
            params["max_rounds"] = int(rounds_match.group(1))
        threshold_match = re.search(r"(majority|threshold|supermajority|多数|门槛)[^0-9]{0,25}(\d+(?:\.\d+)?)", cleaned, re.IGNORECASE)
        if threshold_match:
            params["voting_threshold"] = float(threshold_match.group(2))

    elif recommended_scenario_id == "resource_scarcity":
        amount_match = re.search(r"(\d+)\s+(?:resources?|units?|items?)", lowered)
        if amount_match:
            params["resource_amount"] = int(amount_match.group(1))
        if "skewed" in lowered or "不均" in cleaned:
            params["initial_distribution"] = "skewed"

    elif recommended_scenario_id == "echo_chamber":
        if "polarized" in lowered or "极化" in cleaned:
            params["opinion_distribution"] = "polarized"
        if "balanced" in lowered or "均衡" in cleaned:
            params["opinion_distribution"] = "balanced"

    elif recommended_scenario_id == "social_norm_disruption":
        if "high status" in lowered:
            params["agent_status_distribution"] = "high_status"
        elif "low status" in lowered:
            params["agent_status_distribution"] = "low_status"
        elif "mixed" in lowered or "混合" in cleaned:
            params["agent_status_distribution"] = "mixed"

    elif recommended_scenario_id == "battle_of_the_sexes":
        if len(actions) >= 2:
            params["action_1_name"] = actions[0]["name"].replace("_", " ").title()
            params["action_1_description"] = actions[0]["description"]
            params["action_2_name"] = actions[1]["name"].replace("_", " ").title()
            params["action_2_description"] = actions[1]["description"]

    elif recommended_scenario_id == "stag_hunt":
        if len(actions) >= 2:
            params["action_1_name"] = actions[0]["name"].replace("_", " ").title()
            params["action_1_description"] = actions[0]["description"]
            params["action_2_name"] = actions[1]["name"].replace("_", " ").title()
            params["action_2_description"] = actions[1]["description"]

    elif recommended_scenario_id == "prisoners_dilemma":
        if len(actions) >= 2:
            params["action_1"] = actions[0]["name"].replace("_", " ").title()
            params["action_2"] = actions[1]["name"].replace("_", " ").title()

    elif recommended_scenario_id == "custom" and custom_structure == "proposal_response_exchange":
        stake_match = re.search(r"split\s+(\d+(?:\.\d+)?)\s*(?:dollars?|points?|tokens?)", lowered)
        if stake_match:
            params["stake_amount"] = float(stake_match.group(1))
        if "both receive nothing" in lowered or "both get nothing" in lowered:
            params["rejection_payoff"] = 0

    elif recommended_scenario_id == "custom" and custom_structure == "competitive_pressure_choice":
        resource_match = re.search(r"resource value[^0-9]{0,15}(\d+(?:\.\d+)?)", lowered)
        if resource_match:
            params["resource_value"] = float(resource_match.group(1))
        conflict_match = re.search(r"conflict cost[^0-9]{0,15}(\d+(?:\.\d+)?)", lowered)
        if conflict_match:
            params["conflict_cost"] = float(conflict_match.group(1))

    elif recommended_scenario_id == "custom" and custom_structure == "shared_target_threshold":
        threshold_match = re.search(r"(?:threshold|target)[^0-9]{0,20}(\d+(?:\.\d+)?)", lowered)
        if threshold_match:
            params["target_contribution"] = int(float(threshold_match.group(1)))
        loss_match = re.search(r"(?:loss probability|probability of loss)[^0-9]{0,20}(\d+(?:\.\d+)?)", lowered)
        if loss_match:
            params["loss_probability"] = float(loss_match.group(1))
        if "delegate" in lowered or "delegation" in lowered:
            params["enable_delegation"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "majority_visibility_pressure":
        majority_match = re.search(r"(\d+)\s+(?:other\s+)?(?:participants?|confederates?|group members?)", lowered)
        if majority_match:
            params["majority_size"] = int(majority_match.group(1))
        if "publicly" in lowered or "public response" in lowered:
            params["public_response"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "threshold_adoption_process":
        population_match = re.search(r"(\d+)\s+(?:citizens?|residents?|participants?|actors?)", lowered)
        if population_match:
            params["population_size"] = int(population_match.group(1))
        chinese_population_match = re.search(r"(\d+)\s*名(?:市民|居民|参与者|个体|成员)", text)
        if chinese_population_match:
            params["population_size"] = int(chinese_population_match.group(1))
        if "heterogeneous" in lowered:
            params["threshold_distribution"] = "heterogeneous"
        elif "uniform" in lowered:
            params["threshold_distribution"] = "uniform"
        elif "polarized" in lowered:
            params["threshold_distribution"] = "polarized"
        if any(term in lowered for term in ("neighbor adoption", "others adopt first", "adoption cascade")):
            params["cascade_trigger"] = "neighbor_adoption"
        if any(term in lowered for term in ("irreversible", "remain active once joined", "once state = 1")) or "不可逆" in text:
            params["irreversible_participation"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "attendance_capacity_avoidance":
        capacity_match = re.search(r"(?:less than|under|below|fewer than)\s+(\d+(?:\.\d+)?)\s*(?:%|percent)", lowered)
        if capacity_match:
            params["capacity_percent"] = float(capacity_match.group(1))
        bar_threshold_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:people|agents|participants).{0,40}(?:too crowded|crowded)", lowered)
        if bar_threshold_match:
            params["crowding_threshold"] = int(float(bar_threshold_match.group(1)))
        if any(term in lowered for term in ("history", "historical attendance", "past attendance")):
            params["prediction_source"] = "attendance_history"

    elif recommended_scenario_id == "custom" and custom_structure == "minority_side_choice":
        if any(term in lowered for term in ("two options", "two restaurants", "two directions", "两个选项", "两个餐厅")):
            params["choice_count"] = 2
        if any(term in lowered for term in ("minority wins", "less crowded side", "少数派获胜")):
            params["winner_rule"] = "minority_side"

    elif recommended_scenario_id == "custom" and custom_structure == "common_pool_extraction":
        if any(term in lowered for term in ("renewable", "regrow", "replenish")):
            params["resource_dynamics"] = "renewable"
        elif any(term in lowered for term in ("finite", "deplete", "depletion", "枯竭")):
            params["resource_dynamics"] = "finite_stock"
        if any(term in lowered for term in ("quota", "配额")):
            params["governance_mechanism"] = "quota"

    elif recommended_scenario_id == "custom" and custom_structure == "sanctioning_public_goods":
        if any(term in lowered for term in ("punish", "punishment", "sanction", "惩罚")):
            params["has_punishment_stage"] = True
        if any(term in lowered for term in ("free rider", "free-rider", "搭便车")):
            params["punishment_target"] = "free_rider"

    elif recommended_scenario_id == "custom" and custom_structure == "spatial_relocation_preference":
        if any(term in lowered for term in ("grid", "2d", "lattice", "二维网格", "网格")):
            params["space_type"] = "grid"
        if any(term in lowered for term in ("same type", "same neighbors", "同类邻居")):
            params["preference_basis"] = "similar_neighbors"

    elif recommended_scenario_id == "custom" and custom_structure == "sequential_information_cascade":
        if any(term in lowered for term in ("private signal", "私人信号")):
            params["private_signal"] = True
        if any(term in lowered for term in ("sequentially", "in order", "按顺序")):
            params["decision_order"] = "sequential"

    elif recommended_scenario_id == "custom" and custom_structure == "organizational_garbage_can":
        params["decision_streams"] = ["problems", "solutions", "participants", "choice_opportunities"]
        if any(term in lowered for term in ("meeting", "window", "会议", "窗口期")):
            params["choice_opportunity_mode"] = "episodic"

    elif recommended_scenario_id == "custom" and custom_structure == "weighted_opinion_averaging":
        if any(term in lowered for term in ("weighted average", "加权平均")):
            params["update_rule"] = "weighted_average"
        if any(term in lowered for term in ("network", "neighbors", "邻居", "网络")):
            params["interaction_graph"] = "neighbor_network"

    elif recommended_scenario_id == "custom" and custom_structure == "collective_motion_alignment":
        if any(term in lowered for term in ("noise", "噪声")):
            params["has_noise"] = True
        if any(term in lowered for term in ("fixed speed", "constant speed", "固定速度")):
            params["speed_mode"] = "fixed"

    elif recommended_scenario_id == "custom" and custom_structure == "resource_search_trade_ecology":
        if any(term in lowered for term in ("metabolism", "代谢率")):
            params["metabolism_enabled"] = True
        if any(term in lowered for term in ("vision", "视野")):
            params["vision_enabled"] = True
        if any(term in lowered for term in ("trade", "交易", "贸易")):
            params["trade_enabled"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "recruitment_switching":
        if any(term in lowered for term in ("two food sources", "two restaurants", "两个食物源", "两个餐厅")):
            params["option_count"] = 2
        if any(term in lowered for term in ("recruitment", "招募")):
            params["switch_driver"] = "social_recruitment"

    elif recommended_scenario_id == "custom" and custom_structure == "bystander_help_diffusion":
        if any(term in lowered for term in ("emergency", "urgent event", "紧急情况", "突发事件")):
            params["event_type"] = "emergency"
        bystander_match = re.search(r"(\d+)\s+(?:bystanders?|witnesses|observers)", lowered)
        if bystander_match:
            params["bystander_count"] = int(bystander_match.group(1))
        if any(term in lowered for term in ("diffusion of responsibility", "责任扩散")):
            params["responsibility_diffusion"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "authority_obedience_conflict":
        params["authority_present"] = True
        if any(term in lowered for term in ("withdraw", "退出成本", "exit cost")):
            params["exit_cost_present"] = True
        if any(term in lowered for term in ("moral", "道德", "discomfort", "不适")):
            params["moral_cost_present"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "intergroup_competition_superordinate_goal":
        if any(term in lowered for term in ("two groups", "两个群体", "group a", "group b")):
            params["group_count"] = 2
        if any(term in lowered for term in ("superordinate goal", "共同目标", "超级目标")):
            params["superordinate_goal"] = True
        if any(term in lowered for term in ("stage", "阶段一", "阶段二", "阶段三")):
            params["multi_stage_process"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "social_comparison_adjustment":
        if any(term in lowered for term in ("similar others", "similar peers", "相似他人", "相似同伴")):
            params["comparison_target"] = "similar_peers"
        if any(term in lowered for term in ("confidence", "self-evaluation", "自信", "自我评价")):
            params["updates_self_evaluation"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "liquidity_run_coordination":
        if any(term in lowered for term in ("deposit insurance", "存款保险")):
            params["deposit_insurance"] = True
        if any(term in lowered for term in ("liquidity", "流动性")):
            params["liquidity_constraint"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "asymmetric_quality_market":
        params["quality_information"] = "seller_private"
        if any(term in lowered for term in ("reputation", "certification", "认证", "声誉")):
            params["quality_signal_channel"] = "reputation_or_certification"
        if any(term in lowered for term in ("adverse selection", "逆向选择")):
            params["adverse_selection_risk"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "adaptive_asset_market":
        if any(term in lowered for term in ("trend following", "趋势跟随")):
            params["strategy_family_1"] = "trend_following"
        if any(term in lowered for term in ("mean reversion", "均值回归")):
            params["strategy_family_2"] = "mean_reversion"
        if any(term in lowered for term in ("fundamental", "基本面")):
            params["fundamental_anchor"] = True
        if any(term in lowered for term in ("switch", "replace strategy", "切换策略")):
            params["strategy_adaptation"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "noise_arbitrage_market":
        if any(term in lowered for term in ("funding constraint", "资金约束", "limits to arbitrage", "套利限制")):
            params["arbitrage_limit"] = True
        if any(term in lowered for term in ("sentiment", "情绪", "noise trader", "噪声交易者")):
            params["noise_pressure"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "insider_market_making":
        params["market_maker"] = True
        if any(term in lowered for term in ("continuous auction", "连续拍卖")):
            params["auction_mode"] = "continuous"
        if any(term in lowered for term in ("order flow", "订单流")):
            params["order_flow_pricing"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "exploration_exploitation_learning":
        if any(term in lowered for term in ("long-term", "长期", "breakthrough")):
            params["exploration_upside"] = "long_term"
        if any(term in lowered for term in ("short-term", "稳定收益", "short run")):
            params["exploitation_return"] = "short_term_stable"

    elif recommended_scenario_id == "custom" and custom_structure == "supply_chain_bullwhip":
        if any(term in lowered for term in ("retailer", "wholesaler", "distributor", "factory", "零售商", "批发商", "分销商", "工厂")):
            params["supply_chain_levels"] = 4
        if any(term in lowered for term in ("delay", "lead time", "延迟", "提前期")):
            params["feedback_delay"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "innovation_diffusion_marketing":
        if any(term in lowered for term in ("advertising", "media", "广告", "媒体")):
            params["external_influence"] = True
        if any(term in lowered for term in ("word of mouth", "mouth", "模仿", "口碑")):
            params["social_imitation"] = True
        if any(term in lowered for term in ("innovators", "early adopters", "innovator", "early majority", "late majority", "laggards")):
            params["adopter_categories"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "common_pool_governance":
        if any(term in lowered for term in ("monitor", "监督", "monitoring")):
            params["monitoring_enabled"] = True
        if any(term in lowered for term in ("sanction", "惩罚", "graduated sanctions")):
            params["sanction_enabled"] = True
        if any(term in lowered for term in ("regeneration", "renewable", "再生")):
            params["resource_regeneration"] = True

    elif recommended_scenario_id == "custom" and custom_structure == "collective_action_free_rider":
        if any(term in lowered for term in ("selective incentive", "选择性激励")):
            params["selective_incentives"] = True
        if any(term in lowered for term in ("large group", "大群体")):
            params["group_scale"] = "large"

    elif recommended_scenario_id == "custom" and custom_structure == "spatial_price_competition":
        params["market_space"] = "linear"
        if any(term in lowered for term in ("two firms", "两家店", "两家企业")):
            params["firm_count"] = 2
        if any(term in lowered for term in ("transport cost", "distance cost", "运输成本", "距离成本")):
            params["consumer_cost_basis"] = "distance_plus_price"

    elif recommended_scenario_id == "custom" and custom_structure == "reference_dependent_risk_choice":
        if any(term in lowered for term in ("loss aversion", "损失厌恶")):
            params["loss_aversion"] = True
        if any(term in lowered for term in ("framing", "frame", "框架效应")):
            params["framing_effect"] = True
        if any(term in lowered for term in ("reference point", "参照点")):
            params["reference_point"] = "explicit"

    elif recommended_scenario_id == "custom" and custom_structure == "endowment_statusquo_exchange":
        if any(term in lowered for term in ("wta", "willingness to accept", "愿受价格")):
            params["seller_valuation_mode"] = "wta"
        if any(term in lowered for term in ("wtp", "willingness to pay", "愿付价格")):
            params["buyer_valuation_mode"] = "wtp"
        if any(term in lowered for term in ("status quo", "现状偏好")):
            params["status_quo_bias"] = True

    elif recommended_scenario_id == "coordination_game":
        if actions:
            params["choices"] = ", ".join(
                action["name"].replace("_", " ").title() for action in actions[:6]
            )
        if re.search(r"(same|match|一致|相同)", cleaned, re.IGNORECASE):
            params["goal"] = "match"
        elif re.search(r"(different|differ|不同)", cleaned, re.IGNORECASE):
            params["goal"] = "differ"

    elif recommended_scenario_id == "contagion":
        initial_match = re.search(r"(\d+)\s+(?:initially\s+)?infected", lowered)
        if initial_match:
            params["initial_infected"] = int(initial_match.group(1))
        recovery_match = re.search(r"(?:recover(?:y|ed)?(?: after)?|恢复)[^0-9]{0,20}(\d+)\s+(?:turns?|rounds?|days?|轮|天)", cleaned, re.IGNORECASE)
        if recovery_match:
            params["recovery_turns"] = int(recovery_match.group(1))
        grid_match = re.search(r"(\d+)\s*[x×]\s*(\d+)\s+grid", lowered)
        if grid_match and grid_match.group(1) == grid_match.group(2):
            params["grid_size"] = int(grid_match.group(1))

    elif (
        custom_structure == "escalating_bidding"
        or "auction" in lowered
        or ("highest bidder" in lowered and "second highest bidder" in lowered)
    ):
        if "dollar" in lowered:
            params["prize_value"] = 1.0
            params["currency"] = "dollar"
        increment_value: int | None = None
        increment_match = re.search(r"(?:multiples?\s+of|increments?\s+of|increments?\s+by)\s+(\d+)\s*cents?", lowered)
        if increment_match:
            increment_value = int(increment_match.group(1))
        else:
            increment_match = re.search(r"(\d+)[-\s]*cent\s+increments?", lowered)
            if increment_match:
                increment_value = int(increment_match.group(1))
            else:
                increment_match = re.search(r"\b(\d+)\s*cents?\b", lowered)
                if increment_match:
                    increment_value = int(increment_match.group(1))
        if increment_value is not None:
            params["bid_increment_cents"] = increment_value
        if (
            re.search(
                r"(?:both\s+)?the?\s*highest\s+bidder.{0,120}second[\s-]?highest\s+bidder.{0,120}\bpay\b",
                lowered,
                re.DOTALL,
            )
            or re.search(
                r"second[\s-]?highest\s+bidder.{0,120}highest\s+bidder.{0,120}\bpay\b",
                lowered,
                re.DOTALL,
            )
            or ("highest bidder" in lowered and "second highest bidder" in lowered and "pay" in lowered)
        ):
            params["pay_top_two"] = True
        if re.search(r"\btwo bidders\b", lowered):
            params["bidder_count"] = 2

    return params


def _infer_schema_driven_params(semantic_schema: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    title = str(semantic_schema.get("title") or "").strip()
    participants = semantic_schema.get("participants") or []
    choices = semantic_schema.get("choices") or []
    topology = semantic_schema.get("interaction_topology") or []
    information = semantic_schema.get("information_structure") or []
    outcomes = semantic_schema.get("outcomes") or []
    constraints = semantic_schema.get("constraints") or []
    interaction_structure = semantic_schema.get("interaction_structure") or {}

    if title:
        params["source_title"] = title
    if participants:
        params["participant_roles"] = [str(item.get("label", "")).strip() for item in participants if isinstance(item, dict) and item.get("label")]
    if choices:
        params["decision_action_labels"] = [str(item.get("name", "")).strip() for item in choices if isinstance(item, dict) and item.get("name")]
    if topology:
        params["interaction_topology_hint"] = str(topology[0])[:300]
    if information:
        params["information_structure_hint"] = str(information[0])[:300]
    if outcomes:
        params["outcome_focus"] = [str(item).strip() for item in outcomes[:3] if str(item).strip()]
    if constraints:
        params["constraint_hint"] = str(constraints[0])[:300]
    if interaction_structure:
        params["interaction_structure_hint"] = str(interaction_structure.get("type", ""))[:120]
    return params


def _find_snippet(text: str, term: str) -> str | None:
    if not term:
        return None
    lowered = text.lower()
    idx = lowered.find(term.lower())
    if idx == -1:
        return None
    start = max(0, idx - 90)
    end = min(len(text), idx + len(term) + 150)
    return clean_text(text[start:end])


def _build_evidence(
    text: str,
    sections: list[dict[str, Any]],
    actions: list[dict[str, str]],
    variables: list[str],
    recommended_scenario_id: str | None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for variable in variables[:4]:
        snippet = _find_snippet(text, variable)
        if snippet:
            evidence.append({"label": _localize_text(f"Variable: {variable}", f"变量：{variable}", language), "snippet": snippet, "section": None})
    for action in actions[:4]:
        display = action.get("name", "")
        snippet = _find_snippet(text, display.replace("_", " "))
        if not snippet:
            for library_item in CUSTOM_ACTION_LIBRARY:
                if library_item.get("name") != display:
                    continue
                for pattern in library_item.get("patterns", [])[:5]:
                    simple = re.sub(r"[\\\[\]\(\)\?\+\*\|]", "", str(pattern))
                    snippet = _find_snippet(text, simple)
                    if snippet:
                        break
                if snippet:
                    break
        if snippet:
            evidence.append({"label": _localize_text(f"Action: {display}", f"动作：{display}", language), "snippet": snippet, "section": None})
    if recommended_scenario_id:
        for keyword in SCENARIO_KEYWORDS.get(recommended_scenario_id, [])[:6]:
            snippet = _find_snippet(text, keyword)
            if snippet:
                evidence.append({"label": _localize_text(f"Template clue: {recommended_scenario_id}", f"模板线索：{recommended_scenario_id}", language), "snippet": snippet, "section": None})
                break
    if not evidence and sections:
        evidence.append({"label": _localize_section_title(sections[0]["title"], language), "snippet": sections[0]["excerpt"], "section": _localize_section_title(sections[0]["title"], language)})
    return evidence[:8]


def heuristic_analysis(
    text: str,
    suggestions: list[TemplateSuggestion],
    language: str | None = None,
    *,
    source_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cleaned = _strip_document_noise(clean_text(text))
    sections = _sanitize_source_sections(source_sections) if source_sections else split_source_sections(cleaned)
    recognition_text = _build_priority_text(cleaned, sections)
    outline = build_source_outline(cleaned)
    semantic_schema = build_semantic_schema(cleaned, sections, outline, language=language)
    if not cleaned:
        return {
            "scenario_description": "",
            "settings": [],
            "actions": [],
            "agents": [],
            "key_variables": [],
            "assumptions": [],
            "missing_information": [],
            "evidence": [],
            "recommended_scenario_id": "custom",
            "recommended_scenario_reason": "",
            "recommendation_confidence": 0.0,
            "review_required": True,
            "recommended_params": {},
            "source_sections": [],
        }

    preferred = suggestions[0].id if suggestions else "custom"
    top_score = suggestions[0].score if suggestions else 0.0
    runner_up_score = suggestions[1].score if len(suggestions) > 1 else 0.0
    score_gap = top_score - runner_up_score
    custom_structure = str((semantic_schema.get("interaction_structure") or {}).get("type") or _detect_interaction_structure(cleaned, outline).get("type", ""))
    detected_family = _structure_family(custom_structure)
    preferred_family = SCENARIO_STRUCTURE_HINTS.get(preferred, "")
    structure_conflict = bool(
        preferred != "custom"
        and preferred_family
        and detected_family not in {"", "open_ended_custom"}
        and detected_family != preferred_family
    )
    custom_first_structure = custom_structure in CUSTOM_STRUCTURE_ACTIONS
    custom_first_override = bool(
        preferred != "custom"
        and custom_first_structure
        and top_score < 0.24
    )
    family_supported_match = bool(
        preferred != "custom"
        and preferred_family
        and detected_family == preferred_family
        and not custom_first_structure
        and top_score >= 0.09
        and score_gap >= 0.05
    )
    recommended_scenario_id = preferred if (top_score >= 0.11 and (score_gap >= 0.025 or top_score >= 0.43) or family_supported_match) and not structure_conflict and not custom_first_override else "custom"
    recommendation_confidence = round(top_score * (0.55 if structure_conflict else 1.0), 3)
    review_required = recommended_scenario_id == "custom" or top_score < 0.38 or score_gap < 0.08 or structure_conflict or custom_first_override

    sentences = _split_sentence_candidates(cleaned)
    actions = (
        _default_actions_for_scenario(recommended_scenario_id, language)
        if recommended_scenario_id != "custom"
        else semantic_schema.get("choices") or _extract_actions_from_text(recognition_text, recommended_scenario_id, outline, language)
    )
    if (
        recommended_scenario_id == "custom"
        and re.search(r"(available actions?|action space|action rules?|动作包括|候选动作|可选动作|行动规则|智能体动作|操作包括)\s*[:：]?\s*", cleaned, re.IGNORECASE)
    ):
        explicit_actions = _extract_actions_from_text(cleaned, recommended_scenario_id, outline, language)
        if len(explicit_actions) >= 2:
            actions = explicit_actions
    actions = _filter_noisy_actions(actions, language=language)
    if recommended_scenario_id == "custom":
        structure_actions = _default_actions_for_structure(custom_structure, language)
        if structure_actions and (not actions or len(actions) <= 1):
            actions = structure_actions
        elif structure_actions and any(_looks_like_noise_label(item.get("name", "")) for item in actions):
            actions = structure_actions
    key_variables = semantic_schema.get("key_variables") or _extract_key_variables(cleaned)
    agents = (
        _default_agents_for_scenario(recommended_scenario_id, language)
        if recommended_scenario_id != "custom"
        else semantic_schema.get("participants") or _extract_agents(recognition_text, recommended_scenario_id)
    )
    agents = _filter_noisy_agents(agents, language=language)
    if recommended_scenario_id == "custom":
        structure_agents = _default_agents_for_structure(custom_structure, language)
        if structure_agents and (not agents or len(agents) <= 1):
            agents = structure_agents
        elif structure_agents and any(_looks_like_noise_label(item.get("label", "")) for item in agents):
            agents = structure_agents
        if custom_structure == "threshold_adoption_process" and (
            any(term in cleaned.lower() for term in ("citizen", "resident", "residents"))
            or any(term in cleaned for term in ("市民", "居民", "公民"))
        ):
            extracted_threshold_agents = _filter_noisy_agents(_extract_agents(cleaned, recommended_scenario_id), language=language)
            specialized_labels = {
                str(item.get("label", "")).strip().lower()
                for item in extracted_threshold_agents
                if isinstance(item, dict)
            }
            if extracted_threshold_agents and specialized_labels - {"participants"}:
                agents = extracted_threshold_agents
    scenario_description = _build_custom_scenario_description(cleaned, outline, actions, agents, language) or " ".join(sentences[:3]).strip() or cleaned[:500]
    param_source_text = cleaned if recommended_scenario_id == "custom" else recognition_text
    recommended_params = _infer_recommended_params(param_source_text, recommended_scenario_id, actions)
    for key, value in _infer_schema_driven_params(semantic_schema).items():
        recommended_params.setdefault(key, value)

    assumptions: list[str] = []
    if recommended_scenario_id != "custom" and review_required:
        assumptions.append(_localize_text("Template recommendation is plausible but still needs review because nearby templates scored similarly or the evidence is incomplete.", "当前模板推荐基本合理，但由于相近模板得分接近或证据不完整，仍建议人工复核。", language))
    if structure_conflict:
        assumptions.append(
            _localize_text(
                f"The top preset candidate looked lexically similar, but its interaction family conflicts with the inferred {detected_family.replace('_', ' ')} structure, so the draft stays custom.",
                f"最高分预设在词面上有一定相似性，但它与系统推断出的“{_localize_structure_label(custom_structure, language)}”结构族不一致，因此草案保持为自定义模式。",
                language,
            )
        )
    if custom_first_override:
        assumptions.append(
            _localize_text(
                "The extracted structure matches a custom-first interaction pattern more strongly than any preset template, so the draft stays in custom mode unless the preset evidence becomes much stronger.",
                "提取出的结构更像一个应优先保留为自定义的交互模式，而不是现有预设模板，因此在预设证据显著更强之前，草案会保持为自定义模式。",
                language,
            )
        )
    if not semantic_schema.get("interaction_topology"):
        assumptions.append(_localize_text("No explicit network structure was found; the researcher may need to configure the interaction network manually.", "原文没有明确给出网络结构，研究者可能需要手动配置交互网络。", language))
    if not re.search(r"(\d+)\s+(rounds?|轮)", cleaned, re.IGNORECASE):
        assumptions.append(_localize_text("No explicit round count was found in the source text.", "原文没有明确给出轮次数量。", language))

    missing_information: list[str] = []
    if not actions:
        missing_information.append(_localize_text("The source text does not clearly specify the per-round action space.", "原文没有清楚说明每轮可执行的动作空间。", language))
    if not _extract_agent_count(cleaned) and not semantic_schema.get("participants"):
        missing_information.append(_localize_text("The source text does not clearly specify participant count or group size.", "原文没有清楚说明参与者数量或群组规模。", language))
    if not key_variables:
        missing_information.append(_localize_text("Key experimental variables were not explicitly stated and may need manual refinement.", "原文没有明确列出关键实验变量，可能需要手动补充。", language))
    if recommended_scenario_id == "custom":
        missing_information.append(_localize_text("No strong preset template match was found, so the draft remains in custom mode.", "没有足够强的预设模板匹配，因此草案保持为自定义模式。", language))
    elif review_required:
        missing_information.append(_localize_text("A preset candidate was found, but the mapping is not fully certain; inspect the suggested template list before continuing.", "系统找到了可能的预设模板，但映射仍不完全确定；继续前请检查候选模板列表。", language))
    if structure_conflict:
        missing_information.append(
            _localize_text(
                "The inferred interaction structure conflicts with the best preset candidate, so a manual template decision is still needed.",
                "系统推断的交互结构与最高分预设候选存在冲突，因此仍需要你手动判断是否映射到预设模板。",
                language,
            )
        )
    if not semantic_schema.get("payoff_rules"):
        missing_information.append(_localize_text("The source text does not clearly specify the payoff, loss, or feedback rule.", "原文没有清楚说明收益、损失或反馈规则。", language))

    settings = [
        {"key": "research_question", "value": semantic_schema.get("research_goal") or _extract_research_question(cleaned), "reason": _localize_text("Captured from the provided source text.", "从提供的原文中提取。", language)},
        {"key": "source_type", "value": "research_text", "reason": _localize_text("Marks this experiment draft as reconstructed from uploaded text.", "标记该实验草案来自上传文本的重建。", language)},
    ]
    if outline.get("title"):
        settings.append(
            {
                "key": "scenario_title",
                "value": str(outline["title"]),
                "reason": _localize_text("Detected from the source title field.", "从原文标题字段中识别。", language),
            }
        )
    if semantic_schema.get("payoff_rules"):
        settings.append(
            {
                "key": "payoff_rule",
                "value": " ".join(str(item) for item in semantic_schema["payoff_rules"][:2])[:500],
                "reason": _localize_text("Summarized from explicit payoff, loss, or payment rules in the source.", "根据原文中的收益、损失或支付规则总结。", language),
            }
        )
    if semantic_schema.get("constraints"):
        settings.append(
            {
                "key": "constraints",
                "value": " ".join(str(item) for item in semantic_schema["constraints"][:2])[:500],
                "reason": _localize_text("Summarized from explicit constraints or termination conditions.", "根据原文中的约束或终止条件总结。", language),
            }
        )
    if semantic_schema.get("information_structure"):
        settings.append(
            {
                "key": "information_structure",
                "value": " ".join(str(item) for item in semantic_schema["information_structure"][:2])[:500],
                "reason": _localize_text("Summarized from the information visibility described in the source.", "根据原文中的信息可见性描述总结。", language),
            }
        )
    if semantic_schema.get("interaction_topology"):
        settings.append(
            {
                "key": "interaction_topology",
                "value": " ".join(str(item) for item in semantic_schema["interaction_topology"][:2])[:500],
                "reason": _localize_text("Summarized from the source interaction topology.", "根据原文中的交互拓扑总结。", language),
            }
        )
    if custom_structure and custom_structure != "generic":
        settings.append(
            {
                "key": "interaction_structure",
                "value": str((semantic_schema.get("interaction_structure") or {}).get("display_label") or _localize_structure_label(custom_structure, language)),
                "reason": _localize_text("Recovered from the inferred interaction structure.", "根据推断出的交互结构恢复。", language),
            }
        )
    if recommended_scenario_id != "custom":
        settings.append(
            {
                "key": "recommended_scenario_id",
                "value": recommended_scenario_id,
                "reason": _localize_text("Best deterministic template match for the extracted experimental structure.", "这是对提取后实验结构的最佳确定性模板匹配。", language),
            }
        )

    localized_actions: list[dict[str, str]] = []
    for item in (actions or DEFAULT_SCENARIO_ACTIONS.get(recommended_scenario_id, DEFAULT_SCENARIO_ACTIONS["open_discussion"])):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", ""))
        if "Explicit action inventory recovered from the source text" in description or "从原文的明确动作清单中恢复的动作" in description:
            localized_actions.append({"name": str(item.get("name", "")), "description": description})
            continue
        localized_actions.append(_localize_action_item(item.get("name", ""), description, language))

    localized_sections = [
        {
            **section,
            "title": _localize_section_title(str(section.get("title", "")), language),
        }
        for section in sections
    ]

    return {
        "scenario_description": scenario_description,
        "settings": settings,
        "actions": localized_actions,
        "agents": agents,
        "key_variables": key_variables,
        "assumptions": _dedupe_strings(assumptions, limit=6),
        "missing_information": _dedupe_strings(missing_information, limit=6),
        "evidence": _build_evidence(cleaned, localized_sections, localized_actions, key_variables, recommended_scenario_id, language),
        "evidence_by_field": semantic_schema.get("evidence_map") or {},
        "recommended_scenario_id": recommended_scenario_id,
        "recommended_scenario_reason": suggestions[0].reason if suggestions and recommended_scenario_id != "custom" else _localize_text("No strong preset match was found; keep this as a custom scenario.", "没有足够强的预设匹配，保留为自定义场景。", language),
        "recommendation_confidence": recommendation_confidence,
        "review_required": review_required,
        "recommended_params": recommended_params,
        "source_sections": localized_sections,
    }


def build_llm_analysis_scaffold(
    text: str,
    scenarios: list[dict[str, Any]],
    *,
    language: str | None = None,
    top_k: int = 3,
    source_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cleaned = _strip_document_noise(clean_text(text))
    sections = _sanitize_source_sections(source_sections) if source_sections else split_source_sections(cleaned)
    recognition_text = _build_priority_text(cleaned, sections)
    outline = build_source_outline(cleaned)
    semantic_schema = build_semantic_schema(cleaned, sections, outline, language=language)
    template_suggestions = suggest_templates(
        recognition_text,
        scenarios,
        top_k=top_k,
        source_sections=sections,
        semantic_schema=semantic_schema,
        language=language,
    )
    helper_hints = heuristic_analysis(recognition_text, template_suggestions, language=language, source_sections=sections)

    return {
        "cleaned_text": cleaned,
        "recognition_text": recognition_text,
        "source_sections": sections,
        "source_outline": outline,
        "semantic_schema": semantic_schema,
        "template_suggestions": template_suggestions,
        "evidence_packet": {
            "title": semantic_schema.get("title") or _extract_document_title_candidate(cleaned),
            "research_goal": semantic_schema.get("research_goal"),
            "setting": semantic_schema.get("setting"),
            "priority_text": recognition_text[:12000],
            "source_sections": sections[:8],
            "document_quality": {
                "section_count": len(sections),
                "title_detected": bool(semantic_schema.get("title")),
                "contains_structured_outline": bool(outline.get("roles") or outline.get("stages")),
                "structure_family": str((semantic_schema.get("interaction_structure") or {}).get("family", "")),
            },
        },
        "helper_hints": {
            "candidate_actions": helper_hints.get("actions", []),
            "candidate_agents": helper_hints.get("agents", []),
            "candidate_settings": helper_hints.get("settings", []),
            "candidate_parameters": helper_hints.get("recommended_params", {}),
            "assumptions": helper_hints.get("assumptions", []),
            "missing_information": helper_hints.get("missing_information", []),
            "evidence": helper_hints.get("evidence", []),
            "interaction_structure": semantic_schema.get("interaction_structure") or {},
            "ontology": semantic_schema.get("ontology") or {},
        },
        "evidence_by_field": semantic_schema.get("evidence_map") or {},
    }


def _normalize_evidence_by_field(raw: Any, fallback: dict[str, Any] | None = None) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not key:
                continue
            if isinstance(value, list):
                items = _dedupe_strings([str(item) for item in value], limit=4)
            else:
                items = _dedupe_strings([str(value)], limit=4)
            if items:
                normalized[str(key)] = items
    if normalized:
        return normalized
    if isinstance(fallback, dict):
        for key, value in fallback.items():
            if isinstance(value, list):
                items = _dedupe_strings([str(item) for item in value], limit=4)
                if items:
                    normalized[str(key)] = items
    return normalized


def _cards_from_evidence_map(evidence_by_field: dict[str, list[str]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for key, snippets in evidence_by_field.items():
        for snippet in snippets[:2]:
            cards.append(
                {
                    "label": key.replace("_", " ").strip().title() or "Evidence",
                    "snippet": snippet[:500],
                    "section": None,
                }
            )
        if len(cards) >= 8:
            break
    return cards[:8]


def _normalize_template_choice(
    raw_choice: Any,
    template_suggestions: list[TemplateSuggestion],
) -> tuple[str, float]:
    choice = str(raw_choice or "custom").strip() or "custom"
    valid_ids = {item.id for item in template_suggestions}
    if choice == "custom":
        return "custom", 0.0
    if choice in valid_ids:
        matched = next((item for item in template_suggestions if item.id == choice), None)
        return choice, float(matched.score if matched else 0.0)
    return "custom", 0.0


def normalize_llm_analysis_output(
    primary: dict[str, Any],
    *,
    semantic_schema: dict[str, Any],
    source_sections: list[dict[str, Any]],
    template_suggestions: list[TemplateSuggestion],
) -> dict[str, Any]:
    if not isinstance(primary, dict):
        raise ValueError(T("error.ai_scientist.model_analysis_not_object"))

    scenario_description = str(primary.get("scenario_description") or primary.get("scenario_summary") or "").strip()
    settings = primary.get("settings") or primary.get("setting_candidates") or []
    actions = primary.get("actions") or primary.get("choices") or []
    agents = primary.get("agents") or primary.get("participants") or []
    key_variables = primary.get("key_variables") or semantic_schema.get("key_variables") or []
    assumptions = primary.get("assumptions") or []
    missing_information = primary.get("missing_information") or []
    evidence = primary.get("evidence") or []
    evidence_by_field = _normalize_evidence_by_field(primary.get("evidence_by_field"), semantic_schema.get("evidence_map"))
    recommended_scenario_id, candidate_score = _normalize_template_choice(
        primary.get("recommended_scenario_id") or primary.get("template_id"),
        template_suggestions,
    )
    recommended_scenario_reason = str(primary.get("recommended_scenario_reason") or primary.get("template_reason") or "").strip()
    recommendation_confidence = primary.get("recommendation_confidence")
    if recommendation_confidence is None:
        recommendation_confidence = candidate_score
    try:
        recommendation_confidence = max(0.0, min(1.0, float(recommendation_confidence)))
    except Exception:
        recommendation_confidence = candidate_score
    review_required = bool(primary.get("review_required", True))
    recommended_params = primary.get("recommended_params") or {}
    source_sections_payload = primary.get("source_sections") or source_sections

    if not isinstance(settings, list):
        settings = []
    if not isinstance(actions, list):
        actions = []
    if not isinstance(agents, list):
        agents = []
    if not isinstance(key_variables, list):
        key_variables = []
    if not isinstance(assumptions, list):
        assumptions = []
    if not isinstance(missing_information, list):
        missing_information = []
    if not isinstance(evidence, list):
        evidence = []
    if not isinstance(recommended_params, dict):
        recommended_params = {}
    if not isinstance(source_sections_payload, list):
        source_sections_payload = source_sections

    normalized_settings: list[dict[str, str]] = []
    for item in settings:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key:
            continue
        normalized_settings.append(
            {
                "key": key,
                "value": value,
                "reason": str(item.get("reason", "")).strip(),
            }
        )

    normalized_actions: list[dict[str, str]] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("label") or "").strip()
        if not name:
            continue
        normalized_actions.append(
            {
                "name": re.sub(r"\s+", "_", name.lower()).strip("_") or name,
                "description": str(item.get("description", name)).strip() or name,
            }
        )

    normalized_agents: list[dict[str, Any]] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            continue
        try:
            count = max(1, int(item.get("count", 1)))
        except Exception:
            count = 1
        normalized_agents.append(
            {
                "label": label,
                "description": str(item.get("description", "")).strip() or f"Role description for {label}.",
                "count": count,
            }
        )

    normalized_variables = _dedupe_strings([str(item) for item in key_variables], limit=10)
    normalized_assumptions = _dedupe_strings([str(item) for item in assumptions], limit=8)
    normalized_missing = _dedupe_strings([str(item) for item in missing_information], limit=8)

    normalized_evidence: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        normalized_evidence.append(
            {
                "label": str(item.get("label", "Evidence")).strip() or "Evidence",
                "snippet": snippet[:500],
                "section": str(item.get("section", "")).strip() or None,
            }
        )
    if not normalized_evidence:
        normalized_evidence = _cards_from_evidence_map(evidence_by_field)

    normalized_sections: list[dict[str, Any]] = []
    for item in source_sections_payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "Excerpt"
        excerpt = str(item.get("excerpt", "")).strip()
        if not excerpt:
            continue
        normalized_sections.append(
            {
                "id": str(item.get("id", title)).strip() or title,
                "title": title,
                "excerpt": excerpt[:700],
                "page": item.get("page"),
            }
        )

    return {
        "scenario_description": scenario_description,
        "settings": normalized_settings,
        "actions": normalized_actions,
        "agents": normalized_agents,
        "key_variables": normalized_variables,
        "assumptions": normalized_assumptions,
        "missing_information": normalized_missing,
        "evidence": normalized_evidence,
        "evidence_by_field": evidence_by_field,
        "recommended_scenario_id": recommended_scenario_id,
        "recommended_scenario_reason": recommended_scenario_reason,
        "recommendation_confidence": recommendation_confidence,
        "review_required": review_required,
        "recommended_params": recommended_params,
        "source_sections": normalized_sections,
    }


def _looks_like_noise_label(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    if not value:
        return True
    if len(value) > 140:
        return True
    if "http" in lowered or "doi.org" in lowered:
        return True
    if re.search(r"\b(journal|science|review|introduction|results|discussion|conclusion|references)\b", lowered):
        return True
    if re.search(r"\b(dynamics|definition|theorem|lemma|appendix|abstract|keywords)\b", lowered):
        return True
    if re.search(r"\b\d{4}\b", lowered) and re.search(r"\bet al\b", lowered):
        return True
    if ";" in value or "|" in value:
        return True
    if any(mark in value for mark in (".", "。", "!", "！", "?", "？")) and len(value.split()) > 4:
        return True
    if ":" in value and len(value.split()) > 5:
        return True
    if re.search(r"\b(has|have|are|were|contains|includes)\b", lowered) and len(value.split()) > 6:
        return True
    if len(value.split()) > 9:
        return True
    if re.match(r"^\d+[\.\)]", value):
        return True
    return False


def collect_analysis_quality_issues(
    analysis: dict[str, Any],
    *,
    template_suggestions: list[TemplateSuggestion],
) -> list[str]:
    issues: list[str] = []
    if not str(analysis.get("scenario_description") or "").strip():
        issues.append("scenario_description_missing")
    actions = analysis.get("actions") or []
    if not actions:
        issues.append("actions_missing")
    if len(actions) > 0 and any(_looks_like_noise_label(item.get("name", "")) for item in actions if isinstance(item, dict)):
        issues.append("actions_contain_noise")
    agents = analysis.get("agents") or []
    if not agents:
        issues.append("agents_missing")
    if len(agents) > 0 and any(_looks_like_noise_label(item.get("label", "")) for item in agents if isinstance(item, dict)):
        issues.append("agents_contain_noise")
    evidence = analysis.get("evidence") or []
    if not evidence and not analysis.get("evidence_by_field"):
        issues.append("evidence_missing")
    recommended = str(analysis.get("recommended_scenario_id") or "custom").strip() or "custom"
    valid_ids = {item.id for item in template_suggestions}
    if recommended != "custom" and recommended not in valid_ids:
        issues.append("invalid_template_choice")
    return issues


def merge_analysis(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    scenario_description = str(primary.get("scenario_description") or fallback.get("scenario_description") or "").strip()
    settings = primary.get("settings") or fallback.get("settings") or []
    actions = primary.get("actions") or fallback.get("actions") or []
    agents = primary.get("agents") or fallback.get("agents") or []
    key_variables = primary.get("key_variables") or fallback.get("key_variables") or []
    assumptions = primary.get("assumptions") or fallback.get("assumptions") or []
    missing_information = primary.get("missing_information") or fallback.get("missing_information") or []
    evidence = primary.get("evidence") or fallback.get("evidence") or []
    recommended_scenario_id = str(primary.get("recommended_scenario_id") or fallback.get("recommended_scenario_id") or "custom").strip() or "custom"
    recommended_scenario_reason = str(primary.get("recommended_scenario_reason") or fallback.get("recommended_scenario_reason") or "").strip()
    recommendation_confidence = float(primary.get("recommendation_confidence") or fallback.get("recommendation_confidence") or 0.0)
    review_required = bool(primary.get("review_required") if primary.get("review_required") is not None else fallback.get("review_required"))
    recommended_params = primary.get("recommended_params") or fallback.get("recommended_params") or {}
    source_sections = primary.get("source_sections") or fallback.get("source_sections") or []

    if not isinstance(settings, list):
        settings = fallback.get("settings", [])
    if not isinstance(actions, list):
        actions = fallback.get("actions", [])
    if not isinstance(agents, list):
        agents = fallback.get("agents", [])
    if not isinstance(key_variables, list):
        key_variables = fallback.get("key_variables", [])
    if not isinstance(assumptions, list):
        assumptions = fallback.get("assumptions", [])
    if not isinstance(missing_information, list):
        missing_information = fallback.get("missing_information", [])
    if not isinstance(evidence, list):
        evidence = fallback.get("evidence", [])
    if not isinstance(recommended_params, dict):
        recommended_params = fallback.get("recommended_params", {})
    if not isinstance(source_sections, list):
        source_sections = fallback.get("source_sections", [])

    normalized_settings: list[dict[str, str]] = []
    for item in settings:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key:
            continue
        normalized_settings.append(
            {"key": key, "value": value, "reason": str(item.get("reason", "")).strip()}
        )

    normalized_actions: list[dict[str, str]] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        normalized_actions.append(
            {
                "name": re.sub(r"\s+", "_", name.lower()).strip("_") or name,
                "description": str(item.get("description", name)).strip() or name,
            }
        )

    normalized_agents: list[dict[str, Any]] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        try:
            count = max(1, int(item.get("count", 1)))
        except Exception:
            count = 1
        normalized_agents.append(
            {
                "label": label,
                "description": str(item.get("description", "")).strip() or f"Role description for {label}.",
                "count": count,
            }
        )

    normalized_variables = _dedupe_strings([str(item) for item in key_variables], limit=10)
    normalized_assumptions = _dedupe_strings([str(item) for item in assumptions], limit=8)
    normalized_missing = _dedupe_strings([str(item) for item in missing_information], limit=8)

    normalized_evidence: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        normalized_evidence.append(
            {
                "label": str(item.get("label", "Evidence")).strip() or "Evidence",
                "snippet": snippet[:500],
                "section": str(item.get("section", "")).strip() or None,
            }
        )

    normalized_sections: list[dict[str, Any]] = []
    for item in source_sections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "Excerpt"
        excerpt = str(item.get("excerpt", "")).strip()
        if not excerpt:
            continue
        normalized_sections.append(
            {
                "id": str(item.get("id", title)).strip() or title,
                "title": title,
                "excerpt": excerpt[:700],
                "page": item.get("page"),
            }
        )

    return {
        "scenario_description": scenario_description,
        "settings": normalized_settings,
        "actions": normalized_actions,
        "agents": normalized_agents,
        "key_variables": normalized_variables,
        "assumptions": normalized_assumptions,
        "missing_information": normalized_missing,
        "evidence": normalized_evidence,
        "recommended_scenario_id": recommended_scenario_id,
        "recommended_scenario_reason": recommended_scenario_reason,
        "recommendation_confidence": recommendation_confidence,
        "review_required": review_required,
        "recommended_params": recommended_params,
        "source_sections": normalized_sections,
    }


def localize_analysis_output(analysis: dict[str, Any], language: str | None) -> dict[str, Any]:
    localized = dict(analysis)
    localized["actions"] = [
        _localize_action_item(item.get("name", ""), item.get("description", ""), language)
        for item in analysis.get("actions", [])
        if isinstance(item, dict)
    ]

    localized_evidence: list[dict[str, Any]] = []
    for item in analysis.get("evidence", []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        section = item.get("section")
        localized_label = label
        if label.startswith("Variable: "):
            localized_label = _localize_text(label, f"变量：{label.removeprefix('Variable: ')}", language)
        elif label.startswith("Action: "):
            localized_label = _localize_text(label, f"动作：{label.removeprefix('Action: ')}", language)
        elif label.startswith("Template clue: "):
            localized_label = _localize_text(label, f"模板线索：{label.removeprefix('Template clue: ')}", language)
        localized_evidence.append(
            {
                **item,
                "label": localized_label,
                "section": _localize_section_title(str(section), language) if section else section,
            }
        )
    localized["evidence"] = localized_evidence

    localized["source_sections"] = [
        {
            **item,
            "title": _localize_section_title(str(item.get("title", "")), language),
        }
        for item in analysis.get("source_sections", [])
        if isinstance(item, dict)
    ]
    return localized
