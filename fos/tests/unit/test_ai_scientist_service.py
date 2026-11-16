"""This test file checks the core AI scientist extraction helpers.

Each test verifies one thing:
- markdown-wrapped JSON can be parsed,
- template suggestions rank matching scenarios,
- merge uses fallback values when primary output is incomplete.
"""

from fos.backend.services.ai_scientist import (
    build_llm_analysis_scaffold,
    build_semantic_schema,
    build_source_outline,
    collect_analysis_quality_issues,
    heuristic_analysis,
    merge_analysis,
    normalize_llm_analysis_output,
    parse_llm_json,
    suggest_templates,
)


def test_ai_scientist_parses_json_inside_markdown_block() -> None:
    raw = """```json
    {
      "scenario_description": "A simple test",
      "settings": [],
      "actions": [{"name": "cooperate", "description": "Work together"}],
      "agents": [{"label": "participants", "description": "test", "count": 2}],
      "key_variables": ["trust"]
    }
    ```"""

    parsed = parse_llm_json(raw)

    assert parsed["scenario_description"] == "A simple test"
    assert parsed["actions"][0]["name"] == "cooperate"


def test_ai_scientist_template_matching_prefers_relevant_scenario() -> None:
    scenarios = [
        {
            "id": "public_goods",
            "name": "Public Goods Game",
            "category": "game_theory",
            "description": "People decide how much to contribute to a shared pool.",
            "actions": [{"name": "contribute"}, {"name": "keep"}],
        },
        {
            "id": "policy_erosion",
            "name": "Policy Meaning Erosion",
            "category": "sociology",
            "description": "A policy passes through hierarchy levels.",
            "actions": [{"name": "reinterpret"}, {"name": "block"}],
        },
    ]

    result = suggest_templates(
        "In this study, participants choose to contribute or keep resources in a shared pool.",
        scenarios,
        top_k=2,
    )

    assert len(result) >= 1
    assert result[0].id == "public_goods"


def test_ai_scientist_merge_uses_fallback_when_primary_missing() -> None:
    primary = {
        "scenario_description": "",
        "actions": [],
        "agents": [],
        "settings": [],
        "key_variables": [],
        "assumptions": [],
        "missing_information": [],
        "evidence": [],
        "recommended_scenario_id": "",
        "recommended_scenario_reason": "",
        "recommended_params": {},
        "source_sections": [],
    }
    fallback = {
        "scenario_description": "Fallback scenario",
        "actions": [{"name": "option_a", "description": "Primary decision option."}],
        "agents": [{"label": "participants", "description": "Primary participants", "count": 3}],
        "settings": [{"key": "research_question", "value": "Q", "reason": "from text"}],
        "key_variables": ["trust"],
        "assumptions": ["Fallback assumption"],
        "missing_information": ["Fallback gap"],
        "evidence": [{"label": "Evidence", "snippet": "shared pool", "section": None}],
        "recommended_scenario_id": "public_goods",
        "recommended_scenario_reason": "Keyword match",
        "recommended_params": {"multiplier": 1.5},
        "source_sections": [{"id": "s1", "title": "Abstract", "excerpt": "Text", "page": None}],
    }

    merged = merge_analysis(primary, fallback)

    assert merged["scenario_description"] == "Fallback scenario"
    assert merged["actions"][0]["name"] == "option_a"
    assert merged["agents"][0]["label"] == "participants"
    assert merged["settings"][0]["key"] == "research_question"
    assert merged["recommended_scenario_id"] == "public_goods"
    assert merged["recommended_params"]["multiplier"] == 1.5
    assert merged["evidence"][0]["snippet"] == "shared pool"


def test_ai_scientist_builds_llm_scaffold_without_using_it_as_final_answer() -> None:
    scenarios = [
        {
            "id": "public_goods",
            "name": "Public Goods Game",
            "category": "game_theory",
            "description": "People decide how much to contribute to a shared pool.",
            "actions": [{"name": "contribute"}, {"name": "keep"}],
        }
    ]

    scaffold = build_llm_analysis_scaffold(
        "Abstract\nParticipants contribute 20 tokens to a shared pool or keep them in a private account.",
        scenarios,
        language="en",
        top_k=1,
    )

    assert scaffold["template_suggestions"][0].id == "public_goods"
    assert scaffold["semantic_schema"]["research_goal"]
    assert scaffold["semantic_schema"]["ontology"]["participant_primitives"]
    assert scaffold["semantic_schema"]["interaction_structure"]["display_label"]
    assert scaffold["helper_hints"]["candidate_actions"]
    assert scaffold["helper_hints"]["ontology"]["action_primitives"]
    assert scaffold["evidence_packet"]["source_sections"]


def test_ai_scientist_normalizes_model_output_without_heuristic_fallback() -> None:
    suggestions = [
        type(
            "Suggestion",
            (),
            {
                "id": "public_goods",
                "name": "Public Goods Game",
                "category": "game_theory",
                "description": "Shared pool contribution study.",
                "score": 0.65,
                "reason": "Matched public goods keywords.",
            },
        )()
    ]
    semantic_schema = {
        "key_variables": ["trust"],
        "evidence_map": {"actions": ["participants decide whether to contribute or keep"], "participants": ["four participants received tokens"]},
    }
    normalized = normalize_llm_analysis_output(
        {
            "scenario_description": "A repeated shared-pool experiment.",
            "settings": [{"key": "round_tokens", "value": "20", "reason": "mentioned directly"}],
            "actions": [{"name": "contribute", "description": "Put tokens in the shared pool."}],
            "agents": [{"label": "participants", "description": "Members of the group", "count": 4}],
            "recommended_scenario_id": "public_goods",
            "recommended_scenario_reason": "The document explicitly describes public pool contributions.",
            "evidence_by_field": {"actions": ["participants decide whether to contribute or keep"]},
            "recommended_params": {"tokens_per_round": 20},
        },
        semantic_schema=semantic_schema,
        source_sections=[{"id": "abstract", "title": "Abstract", "excerpt": "Participants contribute or keep tokens.", "page": 1}],
        template_suggestions=suggestions,
    )

    assert normalized["recommended_scenario_id"] == "public_goods"
    assert normalized["actions"][0]["name"] == "contribute"
    assert normalized["source_sections"][0]["title"] == "Abstract"
    assert normalized["evidence_by_field"]["actions"]


def test_ai_scientist_collects_quality_issues_for_noisy_model_output() -> None:
    suggestions = [
        type(
            "Suggestion",
            (),
            {
                "id": "public_goods",
                "name": "Public Goods Game",
                "category": "game_theory",
                "description": "Shared pool contribution study.",
                "score": 0.65,
                "reason": "Matched public goods keywords.",
            },
        )()
    ]

    issues = collect_analysis_quality_issues(
        {
            "scenario_description": "Test draft",
            "actions": [{"name": "1 Introduction", "description": "noise"}],
            "agents": [{"label": "Smith et al. 2020 Journal of Something", "description": "noise", "count": 1}],
            "evidence": [],
            "evidence_by_field": {},
            "recommended_scenario_id": "made_up_template",
        },
        template_suggestions=suggestions,
    )

    assert "actions_contain_noise" in issues
    assert "agents_contain_noise" in issues
    assert "invalid_template_choice" in issues
    assert "evidence_missing" in issues


def test_ai_scientist_heuristic_analysis_reconstructs_public_goods_like_study() -> None:
    suggestions = [
        type(
            "Suggestion",
            (),
            {
                "id": "public_goods",
                "name": "Public Goods Game",
                "category": "game_theory",
                "description": "Shared pool contribution study.",
                "score": 0.45,
                "reason": "Matched public goods keywords.",
            },
        )()
    ]

    result = heuristic_analysis(
        (
            "Abstract\n"
            "Participants received 20 tokens each round and decided whether to contribute to a shared pool "
            "or keep resources in a private account. The pool multiplier was 1.6."
        ),
        suggestions,
    )

    assert result["recommended_scenario_id"] == "public_goods"
    assert result["recommended_params"]["tokens_per_round"] == 20
    assert result["recommended_params"]["multiplier"] == 1.6
    assert len(result["actions"]) >= 2
    assert result["evidence_by_field"]["payoff_rules"]
    assert any(section["title"].lower() == "abstract" for section in result["source_sections"])


def test_ai_scientist_builds_ontology_and_structure_localization_for_custom_draft() -> None:
    schema = build_semantic_schema(
        (
            "Abstract\n"
            "One participant makes an offer about how to split 10 credits. "
            "A responder can accept the offer or reject it. If the offer is rejected, both receive nothing."
        ),
        language="zh",
    )

    assert schema["interaction_structure"]["type"] == "proposal_response_exchange"
    assert schema["interaction_structure"]["display_label"]
    assert "双方" in schema["ontology"]["participant_primitives"]
    assert "分配" in schema["ontology"]["action_primitives"]
    assert schema["evidence_map"]["actions"]


def test_ai_scientist_heuristic_analysis_reconstructs_operational_multi_agent_scene() -> None:
    traffic_text = (
        "场景名称：城市级智能交通应急协同系统（Urban MAS-TECS）\n\n"
        "背景设定\n"
        "2026年5月20日，星期三，早高峰时段。某特大城市中心区发生突发状况：一辆运载化学品的货车在主要干道十字路口轻微剐蹭，"
        "导致局部道路封闭，且存在潜在泄漏风险。传统单一控制中心难以在毫秒级时间内协调交警、消防、医疗及导航服务。"
        "此时，基于多智能体系统（Multi-Agent System, MAS）的城市交通管理平台启动应急响应机制。\n\n"
        "参与智能体及其角色\n\n"
        "1. 交通调度智能体（Traffic Dispatcher Agent, TDA）\n"
        "* 核心职能：全局状态感知与宏观路由规划。\n"
        "* 行为逻辑：TDA实时接入全市摄像头与地磁传感器数据，识别拥堵源头。它不直接控制红绿灯，而是向区域子智能体下发“流量重定向”指令，"
        "将主干道车流引导至备用路线，防止次生拥堵。\n\n"
        "2. 应急救援智能体（Emergency Response Agent, ERA）\n"
        "* 核心职能：资源最优匹配与路径动态规划。\n"
        "* 行为逻辑：ERA接收事故报警后，立即调用地图API与实时路况数据。它与TDA进行通信，获取当前可通行的“绿色通道”。同时，"
        "ERA并行计算救护车、消防车和警车的最优到达路径，确保救援车辆避开拥堵点，并提前通知沿途信号灯转为绿灯。\n\n"
        "3. 现场机器人协作组（Field Robot Swarm, FRS）\n"
        "* 核心职能：物理环境处置与危险源隔离。\n"
        "* 行为逻辑：由三台自主移动机器人组成的小型集群。\n"
        "    * FRS-Alpha（侦察型）：率先抵达现场，通过热成像与气体传感器确认化学品泄漏范围，并将三维环境模型上传至云端共享内存。\n"
        "    * FRS-Beta（封锁型）：根据Alpha的数据，自动部署便携式路障，建立安全隔离区。\n"
        "    * FRS-Gamma（处置型）：在确认安全后，执行初步的吸附处理。\n\n"
        "4. 公众信息服务智能体（Public Info Agent, PIA）\n"
        "* 核心职能：信息分发与用户行为引导。\n"
        "* 行为逻辑：PIA从TDA和ERA处获取事故性质、预计通行时间及绕行建议。它通过车载导航APP、路边电子屏及社交媒体接口，"
        "向受影响区域的驾驶员推送个性化绕行方案。PIA还具备反馈循环功能，监测用户是否采纳建议，若发现大量车辆未绕行，则向TDA发出预警，"
        "请求调整信号配时策略。\n\n"
        "交互流程与决策机制\n\n"
        "* 阶段一：感知与初始化（0-10秒）\n"
        "TDA检测到异常停车事件，触发警报。ERA激活，FRS集群从最近的服务站出发。\n\n"
        "* 阶段二：协商与规划（10-30秒）\n"
        "TDA与ERA进行双向通信。TDA告知ERA：“主干道B段已完全堵塞，建议走C环路。”ERA回复：“收到，正在为救护车规划C环路路径，"
        "但C环路入口有施工，需TDA协助临时开放应急车道。”TDA确认后，向该路段的信号灯控制器发送指令。\n\n"
        "* 阶段三：执行与自适应（30秒-5分钟）\n"
        "FRS集群在现场协作。Alpha发现泄漏物扩散速度超预期，立即广播新坐标。Beta和Gamma自动调整动作序列，优先扩大隔离区而非继续吸附。"
        "PIA同步更新公众信息，提示“事故等级升级，请周边居民关闭门窗”。\n\n"
        "* 阶段四：恢复与评估（5分钟后）\n"
        "事故处理完毕，道路清理完成。TDA逐步解除交通管制，恢复正常信号配时。\n\n"
        "技术特征解析\n"
        "* 去中心化与协作：FRS集群通过去中心化协议直接通信，无需中央服务器中转，实现任务并行处理与资源共享。"
    )
    schema = build_semantic_schema(traffic_text, outline=build_source_outline(traffic_text), language="zh")
    result = heuristic_analysis(
        traffic_text,
        [],
        language="zh",
    )

    action_names = {item["name"] for item in result["actions"]}
    agent_labels = {item["label"] for item in result["agents"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "状态同步" in action_names
    assert "交通重定向" in action_names
    assert "信号优先请求" in action_names
    assert "危险区勘测" in action_names
    assert "交通调度智能体（Traffic Dispatcher Agent, TDA）" in agent_labels
    assert "应急救援智能体（Emergency Response Agent, ERA）" in agent_labels
    assert "FRS-Alpha（侦察型）" in agent_labels
    assert "FRS-Beta（封锁型）" in agent_labels
    assert "FRS-Gamma（处置型）" in agent_labels
    assert "公众信息服务智能体（Public Info Agent, PIA）" in agent_labels
    assert "城市级智能交通应急协同系统" in result["scenario_description"]
    assert "多角色协同" in result["scenario_description"]
    assert result["recommended_params"]["source_title"] == "城市级智能交通应急协同系统（Urban MAS-TECS）"
    assert "交通调度智能体（Traffic Dispatcher Agent, TDA）" in result["recommended_params"]["participant_roles"]
    assert "交通重定向" in result["recommended_params"]["decision_action_labels"]
    assert schema["title"] == "城市级智能交通应急协同系统（Urban MAS-TECS）"
    assert any(item["label"] == "交通调度智能体（Traffic Dispatcher Agent, TDA）" for item in schema["participants"])
    assert any(choice["name"] == "交通重定向" for choice in schema["choices"])
    assert any("开放应急车道" in item for item in schema["interventions"])
    assert any("去中心化" in item for item in schema["interaction_topology"])


def test_ai_scientist_heuristic_analysis_localizes_custom_actions_for_chinese_ui() -> None:
    result = heuristic_analysis(
        "场景名称：交通系统\n\n背景设定\n系统需要根据事故情况进行绕行、信号优先、广播和资源调度。",
        [],
        language="zh",
    )

    action_names = {item["name"] for item in result["actions"]}

    assert "交通重定向" in action_names
    assert "状态同步" in action_names


def test_ai_scientist_heuristic_analysis_reconstructs_auction_structure_from_rule_text() -> None:
    auction_text = (
        "This bidding exercise is an auction in which the auctioneer assigns a prize to the highest bidder, "
        "with the understanding that both the highest bidder and the second highest bidder will pay. "
        "Suppose that bids must be made in multiples of 5 cents. "
        "For the purposes of the discussion and analysis, we limit ourselves to an auctioneer and two bidders. "
        "At that point, it may appear to a bidder that they should raise to 55 cents rather than take a certain loss. "
        "Once two bids have been obtained from the crowd, the paradox of escalation is real."
    )
    schema = build_semantic_schema(auction_text, outline=build_source_outline(auction_text), language="en")
    result = heuristic_analysis(
        auction_text,
        [],
        language="en",
    )

    action_names = {item["name"] for item in result["actions"]}
    agent_labels = {item["label"] for item in result["agents"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Increase bid" in action_names
    assert "Exit bidding" in action_names
    assert "auctioneer" in agent_labels
    assert "bidders" in agent_labels
    assert "second-highest bidder" in result["scenario_description"] or "second highest bidder" in result["scenario_description"]
    assert result["recommended_params"]["pay_top_two"] is True
    assert result["recommended_params"]["bid_increment_cents"] == 5
    assert "discussion and analysis" in schema["research_goal"].lower()
    assert any(choice["name"] == "Increase bid" for choice in schema["choices"])
    assert any("second highest bidder" in rule.lower() for rule in schema["payoff_rules"])
    assert any("multiples of 5 cents" in item.lower() for item in schema["constraints"])


def test_ai_scientist_template_matching_does_not_invent_nonexistent_template() -> None:
    scenarios = [
        {
            "id": "stag_hunt",
            "name": "Stag Hunt",
            "category": "game_theory",
            "description": "Players choose between stag and hare.",
            "actions": [{"name": "stag"}, {"name": "hare"}],
        },
        {
            "id": "coordination_game",
            "name": "Coordination Game",
            "category": "game_theory",
            "description": "Players coordinate by choosing matching options.",
            "actions": [{"name": "option_a"}, {"name": "option_b"}],
        },
    ]
    text = (
        "Sequential allocation study\n"
        "The first player proposes how to divide a fixed budget. "
        "The second player can approve or reject the proposal, and rejection prevents the allocation from taking effect."
    )

    result = suggest_templates(text, scenarios, top_k=2)

    assert {item.id for item in result}.issubset({"stag_hunt", "coordination_game"})
    assert result[0].score < 0.45


def test_ai_scientist_heuristic_analysis_reconstructs_proposal_response_as_custom_structure() -> None:
    text = (
        "Sequential allocation exercise\n\n"
        "In this experiment the first player decides how to split 10 credits between herself and the second player. "
        "The second player then decides whether to approve or reject the proposal. If the proposal is rejected, the allocation does not take effect."
    )

    result = heuristic_analysis(text, [], language="en")

    action_names = {item["name"] for item in result["actions"]}
    agent_labels = {item["label"] for item in result["agents"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Propose split" in action_names
    assert "Approve split" in action_names
    assert "Reject split" in action_names
    assert "initiator" in agent_labels or "first player" in agent_labels
    assert "reviewer" in agent_labels or "second player" in agent_labels


def test_ai_scientist_heuristic_analysis_reconstructs_competitive_pressure_as_custom_structure() -> None:
    text = (
        "Competitive restraint study\n\n"
        "Players repeatedly choose between a forceful strategy and a yielding strategy while competing over the same contested resource. "
        "The conflict cost exceeds the value of the contested resource when both players choose the forceful option."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Choose compete" in action_names
    assert "Choose yield" in action_names
    assert result["review_required"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_shared_target_threshold_as_custom_structure() -> None:
    text = (
        "Shared target contribution study\n\n"
        "Participants decide whether to contribute toward a collective target or keep resources privately. "
        "If the threshold is missed, the group faces a collective loss. Some treatments allow delegation to an automated decision process."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Contribute to target" in action_names
    assert "Keep private reserves" in action_names
    assert "Delegate choice" in action_names
    assert result["recommended_params"]["participant_roles"] == ["participants"]
    assert result["recommended_params"]["enable_delegation"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_majority_visibility_as_custom_structure() -> None:
    text = (
        "Public judgment under group visibility\n\n"
        "A focal participant hears a unanimous majority answer before publicly giving an answer. "
        "The participant can align with the visible majority or state an independent answer."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Align with majority" in action_names
    assert "State independent answer" in action_names


def test_ai_scientist_heuristic_analysis_reconstructs_threshold_adoption_as_custom_structure() -> None:
    text = (
        "Threshold adoption process\n\n"
        "Individuals join collective action only after enough others have already joined. "
        "Different thresholds generate cascades as participation spreads through the group."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Adopt behavior" in action_names
    assert "Wait for more adoption" in action_names


def test_ai_scientist_heuristic_analysis_reconstructs_threshold_adoption_from_chinese_protest_text() -> None:
    text = (
        "场景名称：集体行为阈值模型\n"
        "一个城市中有100名市民，每个市民都有自己的参与阈值。"
        "每一轮，智能体观察当前已经参与的人数；如果达到或超过个人阈值，就加入抗议，否则继续观望。"
        "一旦有人加入，参与会进一步扩散，形成级联。"
    )

    result = heuristic_analysis(text, [], language="zh")
    action_names = {item["name"] for item in result["actions"]}
    agent_labels = {item["label"] for item in result["agents"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "阈值触发的集体行为扩散场景" in result["scenario_description"]
    assert "采纳行为" in action_names
    assert "继续观望" in action_names
    assert "市民" in agent_labels
    assert result["recommended_params"]["population_size"] == 100


def test_ai_scientist_heuristic_analysis_keeps_collective_behavior_threshold_text_out_of_public_goods() -> None:
    text = (
        "Threshold Models of Collective Behavior\n"
        "Actors have two alternatives and the costs and benefits of each depend on how many other actors choose which alternative. "
        "The key concept is a threshold: the number or proportion of others who must join before a given actor joins. "
        "As participation spreads, cascades emerge across the group."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "threshold-driven collective behavior process" in result["scenario_description"]
    assert "Adopt behavior" in action_names
    assert "Wait for more adoption" in action_names
    assert result["recommended_params"]["interaction_structure_hint"] == "threshold_adoption_process"


def test_ai_scientist_heuristic_analysis_reconstructs_el_farol_style_attendance_problem() -> None:
    text = (
        "El Farol Bar Problem\n\n"
        "One hundred agents decide each week whether to go to a bar. "
        "If fewer than 60 percent attend, going is worthwhile; if attendance exceeds that level, the bar becomes too crowded. "
        "Each agent predicts attendance from historical attendance records."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "congestible attendance setting" in result["scenario_description"]
    assert "Attend" in action_names
    assert "Stay away" in action_names
    assert result["recommended_params"]["capacity_percent"] == 60.0
    assert result["recommended_params"]["prediction_source"] == "attendance_history"


def test_ai_scientist_heuristic_analysis_reconstructs_sequential_information_cascade() -> None:
    text = (
        "Sequential herd behavior study\n\n"
        "Agents decide in order. Each person gets a private signal, but also sees previous public choices. "
        "After enough early choices point in the same direction, later agents ignore their private signal and follow the majority."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "information-cascade setting" in result["scenario_description"]
    assert "Follow private signal" in action_names
    assert "Follow observed majority" in action_names
    assert result["recommended_params"]["private_signal"] is True
    assert result["recommended_params"]["decision_order"] == "sequential"


def test_ai_scientist_heuristic_analysis_reconstructs_spatial_relocation_preference() -> None:
    text = (
        "Dynamic Models of Segregation\n\n"
        "Residents occupy a two-dimensional grid. "
        "Each resident wants a minimum share of similar neighbors and relocates to an empty cell when dissatisfied with the local neighborhood."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "spatial relocation process" in result["scenario_description"]
    assert "Stay put" in action_names
    assert "Relocate" in action_names
    assert result["recommended_params"]["space_type"] == "grid"


def test_ai_scientist_preserves_explicit_custom_actions_when_structure_is_clear() -> None:
    text = (
        "Custom protest threshold draft\n\n"
        "Agents observe how many others have joined before deciding whether to act. "
        "Available actions are mobilize_now and hold_position. "
        "When enough others have already mobilized, additional agents join and a cascade begins."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "mobilize_now" in action_names
    assert "hold_position" in action_names


def test_ai_scientist_heuristic_analysis_reconstructs_bystander_help_diffusion() -> None:
    text = (
        "Bystander intervention study\n\n"
        "An emergency event occurs in public. Each bystander observes the severity of the event, "
        "the number of other witnesses, and whether someone else has already intervened. "
        "As the number of bystanders grows, diffusion of responsibility makes each person less likely to help."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Provide help" in action_names
    assert "Wait for others" in action_names
    assert result["recommended_params"]["event_type"] == "emergency"
    assert result["recommended_params"]["responsibility_diffusion"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_bank_run_coordination() -> None:
    text = (
        "Bank run coordination model\n\n"
        "Depositors decide whether to withdraw early or keep deposits in the bank. "
        "If everyone believes others will withdraw, each depositor rushes to withdraw as well, "
        "creating a self-fulfilling liquidity crisis. Deposit insurance may stabilize the safe equilibrium."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Withdraw early" in action_names
    assert "Keep deposit" in action_names
    assert result["recommended_params"]["deposit_insurance"] is True
    assert result["recommended_params"]["liquidity_constraint"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_lemons_market() -> None:
    text = (
        "Market for lemons\n\n"
        "Sellers privately know the quality of a used car while buyers only see price and sparse signals. "
        "Adverse selection pushes high-quality sellers out unless certification or reputation restores trust."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Quote trade price" in action_names
    assert "Certify or signal quality" in action_names
    assert result["recommended_params"]["quality_information"] == "seller_private"
    assert result["recommended_params"]["adverse_selection_risk"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_bullwhip_supply_chain() -> None:
    text = (
        "Beer distribution game\n\n"
        "A retailer, wholesaler, distributor, and factory each see only local inventory and neighboring orders. "
        "Order and shipping delays cause small demand changes to amplify into a bullwhip pattern."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Place replenishment order" in action_names
    assert "Ship available inventory" in action_names
    assert result["recommended_params"]["supply_chain_levels"] == 4
    assert result["recommended_params"]["feedback_delay"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_innovation_diffusion_marketing() -> None:
    text = (
        "Diffusion of innovations\n\n"
        "Consumers adopt a new product through both advertising and word of mouth. "
        "Innovators and early adopters move first, while the late majority waits for stronger social proof."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Adopt product" in action_names
    assert "Delay adoption" in action_names
    assert result["recommended_params"]["external_influence"] is True
    assert result["recommended_params"]["social_imitation"] is True
    assert result["recommended_params"]["adopter_categories"] is True


def test_ai_scientist_heuristic_analysis_reconstructs_collective_action_free_rider() -> None:
    text = (
        "Logic of collective action\n\n"
        "Group members all benefit from a public objective, but each person prefers that others pay the mobilization cost. "
        "Selective incentives are introduced to counter free-riding in a large group."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "Contribute to collective action" in action_names
    assert "Free-ride on others" in action_names
    assert result["recommended_params"]["selective_incentives"] is True
    assert result["recommended_params"]["group_scale"] == "large"


def test_ai_scientist_heuristic_analysis_preserves_explicit_actions_for_financial_text() -> None:
    text = (
        "Custom insider trading draft\n\n"
        "A market maker updates prices from observed order flow while an informed trader hides private information by splitting trades. "
        "Action rules: reveal_small_order, wait_for_liquidity, update_quote. "
        "Noise traders submit random orders in the background."
    )

    result = heuristic_analysis(text, [], language="en")
    action_names = {item["name"] for item in result["actions"]}

    assert result["recommended_scenario_id"] == "custom"
    assert "reveal_small_order" in action_names
    assert "wait_for_liquidity" in action_names
    assert "update_quote" in action_names
