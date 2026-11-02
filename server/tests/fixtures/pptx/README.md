# PPT 解析测试样本

10 份原创的教学课件，模拟老师真实课件里的常见情况，用来测试 M1 的「资料上传与解析」。内容是人教版七上数学第一章「有理数」和英语 Unit 1 的教学内容，由 `generate.py` 生成，可以入库。

每份课件的预期解析结果写在 `manifest.json`。M1 的 PPT 解析器测试用这份清单验收：解析结果要包含 `must_contain` 里的文字、按 `reading_order` 排序、去掉 `noise` 等。

| 文件 | 页数 | 覆盖的情况 |
|---|---|---|
| 01-title-bullets.pptx | 6 | 标题页、标题＋内容版式、多级项目符号 |
| 02-tables-chart.pptx | 3 | 表格、合并单元格（横向和纵向）、柱形图里的文字 |
| 03-images.pptx | 2 | 图片、只在图片里出现的文字、图片替代文字（alt） |
| 04-formula-images.pptx | 2 | 公式是图片（模拟从公式编辑器粘贴）、少量公式是普通文字 |
| 05-speaker-notes.pptx | 2 | 页面文字很少，讲稿在演讲者备注里 |
| 06-freeform-textboxes.pptx | 2 | 全是自由文本框；文件里的顺序和视觉顺序相反；组合图形；带文字的形状 |
| 07-exercises.pptx | 3 | 选择题选项分散在多个文本框；答案在下一页；白色文字藏答案；填空横线 |
| 08-english-unit1.pptx | 4 | 中英混排、带音标的单词表、对话 |
| 09-hidden-empty-overflow.pptx | 5 | 隐藏页、空白页、整页只有图片、文字溢出文本框 |
| 10-long-deck-wide.pptx | 30 | 16:9、长课件、每页重复的页脚和页码（应当作噪声去掉） |

## manifest.json 字段

| 字段 | 含义 |
|---|---|
| `slides` | 页数 |
| `must_contain` | 解析结果里必须出现的文字 |
| `only_in_images` | 只在图片里出现的文字，不做 OCR 时提取不到 |
| `alt_texts` | 图片的替代文字 |
| `notes_contain` | 演讲者备注里必须出现的文字 |
| `hidden_slides` | 隐藏页的页码（从 0 开始） |
| `hidden_text` | 白色等"看不见"的文字，通常是老师藏的答案 |
| `reading_order` | 某页（页码从 0 开始）里文字的正确阅读顺序 |
| `noise` | 每页都重复的页脚等，应当去掉 |
| `tables` / `charts` / `images` | 表格、图表、图片的数量 |

## 重新生成

```bash
cd server
uv run python tests/fixtures/pptx/generate.py
```

图片里的中文用微软雅黑绘制，所以要在 Windows 上运行。2026-11-02 生成后已用 PowerPoint 逐份打开并导出图片核对，没有报错或修复提示。

## 不能覆盖的情况

- **老格式 .ppt**：python-pptx 只能生成 .pptx。老师手里有不少 .ppt，解析流程要先用 LibreOffice 转成 .pptx 或 PDF，这部分要用真实文件测试。
- **SmartArt、动画、嵌入视频和音频、WPS 特有格式**：生成工具不支持，同样需要真实课件补充。
