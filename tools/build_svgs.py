#!/usr/bin/env python3
"""Generate every image in assets/ for the profile README.

All text in the SVGs is converted to <path> outlines with fontTools and
shaped with HarfBuzz (so kerning is correct). The finished SVGs contain no
<text>, no webfonts and no external references.

Usage:  python3 tools/build_svgs.py
See tools/README.md for dependencies.
"""
import io
import os
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "tools" / "fonts"
SRC = ROOT / "tools" / "source"
OUT = ROOT / "assets"

# ---------------------------------------------------------------- palette
THEMES = {
    "dark": dict(bg="#111214", surface="#17191C", line="#26292E", text="#ECE7DF",
                 muted="#8C877F", accent="#D98A4E", tint=0.18),
    "light": dict(bg="#F5F1EA", surface="#FFFFFF", line="#E3DDD2", text="#1A1A1C",
                  muted="#6A655D", accent="#A8551F", tint=0.14),
}


# ------------------------------------------------------------------ fonts
class Face:
    """A static instance of a variable font, shaped with HarfBuzz."""

    def __init__(self, path, wght):
        tt = TTFont(path)
        tt = instancer.instantiateVariableFont(
            tt, {"wght": wght}, inplace=False,
            overlap=instancer.OverlapMode.REMOVE)  # no inner outlines when stroked
        buf = io.BytesIO()
        tt.save(buf)
        data = buf.getvalue()
        self.tt = TTFont(io.BytesIO(data))
        self.gs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.upem = self.tt["head"].unitsPerEm
        self.cap = self.tt["OS/2"].sCapHeight / self.upem
        self.hbfont = hb.Font(hb.Face(data))

    def shape(self, text, tracking=0.0, kern=True):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": kern, "liga": False})
        out, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset))
            x += pos.x_advance + tracking * self.upem
        return out, x

    def width(self, text, size, tracking=0.0):
        return self.shape(text, tracking)[1] * size / self.upem

    def path(self, text, size, x, y, tracking=0.0, anchor="start", kern=True):
        """Return (svg path data, advance width in px). Baseline at y."""
        glyphs, adv = self.shape(text, tracking, kern)
        s = size / self.upem
        w = adv * s
        if anchor == "end":
            x -= w
        elif anchor == "middle":
            x -= w / 2
        pen = SVGPathPen(self.gs, ntos=lambda v: ("%.1f" % v).rstrip("0").rstrip("."))
        for name, gx in glyphs:
            tp = TransformPen(pen, (s, 0, 0, -s, x + gx * s, y))
            self.gs[name].draw(tp)
        return pen.getCommands(), w


ALEX = {}
JBM = {}


def alex(w):
    if w not in ALEX:
        ALEX[w] = Face(FONTS / "Alexandria.ttf", w)
    return ALEX[w]


def mono(w=500):
    if w not in JBM:
        JBM[w] = Face(FONTS / "JetBrainsMono.ttf", w)
    return JBM[w]


# ---------------------------------------------------------------- helpers
def fmt(n):
    return ("%.2f" % n).rstrip("0").rstrip(".")


class Svg:
    def __init__(self, w, h, t, name):
        self.w, self.h, self.t, self.name = w, h, t, name
        self.defs, self.body = [], []

    def add(self, s):
        self.body.append(s)

    def text(self, face, s, size, x, y, fill=None, tracking=0.0, anchor="start", stroke=None, sw=0, kern=True):
        d, w = face.path(s, size, x, y, tracking, anchor, kern)
        if stroke:
            self.add(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}" '
                     f'stroke-linejoin="miter" stroke-miterlimit="3"/>')
        else:
            self.add(f'<path d="{d}" fill="{fill}"/>')
        return w

    def rect(self, x, y, w, h, fill="none", stroke=None, sw=1, extra=""):
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{fill}"{st}{extra}/>')

    def line(self, x1, y1, x2, y2, stroke, sw=1):
        self.add(f'<path d="M{fmt(x1)} {fmt(y1)}L{fmt(x2)} {fmt(y2)}" stroke="{stroke}" stroke-width="{sw}" fill="none"/>')

    def stripes(self, pid):
        c = THEMES[self.t]
        self.defs.append(
            f'<pattern id="{pid}" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="6" height="14" fill="{c["accent"]}" fill-opacity="{c["tint"]}"/></pattern>')

    def dots(self, pid, step=24):
        c = THEMES[self.t]
        self.defs.append(
            f'<pattern id="{pid}" width="{step}" height="{step}" patternUnits="userSpaceOnUse">'
            f'<circle cx="{step/2}" cy="{step/2}" r="1" fill="{c["line"]}"/></pattern>')

    def crop_marks(self, x0, y0, x1, y1, n, stroke, sw=1.5):
        for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            self.add(f'<path d="M{fmt(x + dx * n)} {fmt(y)}L{fmt(x)} {fmt(y)}L{fmt(x)} {fmt(y + dy * n)}" '
                     f'fill="none" stroke="{stroke}" stroke-width="{sw}"/>')

    def render(self):
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(self.w)} {fmt(self.h)}" '
                f'width="100%" role="img">{defs}{"".join(self.body)}</svg>\n')

    def save(self):
        p = OUT / f"{self.name}-{self.t}.svg"
        p.write_text(self.render(), encoding="utf-8")
        return p


# ------------------------------------------------------------------- hero
def hero(t):
    c = THEMES[t]
    W, H, M = 1280, 440, 72
    s = Svg(W, H, t, "hero")
    s.dots("dots")
    s.stripes("st")
    s.rect(0, 0, W, H, c["bg"])
    s.rect(0, 0, W, H, "url(#dots)")
    s.crop_marks(24, 24, W - 24, H - 24, 18, c["muted"])

    A800, A500, M500 = alex(800), alex(500), mono(500)
    s.text(M500, "// MANAMA, BAHRAIN", 16, M, 62, c["accent"], tracking=0.08)

    size = 144
    cap = A800.cap * size
    b1, b2 = 198, 198 + 120
    s.text(A800, "ABDULLA", size, M, b1, stroke=c["text"], sw=2.5, tracking=0.035, kern=False)
    w2 = s.text(A800, "AHMED", size, M, b2, stroke=c["text"], sw=2.5, tracking=0.035, kern=False)
    # blinking cursor, the only moving element
    cx = M + w2 + 26
    s.add(f'<rect x="{fmt(cx)}" y="{fmt(b2 - cap)}" width="34" height="{fmt(cap)}" fill="{c["accent"]}">'
          f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1.1s" repeatCount="indefinite"/></rect>')

    s.text(A500, "Full-stack developer and UI/UX designer", 30, M, 372, c["text"])
    s.line(M, 390.5, 900, 390.5, c["line"])
    s.text(M500, "NOW: CLOUD INNOVATION CENTER INTERN, AWS", 13, M, 416, c["muted"], tracking=0.06)

    # stripe panel (right), framed
    px, py, pw, ph = 984, 68, 224, 304
    s.rect(px, py, pw, ph, c["surface"])
    s.rect(px, py, pw, ph, "url(#st)")
    s.rect(px + .5, py + .5, pw - 1, ph - 1, "none", c["line"])
    s.crop_marks(px - 12, py - 12, px + pw + 12, py + ph + 12, 12, c["accent"], 1.5)
    s.text(M500, "26.22 N / 50.59 E", 13, px + pw, py + ph + 44, c["muted"], tracking=0.06, anchor="end")
    return s.save()


# --------------------------------------------------------------- sections
def section(idx, title, t):
    c = THEMES[t]
    s = Svg(840, 56, t, f"section-{idx}")
    M500, A700 = mono(500), alex(700)
    w1 = s.text(M500, idx, 15, 0, 34, c["accent"], tracking=0.08)
    w2 = s.text(M500, "/", 15, w1 + 12, 34, c["muted"])
    x = w1 + 12 + w2 + 14
    wt = s.text(A700, title.upper(), 22, x, 36, c["text"], tracking=0.06)
    s.line(x + wt + 20, 28.5, 840, 28.5, c["line"])
    s.add(f'<rect x="838" y="25" width="2" height="7" fill="{c["accent"]}"/>')
    return s.save()


# ------------------------------------------------------------------ cards
def card(name, title, meta, chips, t, tag=None):
    c = THEMES[t]
    W, H, PW = 840, 156, 72
    s = Svg(W, H, t, f"card-{name}")
    s.stripes("st")
    s.rect(.5, .5, W - 1, H - 1, c["surface"], c["line"])
    s.rect(.5, .5, PW, H - 1, "url(#st)")
    s.line(PW + .5, 0, PW + .5, H, c["line"])
    M500, A700 = mono(500), alex(700)
    x0 = PW + 40
    s.text(M500, meta, 13, x0, 44, c["accent"], tracking=0.08)
    if tag:
        tw = M500.width(tag, 12, 0.08)
        s.text(M500, tag, 12, W - 32, 44, c["muted"], tracking=0.08, anchor="end")
        s.add(f'<circle cx="{fmt(W - 32 - tw - 14)}" cy="39.5" r="3.5" fill="{c["accent"]}"/>')
    s.text(A700, title, 34, x0, 92, c["text"], tracking=-0.005)
    x = x0
    for ch in chips:
        cw = M500.width(ch, 12) + 24
        s.rect(x + .5, 108.5, cw, 26, "none", c["line"])
        s.text(M500, ch, 12, x + 12, 126, c["muted"])
        x += cw + 8
    return s.save()


# ------------------------------------------------------------------ stack
STACK = [
    ("LANGUAGES", ["Go", "JavaScript", "Python", "C#", "Java", "Swift", "SQL"]),
    ("FRAMEWORKS", ["React", "FastAPI", "ASP.NET Core", "EF Core", "Tailwind CSS"]),
    ("CLOUD AND DATA", ["AWS CDK", "Lambda", "API Gateway", "DynamoDB", "S3", "Cognito",
                        "Azure", "PostgreSQL", "SQL Server", "MySQL", "SQLite"]),
    ("TOOLING", ["Git", "GitHub Actions", "Docker", "Linux", "Postman", "Vitest", "OpenAI API", "n8n"]),
    ("DESIGN", ["Figma", "Photoshop", "Illustrator", "Design systems"]),
]


def stack(t):
    c = THEMES[t]
    W, LX, RX, LH = 840, 0, 230, 26
    M500 = mono(500)
    size, gap = 15, 26
    # layout first to know the height
    rows, y = [], 0
    for label, items in STACK:
        lines, cur, x = [[]], [], 0
        for it in items:
            w = M500.width(it, size)
            if x and x + w > W - RX:
                lines.append([])
                x = 0
            lines[-1].append((it, x, w))
            x += w + gap
        rows.append((label, lines, y))
        y += 28 + len(lines) * LH + 18
    H = y
    s = Svg(W, H, t, "stack")
    for label, lines, y0 in rows:
        s.line(0, y0 + .5, W, y0 + .5, c["line"])
        s.text(M500, label, 13, LX, y0 + 38, c["accent"], tracking=0.08)
        for li, ln in enumerate(lines):
            by = y0 + 38 + li * LH
            for k, (it, x, w) in enumerate(ln):
                s.text(M500, it, size, RX + x, by, c["text"])
                if k < len(ln) - 1:
                    s.rect(RX + x + w + gap / 2 - 1.5, by - 6, 3, 3, c["muted"])
    s.line(0, H - .5, W, H - .5, c["line"])
    return s.save(), [it for _, its in STACK for it in its]


# ----------------------------------------------------------------- footer
def footer(t):
    c = THEMES[t]
    s = Svg(840, 64, t, "footer")
    M500 = mono(500)
    s.line(0, 16.5, 840, 16.5, c["line"])
    x = 0
    x += s.text(M500, "abdulla@github:~", 16, x, 46, c["muted"])
    x += s.text(M500, "$", 16, x + 1, 46, c["accent"])
    s.text(M500, "exit", 16, x + 12, 46, c["text"])
    s.text(M500, "EOF", 12, 840, 46, c["muted"], tracking=0.08, anchor="end")
    return s.save()


# ------------------------------------------------------------- PNG panels
def hex2rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def marks(d, box, c, n=22, w=3):
    x0, y0, x1, y1 = box
    for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(x + dx * n, y), (x, y), (x, y + dy * n)], fill=c, width=w, joint="curve")


def paste_framed(img, d, im, x, y, w, c):
    h = round(im.height * w / im.width)
    im = im.convert("RGB").resize((w, h), Image.LANCZOS)
    img.paste(im, (x, y))
    d.rectangle([x - 1, y - 1, x + w, y + h], outline=hex2rgb(c["line"]), width=1)
    return h


def showroom_png(t):
    c = THEMES[t]
    W, M = 1360, 60
    shot = Image.open(SRC / "showroom-home-light.png").convert("RGB").crop((0, 0, 1372, 800))  # no scrollbar
    inner = W - 2 * M
    h = round(shot.height * inner / shot.width)
    H = h + 2 * M
    img = Image.new("RGB", (W, H), hex2rgb(c["bg"]))
    d = ImageDraw.Draw(img)
    paste_framed(img, d, shot, M, M, inner, c)
    marks(d, (M - 22, M - 22, M + inner + 22, M + h + 22), hex2rgb(c["accent"]))
    return save_png(img, OUT / f"shot-showroom-{t}.png", c)


def guidely_png(t):
    c = THEMES[t]
    W, M, GAP = 1680, 80, 40
    home = Image.open(SRC / "guidely-home.png").convert("RGB").crop((371, 0, 2860, 1556))  # stops above the live stats line
    ans = Image.open(SRC / "guidely-answer.png").convert("RGB").crop((450, 265, 2780, 1562))
    a1, a2 = home.width / home.height, ans.width / ans.height
    inner = W - 2 * M - GAP
    H = round(inner / (a1 + a2))
    w1 = round(H * a1)
    w2 = inner - w1
    img = Image.new("RGB", (W, H + 2 * M), hex2rgb(c["bg"]))
    d = ImageDraw.Draw(img)
    paste_framed(img, d, home, M, M, w1, c)
    paste_framed(img, d, ans, M + w1 + GAP, M, w2, c)
    marks(d, (M - 24, M - 24, W - M + 24, M + H + 24), hex2rgb(c["accent"]))
    return save_png(img, OUT / f"shot-guidely-{t}.png", c)


def design_png(t):
    c = THEMES[t]
    W, M, GAP = 1680, 80, 40
    img_dub = Image.open(SRC / "design-dubrah.png").crop((25, 25, 972, 675))
    forum = Image.open(SRC / "design-real-time-forum.png")
    f15 = forum.crop((445, 49, 808, 426))
    f16 = forum.crop((432, 482, 795, 858))
    mgzn = Image.open(OUT / "design-mgzn.png")
    m_agenda = mgzn.crop((275, 322, 625, 552))
    m_speak = mgzn.crop((265, 56, 615, 286))
    # pick the right-column width so both columns end on the same line
    best = None
    for wf in range(380, 600):
        lw = W - 2 * M - GAP - wf
        total_r = 2 * round(377 * wf / 363) + GAP
        mw = (lw - GAP) // 2
        total_l = round(650 * lw / 947) + GAP + round(230 * mw / 350)
        if best is None or abs(total_l - total_r) < best[0]:
            best = (abs(total_l - total_r), wf)
    wf = best[1]
    lw = W - 2 * M - GAP - wf
    mw = (lw - GAP) // 2
    img = Image.new("RGB", (W, 1600), hex2rgb(c["bg"]))
    d = ImageDraw.Draw(img)
    dh = paste_framed(img, d, img_dub, M, M, lw, c)
    y2 = M + dh + GAP
    h1 = paste_framed(img, d, m_agenda, M, y2, mw, c)
    paste_framed(img, d, m_speak, M + mw + GAP, y2, mw, c)
    rx = W - M - wf
    a = paste_framed(img, d, f15, rx, M, wf, c)
    b = paste_framed(img, d, f16, rx, M + a + GAP, wf, c)
    bottom = max(y2 + h1, M + a + GAP + b)
    marks(d, (M - 24, M - 24, W - M + 24, bottom + 24), hex2rgb(c["accent"]))
    img = img.crop((0, 0, W, bottom + M))
    return save_png(img, OUT / f"design-showcase-{t}.png", c)


def save_png(img, path, c, colors=232):
    """Palette PNG. The theme colours are pinned into the palette so the
    accent crop marks and background survive quantisation."""
    pinned = [hex2rgb(c[k]) for k in ("bg", "line", "accent", "text", "muted")]
    for n in (colors, 160, 112, 80):
        ref = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pal = ref.getpalette()[: n * 3]
        pal += [v for rgb in pinned for v in rgb]
        pal += [0] * (768 - len(pal))
        ref.putpalette(pal)
        q = img.quantize(palette=ref, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
        if path.stat().st_size < 300 * 1024:
            break
    return path


# ------------------------------------------------------------------- main
def main():
    OUT.mkdir(exist_ok=True)
    made = []
    for t in THEMES:
        made.append(hero(t))
        for idx, title in (("01", "Now"), ("02", "Selected work"), ("03", "UI/UX design"), ("04", "Stack")):
            made.append(section(idx, title, t))
        made.append(card("aws", "AMAN Investigation Copilot", "AWS CIC  ·  SEP 2026 TO PRESENT  ·  TEAM OF 5",
                         ["CDK", "Lambda", "API Gateway", "DynamoDB", "S3", "Cognito"], t, tag="CURRENT"))
        made.append(card("showroom", "Reboot01 Student Showroom", "REBOOT01  ·  TEAM OF FOUR",
                         ["React", "Gitea sign-in", "CI/CD", "Auto-rollback"], t, tag="LIVE"))
        made.append(card("guidely", "Guidely", "REBOOT01  ·  SOLO PROJECT",
                         ["RAG", "Cited answers", "Retrieval eval"], t))
        made.append(card("taalam", "Taalam", "FEB TO JUN 2026  ·  TEAM PROJECT",
                         ["ASP.NET Core 9", "JWT", "Role-based access", "Azure"], t))
        made.append(stack(t)[0])
        made.append(footer(t))
        made.append(showroom_png(t))
        made.append(guidely_png(t))
    # design showcase needs the mgzn source in assets/, so it runs last
    for t in THEMES:
        made.append(design_png(t))
    for p in made:
        print("wrote", p.relative_to(ROOT), f"{p.stat().st_size/1024:.1f} KB")


if __name__ == "__main__":
    sys.exit(main())
