"""Download mxsimracing.com favicon and write build_cache/app.ico for PyInstaller / Inno Setup."""
from __future__ import annotations

import io
import json
import os
import sys

BRANDING_HOME_URL = "https://mxsimracing.com/"


def _urljoin(base: str, href: str) -> str:
    from urllib.parse import urljoin

    if not href:
        return base
    return urljoin(base, href.split("#")[0])


def parse_mxsim_branding_urls(html: str, base: str = BRANDING_HOME_URL) -> tuple[str, str]:
    fav_url = None
    header_url = None
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("link"):
            rel = tag.get("rel")
            if not rel:
                continue
            rel_list = rel if isinstance(rel, (list, tuple)) else [rel]
            rel_join = " ".join(str(r).lower() for r in rel_list)
            if "icon" in rel_join and tag.get("href"):
                fav_url = _urljoin(base, str(tag.get("href")))
                break
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            header_url = str(og.get("content")).strip()
    except Exception:
        pass
    if not fav_url:
        fav_url = _urljoin(base, "/favicon.png")
    if not header_url:
        header_url = fav_url
    return fav_url, header_url


def _write_placeholder_ico(path: str) -> None:
    from PIL import Image

    im = Image.new("RGBA", (64, 64), (45, 48, 58, 255))
    im.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])


def _repo_root() -> str:
    """Project root (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    root = _repo_root()
    out_dir = os.path.join(root, "build_cache")
    os.makedirs(out_dir, exist_ok=True)
    out_ico = os.path.join(out_dir, "app.ico")
    try:
        import requests
        from PIL import Image
    except ImportError as e:
        print("Missing dependency:", e, file=sys.stderr)
        return 1
    try:
        r = requests.get(
            BRANDING_HOME_URL,
            headers={"User-Agent": "Mozilla/5.0 (MxSim OBS Overlay build)"},
            timeout=25,
        )
        r.raise_for_status()
        fav_u, _head_u = parse_mxsim_branding_urls(r.text, BRANDING_HOME_URL)
        ir = requests.get(fav_u, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        ir.raise_for_status()
        im = Image.open(io.BytesIO(ir.content)).convert("RGBA")
        im.save(
            out_ico,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        meta = {"favicon_url": fav_u, "ico": os.path.relpath(out_ico, root)}
        with open(os.path.join(out_dir, "build_branding.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("Wrote", out_ico)
        return 0
    except Exception as e:
        print("Branding fetch failed:", e, file=sys.stderr)
        try:
            _write_placeholder_ico(out_ico)
            print("Wrote placeholder", out_ico, file=sys.stderr)
            return 0
        except Exception as e2:
            print("Placeholder failed:", e2, file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
