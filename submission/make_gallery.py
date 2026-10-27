"""Render the Devpost image set (3:2, 1800x1200) from real UI screenshots and showreel frames.
    python submission/make_gallery.py
"""
import pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "gallery"
MARK = (ROOT / "web/public/coolpilot-mark.svg").read_text()
FONT = (ROOT / "web/public/fonts/poppins-normal-700.woff2").as_uri()
FONT5 = (ROOT / "web/public/fonts/poppins-normal-500.woff2").as_uri()
SHOT = lambda n: (ROOT / "submission/screenshots" / n).as_uri()
FRAME = lambda n: (OUT / f"_frame_{n}.png").as_uri()
URL = "n7ebpehiuh2hczk2uzsherigia0pyqfg.lambda-url.us-east-1.on.aws"

BASE = f"""<style>@font-face{{font-family:P;font-weight:700;src:url({FONT})}}@font-face{{font-family:P;font-weight:500;src:url({FONT5})}}
*{{box-sizing:border-box;margin:0}} body{{width:1800px;height:1200px;background:#06070a;color:#f4f5f7;font-family:P;overflow:hidden;position:relative}}
.grid{{position:absolute;inset:0;background-image:radial-gradient(#ffffff14 1.5px,transparent 1.5px);background-size:48px 48px}}
.glow{{position:absolute;width:1200px;height:1200px;border-radius:50%;filter:blur(120px);opacity:.35}}
.bar{{position:absolute;left:0;right:0;bottom:0;height:10px;background:linear-gradient(90deg,#56ce27 33%,#0088ff 33% 66%,#ff3038 66%)}}
.brand{{position:absolute;left:80px;top:64px;display:flex;align-items:center;gap:18px;font-size:40px}} .brand svg{{width:58px;height:58px}}
.brand b{{font-weight:700}} .brand span{{font-weight:500}}
h1{{position:absolute;left:80px;top:150px;font-size:76px;line-height:1.05;letter-spacing:-2px;font-weight:700;max-width:1640px}}
h1 em{{font-style:normal;color:#0088ff}} h1 i{{font-style:normal;color:#56ce27}}
.win{{position:absolute;left:80px;right:80px;top:345px;bottom:70px;border-radius:22px;background:#0b0d12;border:2px solid #2a2f38;overflow:hidden;box-shadow:0 0 120px #0088ff40}}
.top{{height:52px;display:flex;align-items:center;gap:12px;padding:0 22px;border-bottom:1px solid #1a1d23}} .d{{width:15px;height:15px;border-radius:50%}}
.u{{margin-left:22px;flex:1;height:32px;border-radius:16px;background:#151922;color:#7f8590;font:500 17px Menlo,monospace;display:flex;align-items:center;justify-content:center}}
.win img{{width:100%;height:calc(100% - 52px);object-fit:cover;object-position:top}}
.tag{{position:absolute;right:80px;top:62px;padding:14px 26px;border-radius:40px;font:700 26px Menlo,monospace;background:#06070acc}}
</style><div class=grid></div>"""
BRAND = f'<div class=brand>{MARK}<div><b>COOL</b><span>Pilot</span></div></div>'

def window(img, fit="cover"):
    return (f'<div class=win><div class=top><div class=d style="background:#ff3038"></div><div class=d style="background:#f5a524"></div>'
            f'<div class=d style="background:#56ce27"></div><div class=u>{URL}</div></div><img src="{img}" style="object-fit:{fit}"></div>')

PAGES = {
  # preview / thumbnail: almost no text, readable when tiny
  "00-preview": f"""{BASE}<div class=glow style="left:-300px;top:-300px;background:#0088ff"></div><div class=glow style="right:-400px;bottom:-500px;background:#56ce27"></div>
    <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px">
      <div style="display:flex;align-items:center;gap:40px"><div style="width:250px;height:250px">{MARK}</div>
      <div style="font-size:200px;letter-spacing:-6px;line-height:1"><b style="font-weight:700">COOL</b><span style="font-weight:500">Pilot</span></div></div>
      <div style="font-size:64px;font-weight:500;color:#c9ccd2">Cameras that check themselves.</div>
      <div style="display:flex;gap:24px;font:700 40px Menlo,monospace"><span style="color:#56ce27">OpenCV 5</span><span style="color:#7f8590">·</span><span style="color:#0088ff">AI agent</span><span style="color:#7f8590">·</span><span style="color:#ff9900">AWS Graviton</span></div>
    </div><div class=bar></div>""",
  "01-live-replay": f"""{BASE}{BRAND}<h1>Live on <em>AWS Graviton</em>: three cameras, every frame checked.</h1>{window(SHOT('replay-live.jpg'))}<div class=tag style="color:#56ce27;border:2px solid #56ce27">OpenCV 5 · real time</div><div class=bar></div>""",
  "02-verifier": f"""{BASE}{BRAND}<h1>The agent measures twice: <i>232 → 0</i> false alarms an hour.</h1>{window(SHOT('verifier-dismiss.jpg'))}<div class=tag style="color:#0088ff;border:2px solid #0088ff">texture · DNN · motion</div><div class=bar></div>""",
  "03-footage": f"""{BASE}{BRAND}<h1>Check your own footage: <em>what went wrong, and when.</em></h1>{window(SHOT('footage-report.jpg'))}<div class=tag style="color:#ff3038;border:2px solid #ff3038">blackout · 2.07–3.83 s</div><div class=bar></div>""",
  "04-overview": f"""{BASE}{BRAND}<h1>Camera health, <em>measured frame by frame.</em></h1>{window(SHOT('overview.jpg'))}<div class=bar></div>""",
  "05-opencv5": f"""{BASE}<img src="{FRAME('opencv5')}" style="position:absolute;left:0;top:90px;width:1800px;height:1013px;object-fit:cover"><div class=bar></div>""",
  "06-agent-loop": f"""{BASE}<img src="{FRAME('loop')}" style="position:absolute;left:0;top:90px;width:1800px;height:1013px;object-fit:cover"><div class=bar></div>""",
  "07-cool": f"""{BASE}<img src="{FRAME('cool')}" style="position:absolute;left:0;top:90px;width:1800px;height:1013px;object-fit:cover"><div class=bar></div>""",
  "08-night": f"""{BASE}{BRAND}<h1>Night is night, <i>not a broken camera.</i></h1>{window(SHOT('footage-night.jpg'))}<div class=tag style="color:#f5a524;border:2px solid #f5a524">night 0 → 29 / 90</div><div class=bar></div>""",
}

with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files"])
    pg = b.new_page(viewport={"width": 1800, "height": 1200})
    for name, html in PAGES.items():
        f = OUT / f"_{name}.html"; f.write_text(f"<!doctype html><meta charset=utf-8>{html}")
        pg.goto(f.as_uri()); pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT / f"{name}.png")); f.unlink()
        print(name)
    b.close()
