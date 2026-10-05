#!/usr/bin/env python3
"""merge_textbook.py — 把散 chapter markdown 文件合并成单本教材。

用法:
    python scripts/merge_textbook.py

输入:
    chapters/*.md(按文件名排序)

输出:
    textbook-complete.md(单本 markdown,带 README 封面 + 完整目录 + 全部正文)

考虑因素:
- 章节顺序由文件名前缀数字决定(01-, 02-, ...)
- 附录独立排在最后(appendix-* 模式)
- 章节之间用水平分隔符 + 空行
- README 作为封面页放在最前
- MANIFEST.md 在 README 之后、目录之前

**关键工程:Box-Drawing 字符保护**
合并时扫描整本,如果发现 box-drawing 字符(┌─┐│└┘├┤等)出现,
会自动把对应的连续行包成 ```text 代码块,以避免 pandoc 转 PDF 时
STSong 字体缺字符导致渲染成 □□□ 方块。
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CHAPTERS_DIR = ROOT / "chapters"
OUTPUT = ROOT / "textbook-complete.md"

# Box-drawing / block element 字符集(STSong 字体不含)
BOX_CHARS = set("┌┐└┘├┤┬┴┼─│╭╰╮╯━┃┏┓┗┛╌╴╼╾╪╫╬")


def chapter_sort_key(path: Path) -> tuple:
    """把 '01-introduction.md' 排序成 ('01', 'introduction')"""
    stem = path.stem
    match = re.match(r"^(\d+)-(.+)$", stem)
    if match:
        return (int(match.group(1)), match.group(2))
    match = re.match(r"^(appendix)-(.+)$", stem)
    if match:
        return (1000, match.group(2))
    return (9999, stem)


def collect_chapters() -> list[Path]:
    """按编号顺序收集所有 markdown 章节"""
    files = [p for p in CHAPTERS_DIR.glob("*.md") if not p.name.startswith("_")]
    return sorted(files, key=chapter_sort_key)


def make_toc(chapters: list[Path]) -> str:
    """生成 markdown 目录"""
    lines = ["\n# 目录\n\n"]
    for f in chapters:
        title = f.stem
        try:
            content = f.read_text(encoding="utf-8")
            m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if m:
                title = m.group(1).strip()
        except Exception:
            pass
        anchor = f.stem.replace(".", "")
        lines.append(f"- [{title}](#{anchor})\n")
    return "".join(lines)


def wrap_box_lines(text: str) -> str:
    """扫描含 box-drawing 字符的连续行,包成 ```text 代码块(防止 LaTeX 渲染问题)"""
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 阈值:≥1 个 box 字符就算(原来 ≥3 漏掉了 ├── 等单字符行)
        has_box = any(c in BOX_CHARS for c in line)
        if has_box:
            block = [line]
            j = i + 1
            while j < len(lines):
                lj = lines[j]
                # 继续收集:有 box 字符的行 OR 空行(且下一行仍是 box)
                lj_has_box = any(c in BOX_CHARS for c in lj)
                if lj_has_box:
                    block.append(lj)
                    j += 1
                elif lj.strip() == '' and j+1 < len(lines) and any(c in BOX_CHARS for c in lines[j+1]):
                    block.append(lj)
                    j += 1
                else:
                    break
            out.append('```text')
            out.extend(block)
            out.append('```')
            i = j
        else:
            out.append(line)
            i += 1
    return '\n'.join(out)


def merge() -> None:
    """主入口:合并所有 markdown"""
    if not CHAPTERS_DIR.exists():
        raise SystemExit(f"找不到章节目录: {CHAPTERS_DIR}")

    chapters = collect_chapters()
    if not chapters:
        raise SystemExit(f"在 {CHAPTERS_DIR} 里没有 .md 文件")

    parts = []

    # 封面页(README)
    readme = ROOT / "README.md"
    if readme.exists():
        parts.append(wrap_box_lines(readme.read_text(encoding="utf-8")))

    # MANIFEST(可选)
    manifest = ROOT / "MANIFEST.md"
    if manifest.exists():
        parts.append("\n\n---\n\n")
        parts.append(wrap_box_lines(manifest.read_text(encoding="utf-8")))

    # 目录
    parts.append("\n\n---\n\n")
    parts.append(make_toc(chapters))

    # 正文
    parts.append("\n\n---\n\n# 正文\n\n")
    for f in chapters:
        content = f.read_text(encoding="utf-8")
        parts.append("\n\n---\n\n")
        parts.append(wrap_box_lines(content))
        parts.append("\n\n")

    OUTPUT.write_text("".join(parts), encoding="utf-8")
    raw_bytes = OUTPUT.stat().st_size

    # 字数统计
    text = OUTPUT.read_text(encoding="utf-8")
    text_no_md = re.sub(r"[#*\->|`]", "", text)
    text_no_md = re.sub(r"\[|\]|\(|\)", "", text_no_md)
    text_no_md = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9\s]", "", text_no_md)
    text_no_md = re.sub(r"\s+", "", text_no_md)
    chinese_chars = len(text_no_md)

    print(f"合并 {len(chapters)} 章到 {OUTPUT.name}")
    print(f"大小: {raw_bytes / 1024:.1f} KB")
    print(f"中英文字符数: {chinese_chars} ({chinese_chars / 10000:.1f} 万)")


if __name__ == "__main__":
    merge()