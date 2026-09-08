"""The IBM VGA 8x16 font, and the map from a screen cell back to it.

A Turbo Vision screen is drawn out of exactly one repertoire: code page 437.
Booting `demo`, `entries` and `ascii` and collecting every glyph that reached
the terminal returns the 256 characters of it and nothing else -- box drawing,
the three shades, the arrows, the card suits. So a screenshot needs no font
metrics, no fallback chain and no missing-glyph box: one 4 KB table of 8x16
bitmaps covers everything that can appear, and the glyphs tile the way the
originals did, because they are the originals.

The bitmaps are the IBM VGA ROM font, extracted from a card's ROM by
spacerace/romfont. A bitmap typeface is not a copyrightable work in the US and
these have been redistributed freely for forty years; if that is not good
enough, Terminus (SIL OFL) is the drop-in replacement, minus the smileys.

Stored zlib'd and base85'd rather than as a binary blob so that the tree stays
text -- 1.7 KB of it, decoded once on import.
"""

import base64
import zlib

# 256 glyphs of 16 rows, one byte per row, the high bit the leftmost pixel.
GLYPHS = zlib.decompress(base64.b85decode(
    "c-nneKWigL6ki<JYSB5}5DUAx;>slfdkKpKN4`RuRLfo1TrmVyiXhA0x$$>!lP*oZgF(n)Nw"
    "K&T3sQtDsX2@w;8S5{^WOY@Gw0;VM*8i%nfL$A+b9aDzWn|2^5**Tvevj?_5JOx?`y-s1yGe"
    "88+@Eq6tX<u?RJdi7T2)ZVa3AKuU^vb76l;5hk5z>b(y>M+v}T~>s!5kI{51ASqn6aG&4}nK"
    "!C#IZ^kLmWPh*l`?v4k0{yhx&b4s1%6Iun^M9D%?+@azzn_1Q_$VHnj>PD65Fc6f8Dq6kI4T"
    "vvw?2QhTK#&0Bw^JQ8E+b%B~3-ViY^Pzt0_h@>Pd0};ZY(IMh;60QKU3x^Z8s5_=*eu%E99-"
    "t12OgE>)Gecm)Kp$x#`t519JWXW($U{8!pm&0=1~@l{h93l>en(xSOiDC0bvt|4AirF)td-f"
    "_Syi6z=NmPlgG!ZPpklB(#UO`eerk$A=~yW=QE{dBw|jMj3A5z~CxOh+Kn0afgcusF`+I5y!"
    ";hB<EqD153#LolAmdR72#fHW4cU)gNVgC(+#ziZf^%skDB!5SNLrF!7C*p;ySGbGoL$DW^%_"
    "{s;H&1OBXOtyeS1S+KP6J$Vz8UJMJZ2=a}7rH>B16KvX58A%+&AZvV;!P<$Toik<f73MOw+f"
    ">qDNf7Fbpe=uaVoRH)%zAi&1N8UtMI;%WaTvvLM+L7&Gu1j?i`lBCjOT86;40BzT8yFz^<c>"
    "Tf1IlNo@Dm^$(uDO>n+O+!UNVe7O`4++YsXSaGADYG>{|(OhBh7AF7lRFmna(7`6z(Dti5(U"
    "hBLM*l@UmLvQ8`7Ehyy+-#%F_R&7?W}4b0gQb^ki=WZFV}@z&-jnUp7<ANitKHb$dJPMd|Ep"
    "HLSAOnpK%-wVo9Y;Ip9|bp!u^PUw}ReaPZREz1A(;=||#Y*DI@{(a)6hdRlt=V~@A({WwjZF"
    "dXMYyDqmAf0Qbw7OMo{4)ZLdaZ(vm$B8Ma7W=7={{T##puGckUqs~oz%}Gy6K%{o46m$kbDX"
    "YcDCZ=W7PY?q*oSF6VY8nft)DN@Z9JSoU-kG=B7_jcnFRIorSbCz&-2#H$jc7~Hv`4UPjTZK"
    "no);hY>T2SAoiuZGur8S-E}`JFoNV3=#RU|=}YU|&nKm?!|AN`{E6#cel#TBGlZ4bKbpwzCt"
    "w#QBen>?ytYp!*>D)DO+Fmj_V8!B0eLFF1}98jpFrJ2JAlRq<L&tu)~P*+J^dlSNPPja4Oa!"
    "5^AWv`a2$x}WCZtMiq|V0m+%gq)9DGz-;6qo2Fqa$U2)`adH35$v8Zaub5d{TyyNHOI6%BpK"
    "fnCW|9t<4|M~kD|HGcALx3zkSM;dAjTXYgA^&4+`9sp~@Yf$>o4fjnAY+l#CujkOK>st3pRq"
    "o?DMEhc&8$%$?hm-n0)Je1`d_4DPue*3*FQylaBqDI_Fs7Z=^ek`Z~3)#ec-R~{64fV2*cR3"
    "_sscE(%EPJ83+4&Umq6wH;k7(uMa4quTenzfL;XTZ!`Dty6d{Nu4jC=>RKq@*32Jx+tY%?@g"
    "K>+26~#ipKv7VkS5;s2OV~9#d*G|S+3sTA~%o=H;>E93dKF>c@W0gk-SiyJa`3jE#`|D@ISQ"
    "?H%tp`??pO{f&q}cEC~9_pkFVHll1s(o0uNA4IZ4FJkt=U{cu=K=XY$9_Ewht@PA%b%mee|g"
    "`Dj^a-I)$FC(GA>%U8jzx?#66g@iv{tGQ|+vN"))

WIDTH, HEIGHT = 8, 16

# The thirty-three CP437 characters Python's own codec will not encode, because
# it maps 0x00-0x1F and 0x7F to the C0 controls they also are. On a screen they
# are never controls -- 0x10 and 0x11 are the arrows on every scroll bar in the
# program -- so the graphic reading is the one a screenshot wants.
LOW = {
    "☺": 0x01, "☻": 0x02, "♥": 0x03, "♦": 0x04,
    "♣": 0x05, "♠": 0x06, "•": 0x07, "◘": 0x08,
    "○": 0x09, "◙": 0x0A, "♂": 0x0B, "♀": 0x0C,
    "♪": 0x0D, "♫": 0x0E, "☼": 0x0F, "►": 0x10,
    "◄": 0x11, "↕": 0x12, "‼": 0x13, "¶": 0x14,
    "§": 0x15, "▬": 0x16, "↨": 0x17, "↑": 0x18,
    "↓": 0x19, "→": 0x1A, "←": 0x1B, "∟": 0x1C,
    "↔": 0x1D, "▲": 0x1E, "▼": 0x1F, "⌂": 0x7F,
}


# Characters a program can put on the screen that CP437 has no code for, and
# the code that draws the same thing. Turbo Vision passes these through to a
# terminal that can show them; the font here has 256 glyphs and no such option,
# so the small triangles become the large ones and a truncation mark becomes a
# full stop. Nothing else is close enough to be worth guessing at: the misses
# are collected in `unknown` instead, and a caller that cares can say so.
ALIAS = {
    "\u25b8": 0x10, "\u25c2": 0x11,       # ▸ ◂ -- dir's tree markers
    "\u25b4": 0x1E, "\u25be": 0x1F,       # ▴ ▾
    "\u25cf": 0x07,                       # ● -- a bullet, one size down
    "\u2026": 0x2E,                       # … -- one cell, so one dot
}

# Every character asked for that none of the above could draw.
unknown = set()


def index(cell):
    """The CP437 code a screen cell is drawn with.

    A cell is a string rather than a character: the harness appends a combining
    mark to the character it belongs to, which is what that cell holds. CP437
    has no combining marks, so the base character is the whole answer.
    """
    if not cell:
        return 0x20
    ch = cell[0]
    if ch in LOW:
        return LOW[ch]
    if ch in ALIAS:
        return ALIAS[ch]
    try:
        return ch.encode("cp437")[0]
    except UnicodeEncodeError:
        unknown.add(ch)
        return 0x3F


def rows(cell):
    """The sixteen bytes of a cell's glyph."""
    i = index(cell) * HEIGHT
    return GLYPHS[i:i + HEIGHT]
