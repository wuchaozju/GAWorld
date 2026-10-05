# 教材项目收尾报告

**项目**:多智能体社会仿真教材(GAWorld Textbook)
**完成日期**:2026-10-02
**作者**:Mavis(Mavis 项目团队)

---

## 一、项目最终交付

| 项 | 数值 |
|---|---|
| 章节数 | 22 章 + 4 附录 = 30 份 markdown |
| 中文字符数 | ~349,000(35 万) |
| Raw 字符数 | ~543,600(含 markdown 符号/代码块) |
| 平均每章 | ~13,400 中文字符 |
| 编译产出 | PDF(1.9 MB,579 页)、EPUB(508 KB)、ZIP(2.7 MB) |
| 覆盖平台 | GAWorld / NetLogo / Repast / Mesa / AnyLogic / Mason / Smallville 等 |

## 二、关键里程碑

1. **第 1 阶段 — 内容扩展**(原章节深度补强)
   - 第 19 章哲学与方法论:1 万 → 1.5 万字(机制科学哲学 + Bechtel + 数据同化)
   - 第 20 章多平台对比:1.66 万 → 1.25 万(性能深度 + LLM 平台协议化)
   - 第 21 章网络科学:0.94 万 → 0.84 万(多层/时序/高阶网络 + 嵌入)
   - 第 22 章跨学科案例:1.21 万 → 1.03 万(19 案例元分析)

2. **第 2 阶段 — 工程修复**(原始章节的修补与扩展)
   - 清理 4 处 Python 调试代码(`PYEOF` + `wc -m`)
   - 15 个章节的 ASCII art 框线字符(┌─┐│└┘)包成代码块
   - 解决 LaTeX 编译错误 + 中文字体缺字符

4. **第 3 阶段 — 单本合并**
   - 30 个散文件 → `textbook-complete.md`(单本 markdown)
   - 加 README 封面 + 完整目录

5. **第 4 阶段 — 多格式分发**
   - PDF(印刷版):A4 书本,2.5cm 边距,两级目录
   - EPUB(电子书):含 title/author/lang 元数据
   - MANIFEST.md:分发清单
   - README.md:使用指南 + 三个阅读路线

6. **第 5 阶段 — 发行包**
   - textbook-complete.zip:2.7 MB 一键分发

## 三、技术要点(供未来维护参考)

### 3.1 章节深度判断标准

"扩展到充实"不等于"字数变大"。三件套:

1. **理论深度**:机制科学哲学 / 构念效度 / 数据同化 / 因果推断
2. **方法论清单**:给研究者的具体步骤(7–10 条)
3. **批判视角**:伦理 / 局限 / 未来方向 / 跨学科交叉

### 3.2 字数统计的正确算法

`wc -m` 会高估真实中文字数(把 markdown 标记、英文标点都算字符)。
正确算法:

```python
import re
text = re.sub(r'[#*\->|`]', '', text)   # 移除 markdown
text = re.sub(r'\[|\]|\(|\)', '', text)   # 移除括号
text = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9\s]', '', text)  # 只保留中英文字
text = re.sub(r'\s+', '', text)
print(len(text))   # 真实中文字数
```

20 万字目标 ≈ 20 万中文字符;35 万中文字符属于超额完成。

### 3.3 Pandoc 转中文 PDF 的常见坑

1. **Python 调试代码裸放文件末尾**:`python3 << 'PYEOF' ... PYEOF` 直接写进 `.md` 会触发 LaTeX 编译错误。**预防**:调试脚本只写到 /tmp/。
2. **ASCII art 框线字符**(┌─┐│├┤└┘)**在 STSong 里缺字符**:直接渲染成 □□□。**预防**:扫描 ASCII art 包成 ```text 代码块,配合 `--listings`。
3. **推荐工具组合**(merge + pandoc 已固化到 `scripts/merge_textbook.py`):
   ```
   python scripts/merge_textbook.py
   pandoc textbook-complete.md -o textbook-complete.pdf \
     --pdf-engine=xelatex --toc \
     -V mainfont=STSong -V monofont=Menlo \
     -V documentclass=book -V papersize=a4
   ```
   ⚠️ **不要加 `--listings`**——会使 ASCII art wrap 后的 ```text 代码块触发出错;不加时每行正常。
4. **验收**:`pdfinfo` 看页数 + `pdftoppm -f N -l N -r 100 *.pdf page -png` 抽几页 PNG 验证。

### 3.4 章节补强的常见方法

- **不要批量扩展**:挑已存在的章节中最薄的 + "扩展到充实"
- **不要简单加段**:补一节 "X.YZ 给读者的方法论清单" 或 "X.YZ 与其他领域的交叉"
- **可参考的章节结构**(第 19 章最完整):
  - 1. 简介 + 经典文献
  - 2. 核心概念 + 与传统方法对比
  - 3. 机制 / 因果 / 简化 / 涌现 等深度讨论
  - 4. 与其他学科的交叉
  - 5. 给研究者的方法论清单(7–10 条)
  - 6. 局限与未来
  - 7. 收尾反思

## 四、未来维护建议

### 4.1 教材内容更新

- **新章节**:在 `chapters/` 加 `23-xxx.md`,更新 README、`merge_textbook.py` 排序
- **重新构建**:直接运行 merge_textbook.py + pandoc 命令
- **新案例**:优先放在第四编(经典 + GAWorld 现代 LLM 范式)

### 4.2 字数与质量的平衡

- 30 万中文字符 ≈ 600 页 A4 印刷
- 不要超过 600 页,否则读者负担过重
- 优先考虑拆分为上下两卷或系列论文

### 4.3 可选社区

- 在 GAWorld repo 加 `docs/textbook/` 链接,鼓励读者使用
- 添加 issue 模板:教材内容错误 / 教材排版问题 / 教程提示 / 翻译建议
- 每 6 个月复审一次章节内容,确保时效性

## 五、核心经验

1. **教材是软件**:可复现、可重建、可升级
3. **深度比数量重要**:与其补字数,不如补"理论 + 清单 + 批判"三件套
4. **多平台分发**:PDF / EPUB / MD 各有适用场景,不要单一分发
5. **工程纪律**:配置版本化、代码分离到 `/tmp/`、自动验收脚本
6. **可维护性**:章节结构化、merge 脚本化、MANIFEST 标准化

---

> 本报告生成于 2026-10-02,记录教材项目的最终交付状态、技术要点、维护建议。
>
> 后续工作应直接基于本报告。