"""Render reel.html frame-by-frame to MP4.  python render.py [--stills t1,t2,...]"""
import base64, subprocess, sys, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
FPS = 60
GRAB = "t => { render(t); return document.getElementById('c').toDataURL('image/png').split(',')[1]; }"


def main():
    stills = next((a.split(",") for a in sys.argv[1:] if not a.startswith("--")), None)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--force-color-profile=srgb"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((HERE / "reel.html").as_uri())
        assert pg.evaluate("window.ready"), "Poppins failed to load"
        dur = pg.evaluate("DUR")
        if stills:
            (HERE / "stills").mkdir(exist_ok=True)
            for t in stills:
                (HERE / "stills" / f"t{float(t):05.2f}.png").write_bytes(base64.b64decode(pg.evaluate(GRAB, float(t))))
            return
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
                               "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
                               "-movflags", "+faststart", str(HERE / "silent.mp4")], stdin=subprocess.PIPE)
        n = round(FPS * dur)
        for i in range(n):
            ff.stdin.write(base64.b64decode(pg.evaluate(GRAB, i / FPS)))
            if i % 120 == 0:
                print(f"frame {i}/{n}", flush=True)
        ff.stdin.close()
        assert ff.wait() == 0
        b.close()


if __name__ == "__main__":
    main()
