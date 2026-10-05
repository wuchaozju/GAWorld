# 教材项目状态卡

> 极简状态快照。详细报告见 PROJECT_CLOSE_REPORT.md。
> **最后更新**:2026-10-02 10:24

---

## 🎯 项目目标

写一本给社科本科生/研究生的多智能体社会仿真教材,约 20 万字,含理论 + 技术 + 案例 + GAWorld 现代 LLM 范式。

**状态**:**已完成且工程闭环** ✅

---

## 📊 完成度

| 维度 | 状态 |
|---|---|
| 章节数 | 22 章 + 4 附录 = 30 份 ✅ |
| 字数 | 33 万中文字符(目标 20 万的 1.65 倍)✅ |
| 深度 | 每章"理论 + 清单 + 批判"三件套 ✅ |
| 单本合并 | `textbook-complete.md` 865 KB ✅ |
| PDF 编译 | `textbook-complete.pdf` 1.8 MB / 616 页 / A4 ✅ |
| EPUB 转换 | `textbook-complete.epub` 596 KB ✅ |
| 发行包 | `textbook-complete.zip` 2.7 MB ✅ |
| 维护脚本 | `merge_textbook.py` + `build.sh` 入仓 ✅ |

---

## 📁 产物清单

```
textbook/
├── chapters/                         # 30 份散章节 markdown 源
├── textbook-complete.md             # 单本 markdown(865 KB)
├── textbook-complete.pdf            # 印刷版(1.8 MB / 616 页)
├── textbook-complete.epub           # 电子书(596 KB)
├── textbook-complete.zip            # 一键发行包(2.7 MB)
├── README.md                        # 使用指南
├── MANIFEST.md                      # 分发清单
├── PROJECT_CLOSE_REPORT.md          # 项目报告
├── OUTLINE.md                       # 大纲
├── STATUS.md                        # 状态卡(本文件)
└── scripts/
    ├── merge_textbook.py            # 合并散章节
    └── build.sh                     # 一键构建所有产物
```

---

## 🚀 一键维护命令

```bash
cd /Users/cw/dev/GAWorld/textbook
bash scripts/build.sh
```

跑完会重新生成 MD/PDF/EPUB/ZIP。

---

## 📌 下一步可选动作

- **指定章节补深**:章节号 + 主题
- **整体校对**:产出校对报告
- **配套**:习题集 / 课件 / BibTeX / 研讨课设计
- **GitHub 发布准备**:LICENSE / 标题图 / CHANGELOG

---

## 🔍 关键文档

- **入门**:README.md
- **分发清单**:MANIFEST.md
- **完整报告**:PROJECT_CLOSE_REPORT.md
- **大纲**:OUTLINE.md