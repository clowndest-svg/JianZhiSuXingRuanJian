"""从一张原始方形 artwork 生成全套启动图标（5 密度位图 + 自适应层 + 单色层 + 网页图标）。

为什么做成脚本而不是手工导图：换图标要同时改 8 个文件，手工漏一个就会出现
"桌面上是新的、下拉设置里是旧的"这种查半天的不一致；重跑一次脚本即可复现全部产物。
"""
import argparse, json, os
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "app" / "src" / "main" / "res"
ASSETS = ROOT / "app" / "src" / "main" / "assets"
DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
ADAPTIVE = 432          # 108dp @ xxxhdpi，nodpi 一份足够所有密度缩放
SAFE_FILL = 0.88        # 自适应层里 artwork 占画布的比例：留出遮罩余量，圆形桌面不会切掉人物


def square_artwork(path):
    """裁掉外围白边，返回带透明圆角外轮廓的 RGBA。"""
    im = Image.open(path).convert("RGB")
    if abs(im.width - im.height) > 2:
        side = min(im.width, im.height)
        im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                      (im.width + side) // 2, (im.height + side) // 2))
    marks = im.copy()
    seed = (255, 0, 255)
    for corner in ((0, 0), (marks.width - 1, 0), (0, marks.height - 1), (marks.width - 1, marks.height - 1)):
        ImageDraw.floodfill(marks, corner, seed, thresh=48)
    outside = marks.load()
    src = im.load()
    rgba = im.convert("RGBA")
    out = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            if outside[x, y] == seed:
                out[x, y] = (0, 0, 0, 0)
    box = rgba.getbbox()
    trimmed = rgba.crop(box) if box else rgba
    side = min(trimmed.width, trimmed.height)
    return trimmed.crop(((trimmed.width - side) // 2, (trimmed.height - side) // 2,
                         (trimmed.width + side) // 2, (trimmed.height + side) // 2))


def corner_color(art):
    """取 artwork 自己四角的平均色当自适应背景，避免图标外圈出现第二种黑。"""
    px = art.load()
    n = max(2, art.width // 40)
    samples = [px[x, y] for x in range(n) for y in range(n)]
    samples += [px[art.width - 1 - x, art.height - 1 - y] for x in range(n) for y in range(n)]
    rgb = tuple(sum(c[i] for c in samples) // len(samples) for i in range(3))
    return "#%02X%02X%02X" % rgb


def on_canvas(art, size, fill, scale=1.0):
    canvas = Image.new("RGBA", (size, size), fill)
    side = int(size * scale)
    scaled = art.resize((side, side), Image.LANCZOS)
    canvas.paste(scaled, ((size - side) // 2, (size - side) // 2), scaled)
    return canvas


def silhouette(art, size, scale):
    """单色层只保留明度轮廓：深色底变透明，白色人形保留。"""
    gray = art.convert("L").resize((size, size), Image.LANCZOS)
    side = int(size * scale)
    gray = gray.crop(((size - side) // 2,) * 2 + ((size + side) // 2,) * 2)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    white = Image.new("RGBA", gray.size, (255, 255, 255, 255))
    white.putalpha(gray)
    out.paste(white, ((size - side) // 2, (size - side) // 2), white)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="原始方形 artwork（png/jpg）")
    args = ap.parse_args()
    art = square_artwork(args.source)
    written = []

    for density, px in DENSITIES.items():
        folder = RES / ("mipmap-" + density)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            target = folder / name
            art.resize((px, px), Image.LANCZOS).save(target)
            written.append(str(target.relative_to(ROOT)))

    # 通知栏小图标：Android 会把它整体染成单色，所以只能给白色剪影 + 透明底，
    # 直接拿彩色启动图标去当小图标，在状态栏里会糊成一团黑块。
    for density, px in {"mdpi": 24, "hdpi": 36, "xhdpi": 48, "xxhdpi": 72}.items():
        folder = RES / ("drawable-" + density)
        folder.mkdir(parents=True, exist_ok=True)
        silhouette(art, px, 1.0).save(folder / "ic_stat_qingsu.png")
        written.append(str((folder / "ic_stat_qingsu.png").relative_to(ROOT)))

    nodpi = RES / "drawable-nodpi"
    nodpi.mkdir(parents=True, exist_ok=True)
    on_canvas(art, ADAPTIVE, (0, 0, 0, 0), SAFE_FILL).save(nodpi / "ic_launcher_foreground.png")
    silhouette(art, ADAPTIVE, SAFE_FILL).save(nodpi / "ic_launcher_monochrome.png")
    written += [str((nodpi / f).relative_to(ROOT)) for f in ("ic_launcher_foreground.png", "ic_launcher_monochrome.png")]
    # 旧的矢量层必须删掉：同名资源同时存在于 drawable/ 与 drawable-nodpi/ 时，
    # 打包按限定符优先级取，很容易留下"改了没生效"的旧图。
    removed = []
    for stale in ("drawable/ic_launcher_foreground.xml", "drawable/ic_launcher_monochrome.xml"):
        path = RES / stale
        if path.exists():
            path.unlink()
            removed.append(stale)

    colors = RES / "values" / "colors.xml"
    text = colors.read_text(encoding="utf-8")
    hex_color = corner_color(art)
    import re
    updated = re.sub(r'<color name="ic_launcher_background">[^<]*</color>',
                     '<color name="ic_launcher_background">%s</color>' % hex_color, text)
    if updated == text and '<color name="ic_launcher_background">' not in text:
        raise SystemExit("colors.xml 里找不到 ic_launcher_background，拒绝生成不一致的图标")
    colors.write_text(updated, encoding="utf-8")
    written.append(str(colors.relative_to(ROOT)))

    art.resize((512, 512), Image.LANCZOS).save(ASSETS / "app-icon.png")
    written.append(str((ASSETS / "app-icon.png").relative_to(ROOT)))
    manifest = {"name": "轻塑记录", "short_name": "轻塑", "start_url": "/", "scope": "/",
                "display": "standalone", "background_color": "#f8fafc", "theme_color": hex_color,
                "icons": [{"src": "/app-icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                          {"src": "/app-icon.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    (ASSETS / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    written.append("app/src/main/assets/manifest.webmanifest")
    print(json.dumps({"source": os.path.basename(args.source), "artwork": art.size,
                      "background": hex_color, "removed_stale": removed, "written": written},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
