import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# スキルのスクリプトは同じフォルダの lib / common を import する形なので、テストからも同じ形で読めるようにする
for sub in ("skills/video-mascot/scripts", "skills/video-scene/scripts"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.append(p)
