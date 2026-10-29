"""Merge the chapter files into one manuscript and build the .docx.

Usage:
    python3 tools/build_handbook.py            # merge + docx
    python3 tools/build_handbook.py --md-only  # merge only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CHAPTERS = ROOT / "chapters"
IMAGES = ROOT / "images"
BUILD = ROOT / "build"
OUT_MD = ROOT / "handbook.md"
OUT_DOCX = ROOT.parent.parent / "GAWorld_教学手册.docx"

FRONT_MATTER = """---
title: "GAWorld 教学手册"
subtitle: "从一个人到一座城：生成式社会仿真平台的实操指南"
author: "GAWorld 项目组"
date: "2026 年 10 月"
lang: zh-CN
---

# GAWorld 教学手册

**从一个人到一座城：生成式社会仿真平台的实操指南**

GAWorld 是一���生成式多智能体社会仿真平台。它让人物档案、人格、家庭责任和过往经历构成居民的决策情境；让城市、经济、天气和社会网络构成仿真环境，并影响行动结果；让研究者观察轨迹、访谈居民，并在平行世界里比较不同事件与政策的影响。

这本手册面向第一次使用 GAWorld 的人，也面向要把它讲给学生的老师。全部界面截图取自本仓库真实运行的控制台，全部插图由本仓库结构生成；每条命令都来自当前代码，可以直接复制运行。

> **使用边界**：仿真输出是模型与配置共同产生的研究材料，不应直接当作真实人群的预测。文化情境是建模的起点，仿真行为是否真实需要实验验证。

## 怎样读这本手册

手册共 20 章，按「跑起来 → 看懂人 → 造世界 → 做实验 → 写出来」五级台阶排列。

| 你是谁 | 建议路线 | 大约需要 |
|---|---|---|
| 第一次接触的学生 | 第 1–2 章 → 第 6–8 章 → 第 10 章 | 3–4 小时 |
| 准备开课的老师 | 第 1–7 章 → 第 12 章（平行世界）→ 第 19 章（排错） | 1 天 |
| 要做研究的研究者 | 第 1–6 章 → 第 9 章 → 第 11–13 章 → 第 18 章 | 2–3 天 |
| 要改代码的工程师 | 第 2 章 → 第 6–8 章 → 第 15 章（插件）→ 第 18 章 | 2 天 |

每章末尾都有「本章小结」与「动手练习」。练习都带验收标准，做完能立刻看出结果对不对。

## 延伸阅读

- `textbook/` —— 22 章 + 4 附录的《多智能体社会仿真：原理、技术与案例》，讲思想、方法论与经典案例，另附 md / pdf / epub 三种格式
- `docs/PROJECT_GUIDE.zh-CN.md` —— 中文完整使用指南，本手册的细节出处
- `docs/FEATURES.md` —— 能力目录，按子系统罗列所有可调项
- [GAWorld Bench](https://s2014628.github.io/gaworld-bench/) —— 功能效度与人类效度的评测方法

\newpage

"""

CHAPTER_TITLES: dict[str, str] = {}


def collect() -> list[Path]:
    files = sorted(CHAPTERS.glob("*.md"))
    if not files:
        print("no chapters found", file=sys.stderr)
        return []
    return files


def merge(files: list[Path]) -> str:
    parts = [FRONT_MATTER]
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        # chapters reference images as ../images/x.png; the manuscript lives one
        # level up, so rewrite to images/x.png and pin the printed width so
        # every figure fills the text column consistently
        text = re.sub(
            r"\]\(\.\./images/([^)]+)\)",
            r"](images/\1){width=16cm}",
            text,
        )
        # guarantee a page break before every chapter
        text = re.sub(r"^#\s+", "\n\\newpage\n\n# ", text, count=1)
        parts.append(text + "\n")
    return "\n\n".join(parts)


def build_docx(md_path: Path) -> int:
    reference = BUILD / "reference-zh.docx"
    if not reference.is_file():
        print(f"missing {reference}; run make_reference_docx.py first", file=sys.stderr)
        return 1
    command = [
        "pandoc",
        str(md_path),
        "-o",
        str(OUT_DOCX),
        "--reference-doc",
        str(reference),
        "--toc",
        "--toc-depth=2",
        "--resource-path",
        str(ROOT),
        "--from",
        "markdown-implicit_figures+pipe_tables+tex_math_dollars+link_attributes",
        "--metadata",
        "toc-title=目录",
    ]
    print(" ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT))
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return result.returncode
    print(f"wrote {OUT_DOCX} ({OUT_DOCX.stat().st_size // 1024} KB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md-only", action="store_true")
    args = parser.parse_args()

    files = collect()
    if not files:
        return 1
    manuscript = merge(files)
    OUT_MD.write_text(manuscript, encoding="utf-8")
    cjk = len(re.findall(r"[\u4e00-\u9fff]", manuscript))
    print(f"merged {len(files)} chapters -> {OUT_MD} ({cjk} CJK chars)")
    if args.md_only:
        return 0
    return build_docx(OUT_MD)


if __name__ == "__main__":
    raise SystemExit(main())
