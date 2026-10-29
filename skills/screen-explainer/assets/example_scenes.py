# 場面の割り付けの見本（tests/test_screen_explainer.py がこの形の撮影と声で通す）。compose.py --scenes で読む。
# 台詞 1 行に add を 1 回。割合は、その行の声の長さを 1 とした位置。
#   imgs : いつ、どの撮影に切り替えるか      cam : いつ、どこに寄るか（枠。FULL は全体）
#   cur  : いつ、カーソルをどこへ動かすか    hl  : いつからいつまで、どの枠を赤で囲むか（終わりを 1.2 にすると次の行の頭まで残る）
#   click: クリックの波紋を出す割合          key : キーの札（「Enter」など）を出す割合と文字
# rc(撮影, キー) は rects.json の枠、ctr(撮影, キー) はその中心、box(枠, 枠, pad=) は複数の枠を包む枠。
TAB = (300, 990)                                        # 撮影に rects が無い所は、画面の座標をそのまま書ける

# 行 1: 全体を見せてから、表題 → 入力の欄の順に指す
add(imgs=[(0, "s01")], cam=[(0, FULL)],
    cur=[(0, (1150, 520)), (.15, ctr("s01", "title")), (.55, ctr("s01", "input"))],
    hl=[(.1, .5, rc("s01", "title")), (.5, 1.2, rc("s01", "input"))])

# 行 2: 入力の欄に寄って、数を打ち込む（打ち込み後の撮影 s02 に切り替え、キーの札を出す）
near = box(rc("s01", "input"), rc("s02", "result"), pad=60)
add(imgs=[(0, "s01"), (.55, "s02")], cam=[(0, FULL), (.1, near)],
    cur=[(0, ctr("s01", "input")), (.4, ctr("s01", "input")), (.7, ctr("s02", "result"))],
    hl=[(.1, .55, rc("s01", "input")), (.6, 1.2, rc("s02", "result"))], click=[.42], key=[(.5, "Enter")])

# 行 3: 全体に戻って、別のシートの見出しを押す
add(imgs=[(0, "s02")], cam=[(0, near), (.1, FULL)],
    cur=[(0, ctr("s02", "result")), (.5, TAB)], click=[.55])
