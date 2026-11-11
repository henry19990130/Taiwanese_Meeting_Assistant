from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml import parse_xml

BROWN = RGBColor(0x2B, 0x24, 0x20)
GREEN = RGBColor(0x5E, 0x7A, 0x5A)
MUTED = RGBColor(0x6B, 0x63, 0x5C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)


def set_run(run, size, color, bold=False):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = "Microsoft JhengHei"
    r_pr = run._r.get_or_add_rPr()
    ea = r_pr.find(qn("a:ea"))
    if ea is None:
        ea = parse_xml(
            '<a:ea xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'typeface="Microsoft JhengHei"/>'
        )
        r_pr.append(ea)
    else:
        ea.set("typeface", "Microsoft JhengHei")


def add_bg(slide):
    fill = slide.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, prs.slide_height)
    fill.line.fill.background()
    fill.fill.solid()
    fill.fill.fore_color.rgb = WHITE
    sp_tree = slide.shapes._spTree
    sp = fill._element
    sp_tree.remove(sp)
    sp_tree.insert(2, sp)


def add_accent_bar(slide):
    bar = slide.shapes.add_shape(1, Inches(0.9), Inches(1.55), Inches(0.12), Inches(0.55))
    bar.line.fill.background()
    bar.fill.solid()
    bar.fill.fore_color.rgb = GREEN


def add_footer(slide, page, total=11):
    box = slide.shapes.add_textbox(Inches(0.9), Inches(6.95), Inches(11.5), Inches(0.35))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = f"覓聲 MeetSum  ·  資安設計  ·  {page:02d}/{total:02d}"
    set_run(run, 12, MUTED, False)
    p.alignment = PP_ALIGN.LEFT


def add_title(slide, text, top=1.45, size=40):
    box = slide.shapes.add_textbox(Inches(1.25), Inches(top), Inches(10.8), Inches(1.0))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    set_run(run, size, BROWN, True)


def add_body(slide, lines, top=2.55, size=20):
    box = slide.shapes.add_textbox(Inches(1.25), Inches(top), Inches(10.8), Inches(3.6))
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(14)
        p.line_spacing = 1.35
        run = p.add_run()
        run.text = line
        set_run(run, size, BROWN, False)


def content_slide(title, lines, page):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)
    add_accent_bar(slide)
    add_title(slide, title)
    add_body(slide, lines)
    add_footer(slide, page)


# 1 cover
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
strip = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(0.28), prs.slide_height)
strip.line.fill.background()
strip.fill.solid()
strip.fill.fore_color.rgb = GREEN

box = slide.shapes.add_textbox(Inches(1.4), Inches(2.35), Inches(10), Inches(0.4))
tf = box.text_frame
p = tf.paragraphs[0]
run = p.add_run()
run.text = "SECURITY DESIGN"
set_run(run, 14, GREEN, True)

box = slide.shapes.add_textbox(Inches(1.4), Inches(2.85), Inches(10.5), Inches(1.5))
tf = box.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
run = p.add_run()
run.text = "覓聲 MeetSum"
set_run(run, 60, BROWN, True)
p2 = tf.add_paragraph()
run2 = p2.add_run()
run2.text = "資安設計"
set_run(run2, 44, BROWN, False)

box = slide.shapes.add_textbox(Inches(1.4), Inches(5.0), Inches(10), Inches(0.8))
tf = box.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
run = p.add_run()
run.text = "密碼、登入、憑證、權限與瀏覽器防護，寫的都是系統實際在做的事。"
set_run(run, 18, MUTED, False)

content_slide("密碼怎麼存", [
    "這項保護用來擋住資料庫被拿走後，密碼仍能被直接還原。",
    "新密碼用 PBKDF2-SHA256，跑二十六萬次迭代，每組密碼各自加鹽。",
    "比對時使用固定時間比較，避免用回應快慢猜對錯。",
    "密碼至少十二碼，而且要同時含英文字母和數字。",
], 2)

content_slide("登入怎麼防猜測", [
    "這項保護用來擋住別人用錯誤回應與嘗試速度猜帳號與密碼。",
    "帳號不存在時，仍走一次相同的密碼比對，時間不會特別短。",
    "失敗一律只回「帳號或密碼錯誤」，不透露是帳號錯還是密碼錯。",
    "同一帳號連續失敗五次，就鎖定十五分鐘。",
], 3)

content_slide("註冊不洩漏帳號", [
    "這項保護用來擋住別人用註冊結果，確認某個帳號有沒有人用。",
    "帳號已經存在時，不告訴對方這個帳號是否已有人註冊。",
    "對外只回固定短句，說明無法完成註冊，請改用其他帳號或稍後再試。",
], 4)

content_slide("兩段憑證", [
    "這項保護用來擋住長期憑證被網頁腳本讀走，同時讓 API 呼叫仍能驗證身分。",
    "Access Token 只放在瀏覽器記憶體，有效一小時，重新整理就消失，呼叫 API 時放在 Authorization。",
    "它不寫進 localStorage、sessionStorage 或 Cookie。",
    "Refresh Token 放在 HttpOnly Cookie，有效三十天，並維持 Secure 與 SameSite=Lax；資料庫只存雜湊。",
], 5)

content_slide("重新整理怎麼維持登入", [
    "這項保護用來擋住重新整理後被迫重新登入，同時不把短效憑證寫進可被腳本讀取的地方。",
    "頁面一打開，若記憶體沒有 Access Token，就先用 Cookie 裡的 Refresh Token 換一張新的。",
    "換到才進入系統；Cookie 也失效，才回到登入頁。",
    "登出時，兩種憑證一起作廢。",
], 6)

content_slide("會議只屬於建立者", [
    "這項保護用來擋住別人用會議編號讀取、修改或刪除不屬於自己的會議。",
    "每場會議都帶著建立者；讀取、修改、刪除都先確認是本人。",
    "資料庫另外強制資料列隔離，連線必須帶上這次使用者的識別，表擁有者也不能繞過。",
    "只有啟動時收回中斷會議，才使用系統身分。",
], 7)

content_slide("瀏覽器防護", [
    "這項保護用來擋住惡意腳本注入、被別站嵌頁，以及瀏覽器把檔案當腳本執行。",
    "內容安全政策只允許本站腳本；並禁止被別的網站嵌進框架。",
    "禁止瀏覽器猜測內容類型；頁面文字用文字節點寫入，不當成 HTML 執行。",
    "只有 HTTPS 回應才加上 HSTS，要求之後也走加密連線。",
], 8)

content_slide("濫用與資訊外洩", [
    "這項保護用來擋住短時間大量操作，以及錯誤訊息洩漏內部細節。",
    "登入、註冊、上傳、摘要、小幫手、換發憑證、讀會議、詞彙庫、重跑校對、刪除會議都有次數限制。",
    "音檔超過五百 MB 拒收；會議工作一次只跑一件。",
    "錯誤回應用固定短句；API 文件關閉，健康檢查只回狀態。",
], 9)

content_slide("實測結果", [
    "這項檢查用來確認會議權限不是只靠畫面隱藏。",
    "另一個帳號讀取示範帳號的會議時，只得到找不到這場會議。",
    "回應裡沒有示範帳號的內容。",
], 10)

content_slide("仍保留的風險", [
    "臨時網址與自行註冊仍開著，知道網址的人仍可自己建立帳號。",
    "次數限制只存在這支程式的記憶體裡，擋不住大量機器把連線本身打滿。",
    "資料庫在 Colab 本機，這次沒有直接連進去查角色密碼。",
], 11)

out = r"C:\Users\student\Desktop\ex\test2\覓聲_MeetSum_資安設計.pptx"
prs.save(out)
print(out)
print(len(prs.slides))
