"""Inline the viewer template + app JS + sample map into one standalone HTML.

Usage:  python3 site/citymap/build.py [map_json] [out_html]
Defaults: map = data/citymap_visualization.json, out = site/citymap/viewer.html
The embedded map is only a default; users can still drag in any map / trace.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    map_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "citymap_visualization.json"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "viewer.html"

    template = (HERE / "index.html").read_text(encoding="utf-8")
    app_js = (HERE / "app.src.js").read_text(encoding="utf-8")
    phaser_js = (ROOT / "site" / "vendor" / "phaser.min.js").read_text(encoding="utf-8")

    if map_path.exists():
        # Compact the JSON to keep file size down; it is data, not source.
        embedded = json.dumps(json.loads(map_path.read_text(encoding="utf-8")),
                              ensure_ascii=False, separators=(",", ":"))
    else:
        embedded = ""
        print(f"[build] WARNING: {map_path} not found; viewer will start empty.")

    # Inline the vendored Phaser so viewer.html is fully self-contained
    # (double-clickable, no server / sibling files needed).
    html = template.replace('<script src="../vendor/phaser.min.js"></script>',
                            "<script>\n" + phaser_js + "\n</script>")
    html = html.replace("__APP_JS__", app_js)
    html = html.replace("__EMBEDDED_MAP__", embedded)

    out_path.write_text(html, encoding="utf-8")
    kb = out_path.stat().st_size / 1024
    print(f"[build] wrote {out_path.relative_to(ROOT)} ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
