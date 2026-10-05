#!/usr/bin/env bash
# build.sh — 一键从 chapters/ 构建教材成品(MD/PDF/EPUB/ZIP)
#
# 用法:
#   bash scripts/build.sh
#
# 流程:
#   1. 跑 merge_textbook.py 合并散章节 → textbook-complete.md
#   2. pandoc → textbook-complete.pdf
#   3. pandoc → textbook-complete.epub
#   4. zip 全部产物 → textbook-complete.zip
#
# 错误处理:
#   - 任一步 exit 1 立即停止
#   - 全程打印命令(可读)
#
# 依赖:pandoc + xelatex(系统装好的话就行)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "============================================================"
echo "  教材构建: $ROOT"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# 1. 合并
echo ""
echo "▶ Step 1/4 — 合并 chapters/*.md → textbook-complete.md"
python3 scripts/merge_textbook.py

# 2. PDF
echo ""
echo "▶ Step 2/4 — pandoc → textbook-complete.pdf"
pandoc textbook-complete.md \
  -o textbook-complete.pdf \
  --pdf-engine=xelatex \
  --toc \
  -V mainfont=STSong \
  -V monofont=Menlo \
  -V documentclass=book \
  -V papersize=a4

# 3. EPUB
echo ""
echo "▶ Step 3/4 — pandoc → textbook-complete.epub"
pandoc textbook-complete.md \
  -o textbook-complete.epub \
  --toc \
  --metadata title="多智能体社会仿真:原理、技术与案例" \
  --metadata author="Mavis (cw 项目团队)" \
  --metadata lang="zh-CN"

# 4. 打包
echo ""
echo "▶ Step 4/4 — 打包发行包 textbook-complete.zip"
/bin/rm -f textbook-complete.zip
zip textbook-complete.zip \
  textbook-complete.md \
  textbook-complete.pdf \
  textbook-complete.epub \
  MANIFEST.md \
  README.md \
  PROJECT_CLOSE_REPORT.md \
  scripts/merge_textbook.py \
  scripts/build.sh > /dev/null

echo ""
echo "============================================================"
echo "  构建完成!"
echo "============================================================"
ls -lh textbook-complete.md textbook-complete.pdf textbook-complete.epub textbook-complete.zip
echo ""

# 字数统计
python3 - <<'PYEOF'
import re
with open('textbook-complete.md') as f:
    s = f.read()
text = re.sub(r'[#*\->|`]', '', s)
text = re.sub(r'\[|\]|\(|\)', '', text)
text = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9\s]', '', text)
text = re.sub(r'\s+', '', text)
print(f"中英文字符数: {len(text)} ({len(text)/10000:.1f} 万)")
PYEOF