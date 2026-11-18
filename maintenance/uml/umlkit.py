"""Tiny hand-rolled UML-to-SVG kit (no Graphviz/PlantUML on this machine)."""
from __future__ import annotations

from html import escape

CW = 6.65      # monospace advance at 11px (Consolas/Menlo)
NW = 7.7       # bold 13px sans, average
SW = 6.1       # italic 11px sans, average
LH = 15        # member line height
PAD = 10

CSS = """
.bg{fill:#ffffff}
.box{fill:#ffffff;stroke:#3b3b52;stroke-width:1.2}
.sep{stroke:#3b3b52;stroke-width:1}
.h-class{fill:#ecebfa}.h-module{fill:#e4f2e9}.h-ext{fill:#fcecd6}.h-art{fill:#e9eef5}
.h-exc{fill:#fbe3e3}.h-data{fill:#e3eefb}.h-prog{fill:#efe6f8}.h-pkg{fill:#f1f1f1}.h-wf{fill:#fff3c9}
.name{font:600 13px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#1d1d2c}
.stereo{font:italic 11px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#55556b}
.mem{font:11px Consolas,Menlo,'DejaVu Sans Mono',monospace;fill:#25253a}
.cap{font:italic 10px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#6b6b80}
.edge{fill:none;stroke:#4a4a64;stroke-width:1.25}
.dash{stroke-dasharray:6 4}
.ah-fill{fill:#4a4a64;stroke:#4a4a64}
.ah-open{fill:none;stroke:#4a4a64;stroke-width:1.25}
.ah-hollow{fill:#ffffff;stroke:#4a4a64;stroke-width:1.25}
.lbl{font:11px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#34344c;paint-order:stroke;stroke:#ffffff;stroke-width:4px;stroke-linejoin:round}
.frame{fill:#fafafc;stroke:#8f8fa6;stroke-width:1}
.ftab{fill:#ececf3;stroke:#8f8fa6;stroke-width:1}
.ftitle{font:600 12px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#3c3c54}
.title{font:600 19px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#1d1d2c}
.sub{font:12px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#62627a}
.note{fill:#fff9df;stroke:#b5a35a;stroke-width:1}
.notetxt{font:11px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#4a4326}
.life{stroke:#8f8fa6;stroke-width:1;stroke-dasharray:5 4}
.act{fill:#ecebfa;stroke:#3b3b52;stroke-width:1}
.frag{fill:none;stroke:#6b6b84;stroke-width:1}
.fragtab{fill:#ececf3;stroke:#6b6b84;stroke-width:1}
.fragtxt{font:600 11px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#3c3c54}
.guard{font:italic 11px 'Segoe UI',Helvetica,Arial,sans-serif;fill:#3c3c54}
.actor{fill:none;stroke:#3b3b52;stroke-width:1.4}
@media (prefers-color-scheme: dark){
.bg{fill:#17171f}
.box{fill:#20202b;stroke:#b9b9cf}.sep{stroke:#b9b9cf}
.h-class{fill:#33305a}.h-module{fill:#22402f}.h-ext{fill:#4a3618}.h-art{fill:#26364a}
.h-exc{fill:#4d2626}.h-data{fill:#203a57}.h-prog{fill:#3b2a52}.h-pkg{fill:#2c2c38}.h-wf{fill:#4a4019}
.name{fill:#ececf6}.stereo{fill:#b4b4c8}.mem{fill:#dcdcea}.cap{fill:#a4a4ba}
.edge{stroke:#b4b4cc}.ah-fill{fill:#b4b4cc;stroke:#b4b4cc}.ah-open{stroke:#b4b4cc}
.ah-hollow{fill:#17171f;stroke:#b4b4cc}
.lbl{fill:#d8d8e8;stroke:#17171f}
.frame{fill:#1c1c26;stroke:#5e5e78}.ftab{fill:#2a2a38;stroke:#5e5e78}.ftitle{fill:#cfcfe2}
.title{fill:#f0f0f8}.sub{fill:#a4a4ba}
.note{fill:#3a3520;stroke:#8a7b3c}.notetxt{fill:#eadfb0}
.life{stroke:#5e5e78}.act{fill:#33305a;stroke:#b9b9cf}
.frag{stroke:#8a8aa6}.fragtab{fill:#2a2a38;stroke:#8a8aa6}.fragtxt,.guard{fill:#cfcfe2}
.actor{stroke:#d0d0e2}
}
"""

DEFS = """
<defs>
 <marker id="open" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
  <path class="ah-open" d="M1,1 L11,6 L1,11"/></marker>
 <marker id="fill" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="11" markerHeight="11" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
  <path class="ah-fill" d="M1,1.5 L11,6 L1,10.5 z"/></marker>
 <marker id="tri" viewBox="0 0 16 16" refX="15" refY="8" markerWidth="16" markerHeight="16" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
  <path class="ah-hollow" d="M1,1 L15,8 L1,15 z"/></marker>
 <marker id="diamond" viewBox="0 0 20 12" refX="1" refY="6" markerWidth="20" markerHeight="12" orient="auto" markerUnits="userSpaceOnUse">
  <path class="ah-fill" d="M1,6 L10,1 L19,6 L10,11 z"/></marker>
</defs>
"""


def t(x, y, s, cls, anchor="start"):
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{escape(s)}</text>'


class Box:
    """UML classifier: header (stereotype + name) and any number of compartments.

    comps: list of (caption | None, [lines]).  caption renders as a small italic
    heading inside the compartment (UML named compartment).
    """

    def __init__(self, name, stereo=None, comps=(), kind="class", minw=0, w=None, icon=None):
        self.name, self.stereo, self.comps, self.kind, self.icon = name, stereo, list(comps), kind, icon
        widths = [len(name) * NW + 2 * PAD + (22 if icon else 0)]
        if stereo:
            widths.append(len(stereo) * SW + 2 * PAD + (22 if icon else 0))
        for cap, lines in self.comps:
            widths += [len(l) * CW + 2 * PAD for l in lines]
            if cap:
                widths.append(len(cap) * 5.6 + 2 * PAD)
        self.w = w or max(max(widths), minw)
        self.hh = 38 if stereo else 26
        self.h = self.hh + sum(self._ch(c) for c in self.comps)
        self.x = self.y = 0

    @staticmethod
    def _ch(comp):
        cap, lines = comp
        return (14 if cap else 0) + max(len(lines), 0) * LH + (10 if lines or cap else 8)

    def at(self, x, y):
        self.x, self.y = x, y
        return self

    # anchors ----------------------------------------------------------------
    def t(self, f=.5): return (self.x + self.w * f, self.y)
    def b(self, f=.5): return (self.x + self.w * f, self.y + self.h)
    def l(self, f=.5): return (self.x, self.y + self.h * f)
    def r(self, f=.5): return (self.x + self.w, self.y + self.h * f)
    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2
    @property
    def right(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h

    def svg(self):
        x, y, w = self.x, self.y, self.w
        out = [f'<g><rect class="box" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{self.h:.1f}" rx="2"/>',
               f'<rect class="h-{self.kind}" x="{x + .6:.1f}" y="{y + .6:.1f}" width="{w - 1.2:.1f}" height="{self.hh - .6:.1f}"/>']
        cx = x + w / 2
        if self.stereo:
            out.append(t(cx, y + 15, self.stereo, "stereo", "middle"))
            out.append(t(cx, y + 31, self.name, "name", "middle"))
        else:
            out.append(t(cx, y + 18, self.name, "name", "middle"))
        if self.icon == "component":
            ix, iy = x + w - 22, y + 7
            out.append(f'<rect class="box" x="{ix + 3}" y="{iy}" width="13" height="16"/>'
                       f'<rect class="box" x="{ix}" y="{iy + 3}" width="7" height="3.5"/>'
                       f'<rect class="box" x="{ix}" y="{iy + 9}" width="7" height="3.5"/>')
        elif self.icon == "artifact":
            ix, iy = x + w - 20, y + 6
            out.append(f'<path class="box" d="M{ix},{iy} h9 l5,5 v13 h-14 z M{ix + 9},{iy} v5 h5"/>')
        cy = y + self.hh
        for comp in self.comps:
            cap, lines = comp
            out.append(f'<line class="sep" x1="{x:.1f}" y1="{cy:.1f}" x2="{x + w:.1f}" y2="{cy:.1f}"/>')
            yy = cy + 5
            if cap:
                out.append(t(x + PAD, yy + 10, cap, "cap"))
                yy += 14
            for ln in lines:
                out.append(t(x + PAD, yy + 11.5, ln, "mem"))
                yy += LH
            cy += self._ch(comp)
        out.append("</g>")
        return "\n".join(out)


class Diagram:
    def __init__(self, w, h, title, subtitle=""):
        self.w, self.h, self.title, self.subtitle = w, h, title, subtitle
        self.frames, self.edges, self.boxes, self.top = [], [], [], []

    def add(self, *boxes):
        self.boxes += boxes
        return boxes[0] if len(boxes) == 1 else boxes

    def frame(self, x, y, w, h, title, kind="package"):
        tw = len(title) * 7 + 20
        if kind == "package":
            self.frames.append(
                f'<rect class="ftab" x="{x}" y="{y - 20}" width="{tw}" height="20"/>'
                f'<rect class="frame" x="{x}" y="{y}" width="{w}" height="{h}"/>'
                + t(x + 10, y - 6, title, "ftitle"))
        else:
            self.frames.append(f'<rect class="frame" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>'
                               + t(x + 12, y + 18, title, "ftitle"))

    def edge(self, pts, kind="dep", label=None, lpos=None, anchor="middle", lines=None):
        """kind: dep (dashed, open head) | use | flow (solid, filled) | assoc (solid, open)
        | inherit (solid, hollow triangle) | comp (diamond at first point) | ret (dashed, open)
        | line (plain solid) | bidep (dashed, open heads both ends)"""
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        cls, attrs = "edge", ""
        if kind in ("dep", "use", "ret"):
            cls += " dash"; attrs = 'marker-end="url(#open)"'
        elif kind == "bidep":
            cls += " dash"; attrs = 'marker-end="url(#open)" marker-start="url(#open)"'
        elif kind == "flow":
            attrs = 'marker-end="url(#fill)"'
        elif kind == "assoc":
            attrs = 'marker-end="url(#open)"'
        elif kind == "inherit":
            attrs = 'marker-end="url(#tri)"'
        elif kind == "comp":
            attrs = 'marker-start="url(#diamond)"'
        elif kind == "dashline":
            cls += " dash"
        self.edges.append(f'<path class="{cls}" d="{d}" {attrs}/>')
        if label:
            if lpos is None:
                (x1, y1), (x2, y2) = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
                lpos = ((x1 + x2) / 2, (y1 + y2) / 2 - 5)
            self.label(lpos, label, anchor)

    def label(self, pos, text, anchor="middle"):
        x, y = pos
        for i, ln in enumerate(text.split("\n")):
            self.top.append(t(x, y + i * 13, ln, "lbl", anchor))

    def note(self, x, y, lines, w=None):
        w = w or max(len(l) for l in lines) * 6.0 + 24
        h = len(lines) * 14 + 14
        self.top.append(
            f'<path class="note" d="M{x},{y} h{w - 10} l10,10 v{h - 10} h{-w} z"/>'
            f'<path class="note" d="M{x + w - 10},{y} v10 h10"/>'
            + "".join(t(x + 10, y + 18 + i * 14, l, "notetxt") for i, l in enumerate(lines)))
        return (x, y, w, h)

    def actor(self, cx, y, name):
        self.boxes.append(type("A", (), {"svg": lambda s: (
            f'<g class="actor"><circle cx="{cx}" cy="{y + 8}" r="8"/>'
            f'<path d="M{cx},{y + 16} v20 M{cx - 13},{y + 23} h26 M{cx},{y + 36} l-11,15 M{cx},{y + 36} l11,15"/></g>'
            + t(cx, y + 66, name, "name", "middle"))})())

    def raw(self, s, layer="top"):
        getattr(self, layer).append(s)

    def svg(self):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">\n'
                f'<title>{escape(self.title)}</title>\n<style>{CSS}</style>{DEFS}'
                f'<rect class="bg" width="100%" height="100%"/>\n'
                + t(30, 36, self.title, "title") + (t(30, 56, self.subtitle, "sub") if self.subtitle else ""))
        body = self.frames + self.edges + [b.svg() for b in self.boxes] + self.top
        return head + "\n" + "\n".join(body) + "\n</svg>\n"
