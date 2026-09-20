import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generative_city_sim import CSV_PATH, MAP_PATH, build_agent, call_llm, load_city_map


QUESTION_BANK = [
    {
        "id": "math_1",
        "dimension": "numerical",
        "question": "计算：17 × 6 - 15 = ?",
        "answer": "87",
        "score": 10,
    },
    {
        "id": "sequence_1",
        "dimension": "pattern",
        "question": "数列 2, 6, 12, 20, 30, ? 下一个数字是多少？",
        "answer": "42",
        "score": 10,
    },
    {
        "id": "analogy_1",
        "dimension": "verbal",
        "question": (
            "类比题：鱼之于水，相当于鸟之于什么？\n"
            "A. 森林\nB. 天空\nC. 巢穴\nD. 羽毛"
        ),
        "answer": "B",
        "score": 10,
    },
    {
        "id": "logic_1",
        "dimension": "logic",
        "question": (
            "逻辑题：所有玫瑰都是花，有些花会很快凋谢。根据这句话，下面哪项一定为真？\n"
            "A. 有些玫瑰会很快凋谢\nB. 所有花都会很快凋谢\nC. 无法确定是否有玫瑰会很快凋谢\nD. 没有玫瑰会很快凋谢"
        ),
        "answer": "C",
        "score": 10,
    },
    {
        "id": "memory_1",
        "dimension": "working_memory",
        "question": "记住数字 7 2 9 4。现在请把它倒序写出来，只输出四位数字。",
        "answer": "4927",
        "score": 10,
    },
    {
        "id": "calendar_1",
        "dimension": "temporal",
        "question": "如果今天是星期三，那么 10 天后是星期几？",
        "answer": "星期六",
        "alternatives": ["周六"],
        "score": 10,
    },
    {
        "id": "planning_1",
        "dimension": "planning",
        "question": (
            "你 9:00 必须到达一个重要会议地点。\n"
            "A 方案：8:30 出发，路程通常 20 分钟，但经常额外堵 20 分钟。\n"
            "B 方案：8:10 出发，路程稳定 30 分钟。\n"
            "C 方案：8:45 出发，路程稳定 10 分钟。\n"
            "哪一个方案最稳妥？\n"
            "A. 方案A\nB. 方案B\nC. 方案C\nD. 三个一样稳妥"
        ),
        "answer": "B",
        "score": 10,
    },
    {
        "id": "reading_1",
        "dimension": "reading",
        "question": (
            "阅读：'所有参加复试的人都提交了材料。小张参加了复试。'\n"
            "可以推出什么？\n"
            "A. 小张一定被录取\nB. 小张提交了材料\nC. 提交材料的人都参加了复试\nD. 无法判断"
        ),
        "answer": "B",
        "score": 10,
    },
]


def build_profile_text(agent):
    return "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        f"性格与情绪特征：{agent.get('personality', '')}",
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])


def extract_structured_answer(text):
    if not text:
        return ""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    json_blob = match.group(1) if match else ""
    if not json_blob:
        inline = re.search(r"\{.*\}", text, re.S)
        json_blob = inline.group(0) if inline else ""
    if json_blob:
        try:
            payload = json.loads(json_blob)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            answer = str(payload.get("answer", "")).strip()
            if answer:
                return answer
    return text.strip()


def normalize_answer(text):
    cleaned = str(text or "").strip()
    cleaned = cleaned.replace("：", ":")
    cleaned = cleaned.replace("答案", "")
    cleaned = cleaned.strip(" .,:;，。；")
    upper = cleaned.upper()
    letter_match = re.search(r"\b([A-D])\b", upper)
    if letter_match:
        return letter_match.group(1)
    digit_match = re.search(r"\b(\d+)\b", cleaned)
    if digit_match:
        return digit_match.group(1)
    weekday_match = re.search(r"(星期[一二三四五六日天]|周[一二三四五六日天])", cleaned)
    if weekday_match:
        return weekday_match.group(1)
    return cleaned


def is_correct(question, normalized_answer):
    accepted = [question["answer"]] + list(question.get("alternatives", []))
    normalized_targets = {normalize_answer(item) for item in accepted}
    return normalized_answer in normalized_targets


def ask_question(agent, question):
    profile_text = build_profile_text(agent)
    prompt = f"""
你正在扮演城市模拟器中的角色 {agent['name']}，现在接受一项简短能力测试。
角色资料：
{profile_text}

要求：
1) 认真做题，尽量给出你能推理出的最好答案。
2) 仅输出 JSON：{{"answer":"...", "reason":"..."}}。
3) answer 尽量简短；选择题只输出 A/B/C/D，中短题只输出最终答案。

题目：
{question['question']}
"""
    response = call_llm(prompt, task="interview", agent_id=agent["id"])
    raw_answer = extract_structured_answer(response)
    final_answer = normalize_answer(raw_answer)
    correct = is_correct(question, final_answer)
    return {
        "question_id": question["id"],
        "dimension": question["dimension"],
        "question": question["question"],
        "expected_answer": question["answer"],
        "agent_answer": final_answer,
        "correct": bool(correct),
        "score": int(question["score"] if correct else 0),
        "raw_response": response.strip(),
    }


def capability_band(index_score):
    if index_score >= 125:
        return "very_high"
    if index_score >= 110:
        return "high"
    if index_score >= 95:
        return "average_high"
    if index_score >= 85:
        return "average"
    if index_score >= 75:
        return "below_average"
    return "low"


def run_agent_capability_test(agent, runs=1):
    runs = max(1, int(runs))
    run_results = []
    for run_idx in range(runs):
        answers = [ask_question(agent, question) for question in QUESTION_BANK]
        total_score = sum(item["score"] for item in answers)
        max_score = sum(item["score"] for item in QUESTION_BANK)
        accuracy = total_score / max_score if max_score else 0.0
        capability_index = round(55 + accuracy * 90, 2)
        run_results.append({
            "run": run_idx + 1,
            "total_score": total_score,
            "max_score": max_score,
            "accuracy": round(accuracy, 4),
            "capability_index": capability_index,
            "band": capability_band(capability_index),
            "answers": answers,
        })

    avg_index = round(sum(item["capability_index"] for item in run_results) / len(run_results), 2)
    avg_accuracy = round(sum(item["accuracy"] for item in run_results) / len(run_results), 4)
    return {
        "agent_id": int(agent["id"]),
        "agent_name": agent.get("name", ""),
        "runs": runs,
        "average_capability_index": avg_index,
        "average_accuracy": avg_accuracy,
        "band": capability_band(avg_index),
        "note": "这是基于固定题库和 LLM 回答的粗略能力指数，不等同于正式 IQ 测试。",
        "run_results": run_results,
    }


def print_report(report):
    print(f"Agent {report['agent_id']} - {report['agent_name']}")
    print(f"Average capability index: {report['average_capability_index']}")
    print(f"Average accuracy: {report['average_accuracy']:.2%}")
    print(f"Band: {report['band']}")
    print(report["note"])
    print("")
    for run in report["run_results"]:
        print(f"Run {run['run']}: score {run['total_score']}/{run['max_score']} | index {run['capability_index']}")
        for item in run["answers"]:
            status = "OK" if item["correct"] else "ERR"
            print(
                f"  [{status}] {item['question_id']} | expected={item['expected_answer']} | "
                f"got={item['agent_answer']}"
            )
        print("")


def main():
    parser = argparse.ArgumentParser(description="Test an agent's rough capability index.")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID to test")
    parser.add_argument("--runs", type=int, default=1, help="Repeat test N times and average the result")
    parser.add_argument("--save", default=None, help="Optional path to save JSON report")
    args = parser.parse_args()

    df = pd.read_csv(CSV_PATH)
    city_map = load_city_map(MAP_PATH)
    agent = build_agent(args.agent_id, df, city_map=city_map)
    report = run_agent_capability_test(agent, runs=args.runs)
    print_report(report)

    if args.save:
        output_path = args.save
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
