"""生成 PPT 解析测试用的课件样本。内容为原创，可以入库。

运行：cd server && uv run python tests/fixtures/pptx/generate.py
产物：同目录下 10 份 .pptx 和 manifest.json（每份课件的预期解析结果）。

每份课件覆盖真实老师课件里常见的一类情况，说明见同目录 README.md。
图片里的文字只能靠 OCR 取到，manifest 里单独列在 only_in_images。
图片中的中文用微软雅黑绘制，所以重新生成需要在 Windows 上运行；课件文件本身已入库，测试不需要重新生成。
"""

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent
FONT_FILE = "C:/Windows/Fonts/msyh.ttc"
CJK = "微软雅黑"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLUE = RGBColor(0x1F, 0x4E, 0x9A)
RED = RGBColor(0xC0, 0x1C, 0x28)

# 默认模板的版式编号
TITLE, TITLE_CONTENT, TITLE_ONLY, BLANK = 0, 1, 5, 6


# —— 工具函数 ——


def style_run(run, *, size=None, bold=None, color=None):
    run.font.name = CJK
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    # 中文字体要单独设在 a:ea 上，否则 PowerPoint 会用默认东亚字体
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        rpr.append(ea)
    ea.set("typeface", CJK)


def fill_frame(frame, lines, *, size=24, color=None, bold=False):
    """lines：字符串，或 (文字, 缩进级别) 元组。"""
    frame.word_wrap = True
    for i, line in enumerate(lines):
        text, level = (line, 0) if isinstance(line, str) else line
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.level = level
        run = para.add_run()
        run.text = text
        style_run(run, size=size - 2 * level, color=color, bold=bold)


def textbox(slide, lines, left, top, width, height, **kw):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    fill_frame(box.text_frame, [lines] if isinstance(lines, str) else lines, **kw)
    return box


def set_title(slide, text, size=32):
    slide.shapes.title.text_frame.clear()
    run = slide.shapes.title.text_frame.paragraphs[0].add_run()
    run.text = text
    style_run(run, size=size, bold=True, color=BLUE)


def set_body(slide, lines, size=24):
    body = slide.placeholders[1].text_frame
    body.clear()
    fill_frame(body, lines, size=size)


def image(draw_fn, size=(900, 300)):
    img = Image.new("RGB", size, "white")
    draw_fn(ImageDraw.Draw(img), lambda px: ImageFont.truetype(FONT_FILE, px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def text_image(lines, size=(900, 260), px=44):
    def draw(d, font):
        for i, line in enumerate(lines):
            d.text((30, 30 + i * (px + 24)), line, fill="black", font=font(px))

    return image(draw, size)


def number_line_image():
    def draw(d, font):
        y, x0, step = 150, 90, 120
        d.line((40, y, 860, y), fill="black", width=4)
        d.polygon([(860, y), (838, y - 12), (838, y + 12)], fill="black")
        for k in range(-3, 4):
            x = x0 + (k + 3) * step
            d.line((x, y - 14, x, y + 14), fill="black", width=3)
            d.text((x - 14, y + 22), f"{k}".replace("-", "−"), fill="black", font=font(32))
        x_a = x0 + 0.5 * step
        d.ellipse((x_a - 9, y - 9, x_a + 9, y + 9), fill="red")
        d.text((x_a - 70, y - 75), "点 A 表示 −2.5", fill="red", font=font(30))
        d.text((x0 + 3 * step - 10, y - 60), "O", fill="black", font=font(30))

    return image(draw, (900, 260))


def thermometer_image():
    def draw(d, font):
        d.rounded_rectangle((120, 30, 170, 330), radius=20, outline="black", width=4)
        d.ellipse((105, 300, 185, 380), outline="black", width=4, fill="#d33")
        d.rectangle((135, 210, 155, 330), fill="#d33")
        for i, t in enumerate(range(10, -11, -5)):
            yy = 60 + i * 50
            d.line((170, yy, 195, yy), fill="black", width=3)
            d.text((205, yy - 18), f"{t} ℃".replace("-", "−"), fill="black", font=font(28))
        d.text((320, 150), "此时温度：零下 5 ℃，记作 −5 ℃", fill="black", font=font(34))

    return image(draw, (900, 400))


class Deck:
    def __init__(self, name, *, subject, topic, features, wide=False):
        self.name = name
        self.prs = Presentation()
        if wide:
            self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.expect = {
            "subject": subject,
            "topic": topic,
            "features": features,
            "slides": 0,
            "must_contain": [],
            "only_in_images": [],
            "alt_texts": [],
            "notes_contain": [],
            "hidden_slides": [],
            "hidden_text": [],
            "reading_order": {},
            "noise": [],
            "tables": 0,
            "charts": 0,
            "images": 0,
        }

    def slide(self, layout=BLANK):
        return self.prs.slides.add_slide(self.prs.slide_layouts[layout])

    def expect_text(self, *texts):
        self.expect["must_contain"].extend(texts)

    def picture(self, slide, stream, left, top, width, *, in_image=(), alt=None):
        pic = slide.shapes.add_picture(stream, Inches(left), Inches(top), width=Inches(width))
        if alt:
            pic._element.nvPicPr.cNvPr.set("descr", alt)
            self.expect["alt_texts"].append(alt)
        self.expect["only_in_images"].extend(in_image)
        self.expect["images"] += 1
        return pic

    def notes(self, slide, text):
        slide.notes_slide.notes_text_frame.text = text

    def save(self):
        self.expect["slides"] = len(self.prs.slides)
        self.prs.save(OUT / self.name)
        return self.name, self.expect


# —— 10 份课件 ——


def deck_01():
    d = Deck(
        "01-title-bullets.pptx",
        subject="数学",
        topic="1.1 正数和负数（第 1 课时）",
        features=["标题页版式", "标题＋内容版式", "多级项目符号"],
    )
    s = d.slide(TITLE)
    set_title(s, "1.1 正数和负数（第 1 课时）", 36)
    s.placeholders[1].text = "人教版 · 七年级上册 · 第一章 有理数"
    d.expect_text("1.1 正数和负数（第 1 课时）", "第一章 有理数")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "情境引入")
    set_body(
        s,
        [
            "生活中有很多“相反意义的量”",
            ("气温有零上和零下", 1),
            ("海拔有高于海平面和低于海平面", 1),
            ("收入和支出", 1),
            "只用小学学过的数，能把这些量表示清楚吗？",
        ],
    )
    d.expect_text("相反意义的量", "海拔有高于海平面和低于海平面")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "学习目标")
    set_body(
        s,
        [
            "1. 理解正数、负数的意义",
            "2. 会用正数和负数表示具有相反意义的量",
            "3. 知道 0 既不是正数也不是负数",
        ],
    )
    d.expect_text("会用正数和负数表示具有相反意义的量")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "新知讲解")
    set_body(
        s,
        [
            "像 3、1.8、2/3 这样大于 0 的数叫做正数",
            ("正数前面有时也加上“+”号，如 +3", 1),
            "在正数前面加上符号“−”的数叫做负数",
            ("−3 读作“负三”", 1),
            ("−2.7 读作“负二点七”", 1),
            "0 既不是正数也不是负数",
            ("0 是正数和负数的分界", 1),
        ],
    )
    d.expect_text("大于 0 的数叫做正数", "−3 读作“负三”", "0 既不是正数也不是负数")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "例题")
    set_body(
        s, ["例 1 如果收入 100 元记作 +100 元，那么支出 60 元记作多少？", ("解：支出 60 元记作 −60 元。", 1)]
    )
    d.expect_text("支出 60 元记作 −60 元")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "课堂小结")
    set_body(
        s,
        ["正数：大于 0 的数", "负数：在正数前面加“−”的数", "用正负数表示相反意义的量，要先规定哪个方向为正"],
    )
    d.expect_text("要先规定哪个方向为正")
    return d.save()


def deck_02():
    d = Deck(
        "02-tables-chart.pptx",
        subject="数学",
        topic="正负数的应用：气温统计",
        features=["表格", "合并单元格", "柱形图（图表里的文字）"],
    )
    s = d.slide(TITLE_ONLY)
    set_title(s, "某市一周气温记录")
    rows = [
        ("星期一", "6", "−1"),
        ("星期二", "4", "−3"),
        ("星期三", "2", "−5"),
        ("星期四", "5", "−2"),
        ("星期五", "8", "0"),
        ("星期六", "9", "1"),
        ("星期日", "7", "−1"),
    ]
    tbl = s.shapes.add_table(len(rows) + 2, 3, Inches(0.8), Inches(1.6), Inches(8.4), Inches(4.8)).table
    tbl.cell(0, 0).merge(tbl.cell(0, 2))
    tbl.cell(0, 0).text = "某市一周气温（单位：℃）"
    for c, head in enumerate(["日期", "最高气温", "最低气温"]):
        tbl.cell(1, c).text = head
    for r, row in enumerate(rows, start=2):
        for c, val in enumerate(row):
            tbl.cell(r, c).text = val
    d.expect["tables"] += 1
    d.expect_text("某市一周气温（单位：℃）", "星期三", "最低气温")

    s = d.slide(TITLE_ONLY)
    set_title(s, "有理数的分类")
    tbl = s.shapes.add_table(5, 3, Inches(1.5), Inches(1.8), Inches(7), Inches(4)).table
    tbl.cell(0, 0).merge(tbl.cell(2, 0))
    tbl.cell(0, 0).text = "整数"
    tbl.cell(3, 0).merge(tbl.cell(4, 0))
    tbl.cell(3, 0).text = "分数"
    for r, (kind, example) in enumerate(
        [
            ("正整数", "1，2，3，…"),
            ("0", "0"),
            ("负整数", "−1，−2，−3，…"),
            ("正分数", "1/2，0.3，…"),
            ("负分数", "−1/2，−0.3，…"),
        ]
    ):
        tbl.cell(r, 1).text = kind
        tbl.cell(r, 2).text = example
    d.expect["tables"] += 1
    d.expect_text("正整数", "负分数", "−1，−2，−3，…")

    s = d.slide(TITLE_ONLY)
    set_title(s, "用图表看最低气温")
    data = CategoryChartData()
    data.categories = [r[0] for r in rows]
    data.add_series("最低气温", [float(r[2].replace("−", "-")) for r in rows])
    chart = s.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.8), Inches(1.5), Inches(8.4), Inches(5), data
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = "一周最低气温（℃）"
    chart.plots[0].series[0].invert_if_negative = False  # 默认负值柱子是白色，不像真实课件
    d.expect["charts"] += 1
    d.expect_text("一周最低气温（℃）")
    return d.save()


def deck_03():
    d = Deck(
        "03-images.pptx",
        subject="数学",
        topic="1.2.2 数轴",
        features=["图片", "图片里的文字", "图片替代文字（alt）"],
    )
    s = d.slide(TITLE_ONLY)
    set_title(s, "数轴的概念")
    textbox(s, ["规定了原点、正方向和单位长度的直线叫做数轴。"], 0.6, 1.4, 8.8, 0.8, size=24)
    d.picture(
        s,
        number_line_image(),
        0.8,
        2.6,
        8.4,
        in_image=["点 A 表示 −2.5"],
        alt="数轴示意图：原点 O，向右为正方向，单位长度为 1",
    )
    d.expect_text("规定了原点、正方向和单位长度的直线叫做数轴")

    s = d.slide(TITLE_ONLY)
    set_title(s, "温度计与数轴")
    d.picture(s, thermometer_image(), 0.8, 1.5, 8.4, in_image=["此时温度：零下 5 ℃，记作 −5 ℃"])
    textbox(s, "温度计的刻度和数轴很像：0 以上是正数，0 以下是负数。", 0.6, 6.2, 8.8, 0.8, size=20)
    d.expect_text("0 以下是负数")
    return d.save()


def deck_04():
    d = Deck(
        "04-formula-images.pptx",
        subject="数学",
        topic="1.2.4 绝对值",
        features=["公式是图片（模拟从公式编辑器粘贴）", "少量公式是普通文字"],
    )
    s = d.slide(TITLE_ONLY)
    set_title(s, "绝对值的代数意义")
    textbox(
        s,
        "一个正数的绝对值是它本身；一个负数的绝对值是它的相反数；0 的绝对值是 0。",
        0.6,
        1.4,
        8.8,
        1.0,
        size=22,
    )
    d.picture(
        s,
        text_image(["|a| = a    (a > 0)", "|a| = 0    (a = 0)", "|a| = −a   (a < 0)"], size=(900, 260)),
        1.5,
        2.8,
        7,
        in_image=["|a| = −a   (a < 0)"],
    )
    d.expect_text("一个负数的绝对值是它的相反数")

    s = d.slide(TITLE_ONLY)
    set_title(s, "练一练")
    textbox(s, ["|−3| = 3", "|+5| = 5", "|0| = 0"], 0.8, 1.6, 4, 2.5, size=28)
    d.picture(
        s,
        text_image(["若 |x| = 2，则 x = ±2"], size=(900, 120)),
        1,
        4.4,
        8,
        in_image=["若 |x| = 2，则 x = ±2"],
    )
    d.expect_text("|−3| = 3")
    return d.save()


def deck_05():
    d = Deck(
        "05-speaker-notes.pptx",
        subject="数学",
        topic="1.2.3 相反数",
        features=["页面文字很少，讲稿在演讲者备注里"],
    )
    s = d.slide(TITLE_ONLY)
    set_title(s, "相反数")
    textbox(s, "只有符号不同的两个数叫做互为相反数。", 0.6, 2.5, 8.8, 1, size=28)
    d.notes(
        s,
        "先让学生在数轴上找出 2 和 −2，观察它们到原点的距离。\n"
        "引导学生说出：它们在原点两侧，到原点距离相等。\n"
        "再给出定义，强调“只有符号不同”。",
    )
    d.expect_text("只有符号不同的两个数叫做互为相反数")
    d.expect["notes_contain"] += ["先让学生在数轴上找出 2 和 −2", "强调“只有符号不同”"]

    s = d.slide(TITLE_ONLY)
    set_title(s, "特别注意")
    textbox(s, "0 的相反数是什么？", 0.6, 2.5, 8.8, 1, size=28)
    d.notes(s, "强调：0 的相反数是 0。\n易错点：学生容易认为 0 没有相反数。")
    d.expect["notes_contain"] += ["0 的相反数是 0", "学生容易认为 0 没有相反数"]
    return d.save()


def deck_06():
    d = Deck(
        "06-freeform-textboxes.pptx",
        subject="数学",
        topic="1.2.5 有理数的大小比较",
        features=[
            "全部是自由文本框，没有占位符",
            "文本框在文件里的顺序和视觉顺序相反",
            "组合图形",
            "带文字的形状",
        ],
    )
    s = d.slide()
    textbox(s, "有理数的大小比较", 0.6, 0.4, 8.8, 0.9, size=34, bold=True, color=BLUE)
    # 故意按从下到上的顺序添加：解析时要按位置排序，不能按文件里的顺序
    order = [
        "比较方法一：数轴法——右边的数总比左边的大",
        "比较方法二：法则法——两个负数，绝对值大的反而小",
        "例：比较 −3 和 −5 的大小",
    ]
    for i, text in reversed(list(enumerate(order))):
        textbox(s, text, 0.6, 1.6 + i * 1.3, 8.8, 1.0, size=24)
    d.expect["reading_order"][str(len(d.prs.slides) - 1)] = order  # 页码从 0 开始，和 hidden_slides 一致
    d.expect_text(*order)

    s = d.slide()
    textbox(s, "易错点提醒", 0.6, 0.4, 8.8, 0.9, size=34, bold=True, color=BLUE)
    grp = s.shapes.add_group_shape()
    for i, text in enumerate(["−3 > −5", "因为 |−3| < |−5|"]):
        shape = grp.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8 + i * 4.4), Inches(2), Inches(4), Inches(1.4)
        )
        fill_frame(shape.text_frame, [text], size=26, color=WHITE)
    warn = s.shapes.add_shape(MSO_SHAPE.WAVE, Inches(2.5), Inches(4.4), Inches(5), Inches(1.4))
    fill_frame(warn.text_frame, ["两个负数比较，不能只看数字本身"], size=22, color=WHITE)
    d.expect_text("−3 > −5", "因为 |−3| < |−5|", "两个负数比较，不能只看数字本身")
    return d.save()


def deck_07():
    d = Deck(
        "07-exercises.pptx",
        subject="数学",
        topic="第一章 课堂练习",
        features=["选择题选项分散在多个文本框", "答案在下一页", "白色文字藏答案", "填空横线"],
    )
    s = d.slide()
    textbox(s, "1. 下列各数中，是负数的是（　　）", 0.6, 0.8, 8.8, 0.8, size=26)
    for i, opt in enumerate(["A. 0", "B. −2", "C. 3", "D. 1/2"]):
        textbox(s, opt, 1.0 + (i % 2) * 4.2, 2.0 + (i // 2) * 1.0, 3.8, 0.8, size=24)
    textbox(s, "【答案】B", 7.5, 6.6, 2, 0.6, size=14, color=WHITE)  # 老师常用的“隐藏答案”
    d.expect_text("下列各数中，是负数的是", "A. 0", "B. −2", "C. 3", "D. 1/2")
    d.expect["hidden_text"].append("【答案】B")

    s = d.slide()
    textbox(
        s,
        "2. 填空：如果向东走 5 米记作 +5 米，那么向西走 3 米记作 ________ 米。",
        0.6,
        0.8,
        8.8,
        1.2,
        size=26,
    )
    d.expect_text("向西走 3 米记作 ________ 米")

    s = d.slide()
    textbox(s, "参考答案", 0.6, 0.4, 8.8, 0.9, size=34, bold=True, color=RED)
    textbox(s, ["1. B", "2. −3"], 0.8, 1.6, 8, 2, size=28)
    d.expect_text("参考答案", "2. −3")
    return d.save()


def deck_08():
    d = Deck(
        "08-english-unit1.pptx",
        subject="英语",
        topic="Unit 1 You and Me · Section A",
        features=["中英混排", "单词表（音标）", "对话"],
    )
    s = d.slide(TITLE)
    set_title(s, "Unit 1 You and Me", 40)
    s.placeholders[1].text = "Section A · 认识新同学"
    d.expect_text("Unit 1 You and Me", "认识新同学")

    s = d.slide(TITLE_ONLY)
    set_title(s, "Words and Expressions")
    words = [
        ("classmate", "/ˈklɑːsmeɪt/", "同学"),
        ("hobby", "/ˈhɒbi/", "业余爱好"),
        ("country", "/ˈkʌntri/", "国家"),
        ("favourite", "/ˈfeɪvərɪt/", "最喜爱的"),
    ]
    tbl = s.shapes.add_table(len(words) + 1, 3, Inches(1), Inches(1.6), Inches(8), Inches(3.6)).table
    for c, head in enumerate(["Word", "Phonetic", "中文"]):
        tbl.cell(0, c).text = head
    for r, row in enumerate(words, start=1):
        for c, val in enumerate(row):
            tbl.cell(r, c).text = val
    d.expect["tables"] += 1
    d.expect_text("/ˈklɑːsmeɪt/", "业余爱好", "favourite")

    s = d.slide(TITLE_ONLY)
    set_title(s, "Listen and Talk")
    textbox(
        s,
        [
            "A: Hi, I'm Peter. What's your name?",
            "B: My name is Emma. Nice to meet you!",
            "A: Nice to meet you, too. Where are you from?",
            "B: I'm from Canada.",
        ],
        0.8,
        1.6,
        8.6,
        3,
        size=24,
    )
    d.expect_text("What's your name?", "Nice to meet you, too.")

    s = d.slide(TITLE_CONTENT)
    set_title(s, "Grammar Focus")
    set_body(
        s,
        [
            "be 动词的用法",
            ("I am → I'm", 1),
            ("You are → You're", 1),
            ("He / She is → He's / She's", 1),
            "介绍自己：My name is … / I'm from …",
        ],
    )
    d.expect_text("be 动词的用法", "He / She is → He's / She's")
    return d.save()


def deck_09():
    d = Deck(
        "09-hidden-empty-overflow.pptx",
        subject="数学",
        topic="边角情况",
        features=["隐藏页", "空白页", "只有图片的页", "文字溢出文本框"],
    )
    s = d.slide(TITLE_ONLY)
    set_title(s, "本节课内容")
    d.expect_text("本节课内容")

    s = d.slide(TITLE_ONLY)
    set_title(s, "（备用）拓展材料")
    textbox(s, "这页是隐藏页，上课时不放映。", 0.6, 2, 8.8, 1, size=24)
    s._element.set("show", "0")
    d.expect["hidden_slides"].append(1)
    d.expect_text("这页是隐藏页，上课时不放映")

    d.slide()  # 空白页

    s = d.slide()
    d.picture(
        s,
        text_image(["整页只有一张图片", "图片里写着：负数比 0 小"], size=(900, 300)),
        0.5,
        1.5,
        9,
        in_image=["图片里写着：负数比 0 小"],
    )

    s = d.slide(TITLE_ONLY)
    set_title(s, "阅读材料：负数的历史")
    long = (
        "我国是世界上最早认识和使用负数的国家之一。古代数学著作中已经用不同颜色的算筹表示正数和负数，"
        "并给出了正负数的加减运算法则。"
    ) * 6 + "（本段结束）"
    textbox(s, long, 0.6, 1.5, 8.8, 2.0, size=20)  # 文字远超文本框高度
    d.expect_text("最早认识和使用负数的国家之一", "（本段结束）")
    return d.save()


def deck_10():
    d = Deck(
        "10-long-deck-wide.pptx",
        subject="数学",
        topic="第一章 有理数 复习课（30 页）",
        features=["16:9", "30 页长课件", "每页重复的页脚和页码（应当作噪声去掉）"],
        wide=True,
    )
    footer = "七年级数学备课组 · 内部资料"
    points = ["正数和负数", "有理数的概念", "数轴", "相反数", "绝对值", "有理数的大小比较"]
    for i in range(30):
        s = d.slide()
        topic = points[i % len(points)]
        textbox(s, f"知识点 {i + 1}：{topic}", 0.6, 0.4, 12, 0.9, size=32, bold=True, color=BLUE)
        textbox(
            s,
            [f"要点：复习“{topic}”的定义和典型例题（第 {i + 1} 页）", ("回顾课本例题，说出解题思路", 1)],
            0.6,
            1.6,
            12,
            3,
            size=24,
        )
        textbox(s, footer, 0.4, 6.9, 6, 0.4, size=12)
        textbox(s, f"{i + 1} / 30", 11.8, 6.9, 1.2, 0.4, size=12)
    d.expect_text("知识点 1：正数和负数", f"知识点 30：{points[29 % len(points)]}", "第 30 页")
    d.expect["noise"].append(footer)
    return d.save()


def main():
    manifest = dict(
        fn()
        for fn in (deck_01, deck_02, deck_03, deck_04, deck_05, deck_06, deck_07, deck_08, deck_09, deck_10)
    )
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, exp in manifest.items():
        print(f"{name}: {exp['slides']} 页")


if __name__ == "__main__":
    main()
