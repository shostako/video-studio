"""Excel のブックの「写し」を開いて、場面ごとに画面を撮り、強調するセルの画面座標を rects.json に書く。
Windows 側の Python（pywin32・Pillow）で動かす。WSL の python では動かない。元のブックは開かない・保存しない。

usage（WSL から）:
  /mnt/c/.../Python312/python.exe 'C:\\...\\excel_capture.py' <写しの.xlsx> <states.json> <出力フォルダ>
  ※ スクリプトと states.json は Windows から見える場所（C:\\Users\\<you>\\AppData\\Local\\Temp\\... など）に置く

states.json: [ {"name": "s01", "sheet": "シート名", "row": 1, "col": 1, "sel": "A1",
               "rects": {"キー": "D5:D7", ...},
               "type": "6"            （任意。選んだセルに打ち込んだ途中の画面を撮り、撮ったあと Enter で確定する）
               "dropdown": true }     （任意。選んだセルの入力規則のリストを開いた画面を撮る。マウスで▼を押す）
             , ... ]
  row / col は左上に出す行・列（ScrollRow / ScrollColumn）。ウィンドウ枠の固定がある所では、固定の外の最初の行・列を書く。

注意（references/lessons.md に詳しく）:
  - 打ち込みの途中（編集モード）は Excel が COM の呼び出しを拒否する。座標は打つ前に取る（このスクリプトはそうしている）
  - 入力規則のリストは Alt+↓ では開かないことがある。マウスで▼を押す（セルの右端の外側）
  - ウィンドウ枠の固定がある所は、セルが属する区画（Panes(1..4)）で座標を変換しないとずれる
  - 撮った後は写しを保存せずに閉じる。もともと開いていたブックは前に戻す
"""
import ctypes, json, os, sys, time
import win32api, win32com.client, win32con, win32gui
from PIL import ImageGrab

ctypes.windll.user32.SetProcessDPIAware()          # 画面の座標と撮影の座標をそろえる（125 % 表示でずれない）
book, states_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
states = json.load(open(states_path, encoding="utf-8"))

xl = win32com.client.Dispatch("Excel.Application"); xl.Visible = True
before = xl.ActiveWorkbook
wb = xl.Workbooks.Open(os.path.abspath(book)); wb.Activate()
sh = win32com.client.Dispatch("WScript.Shell"); hwnd = xl.Hwnd

def front():
    sh.SendKeys("{ESC}")                                  # Alt を送ると見出しのキーの札が出るので、Esc で前面化を促す
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE); win32gui.SetForegroundWindow(hwnd); time.sleep(0.3)

def pane_for(win, r, c):
    if not win.FreezePanes: return win.Panes(1)
    sr, sc = win.SplitRow, win.SplitColumn; top, left = r <= sr, c <= sc
    if sr and sc: return win.Panes(1 if (top and left) else 2 if top else 3 if left else 4)
    return win.Panes(1 if (top if sr else left) else 2)

def rect(win, ws, addr):
    rg = ws.Range(addr); r0, c0 = rg.Row, rg.Column
    r1, c1 = r0 + rg.Rows.Count - 1, c0 + rg.Columns.Count - 1
    a, b = ws.Cells(r0, c0), ws.Cells(r1, c1)
    p0, p1 = pane_for(win, r0, c0), pane_for(win, r1, c1)
    return [p0.PointsToScreenPixelsX(a.Left), p0.PointsToScreenPixelsY(a.Top),
            p1.PointsToScreenPixelsX(b.Left + b.Width), p1.PointsToScreenPixelsY(b.Top + b.Height)]

def click(x, y):
    win32api.SetCursorPos((int(x), int(y))); time.sleep(0.2)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0); time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0); time.sleep(0.3)
    win32api.SetCursorPos((1900, 200))                    # 撮影の邪魔にならない所へ逃がす（撮影には矢印は写らない）

rects = {}
try:
    front(); xl.WindowState = -4137
    for st in states:
        ws = wb.Worksheets(st["sheet"]); ws.Activate(); front(); win = xl.ActiveWindow
        win.ScrollRow = st.get("row", 1); win.ScrollColumn = st.get("col", 1)
        ws.Range(st.get("sel", "A1")).Select(); time.sleep(0.4)
        rects[st["name"]] = {k: rect(win, ws, a) for k, a in st.get("rects", {}).items()}
        if st.get("dropdown"):
            r = rect(win, ws, st.get("sel", "A1")); click(r[2] + 12, (r[1] + r[3]) / 2); time.sleep(0.8)
            rects[st["name"]]["_arrow"] = [r[2] + 2, r[1], r[2] + 22, r[3]]
        if st.get("type") is not None:
            sh.SendKeys(st["type"]); time.sleep(0.6)
        time.sleep(0.8)
        ImageGrab.grab(all_screens=True).save(os.path.join(out, st["name"] + ".png"))
        if st.get("dropdown"): sh.SendKeys("{ESC}"); time.sleep(0.4)
        if st.get("type") is not None: sh.SendKeys("{ENTER}"); time.sleep(1.0)
        print(st["name"], "ok", flush=True)
    json.dump(rects, open(os.path.join(out, "rects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
finally:
    wb.Close(SaveChanges=False)
    if before is not None:
        try: before.Activate()
        except Exception: pass
print("done", out)
