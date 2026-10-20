"""Build a Chinese-friendly reference.docx for pandoc.

Patches pandoc's default reference document with:
  * A4 page size and Chinese-standard margins
  * Microsoft YaHei for East Asian text (with a Hans theme mapping)
  * 10.5pt body text, 1.5 line spacing, justified
  * Brand-coloured headings, a styled code block style, caption styling
  * TOC1..TOC3 styles and auto field update so Word fills the TOC on open
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent / "build"
SRC = BUILD / "reference-default.docx"
WORK = BUILD / "refpatch"
OUT = BUILD / "reference-zh.docx"

BRAND = "1D3324"
ACCENT = "B5402A"
MUTED = "5D6B58"
CJK = "Microsoft YaHei"
LATIN = "Calibri"
MONO = "Consolas"


def patch_theme(xml: str) -> str:
    xml = xml.replace('<a:ea typeface=""/>', f'<a:ea typeface="{CJK}"/>')
    if 'script="Hans"' not in xml:
        xml = xml.replace(
            '<a:font script="Jpan" typeface="游ゴシック Light"/>',
            f'<a:font script="Hans" typeface="{CJK}"/><a:font script="Jpan" typeface="游ゴシック Light"/>',
        )
        xml = xml.replace(
            '<a:font script="Jpan" typeface="游明朝"/>',
            f'<a:font script="Hans" typeface="{CJK}"/><a:font script="Jpan" typeface="游明朝"/>',
        )
    return xml


def style_block(style_id: str, name: str, *, based_on: str = "Normal", next_style: str = "Normal",
                ppr: str = "", rpr: str = "") -> str:
    return (
        f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{style_id}">'
        f'<w:name w:val="{name}"/><w:basedOn w:val="{based_on}"/><w:next w:val="{next_style}"/>'
        f"<w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
    )


def patch_styles(xml: str) -> str:
    # --- Normal: CJK body text -------------------------------------------------
    xml = re.sub(
        r'(<w:style w:type="paragraph" w:default="1" w:styleId="Normal">.*?)<w:rPr>.*?</w:rPr>',
        r'\1'
        f'<w:rPr><w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}" w:cs="Times New Roman"/>'
        '<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/></w:rPr>',
        xml,
        count=1,
        flags=re.S,
    )
    xml = re.sub(
        r'(<w:style w:type="paragraph" w:default="1" w:styleId="Normal">.*?<w:pPr>)<w:spacing[^/]*/>',
        r'\1<w:spacing w:before="0" w:after="70" w:line="288" w:lineRule="auto"/><w:jc w:val="both"/>',
        xml,
        count=1,
        flags=re.S,
    )

    # --- Headings -------------------------------------------------------------
    sizes = {"Heading1": 36, "Heading2": 28, "Heading3": 24, "Heading4": 22}
    for sid, half in sizes.items():
        pattern = re.compile(rf'(<w:style w:type="paragraph" w:styleId="{sid}">.*?)<w:rPr>.*?</w:rPr>', re.S)
        xml = pattern.sub(
            r"\1"
            f'<w:rPr><w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}"/><w:b/>'
            f'<w:color w:val="{BRAND}"/><w:sz w:val="{half}"/><w:szCs w:val="{half}"/></w:rPr>',
            xml,
            count=1,
        )
        ppat = re.compile(rf'(<w:style w:type="paragraph" w:styleId="{sid}">.*?<w:pPr>)(.*?)(</w:pPr>)', re.S)
        xml = ppat.sub(
            r'\1<w:keepNext/><w:keepLines/><w:spacing w:before="' + str(280 if sid == "Heading1" else 220)
            + r'" w:after="120"/><w:outlineLvl w:val="' + str(int(sid[-1]) - 1) + r'"/>\3',
            xml,
            count=1,
        )

    # --- Title / Subtitle / Author --------------------------------------------
    xml = re.sub(
        r'(<w:style w:type="paragraph" w:styleId="Title">.*?)<w:rPr>.*?</w:rPr>',
        r"\1"
        f'<w:rPr><w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}"/><w:b/>'
        f'<w:color w:val="{BRAND}"/><w:sz w:val="60"/><w:szCs w:val="60"/></w:rPr>',
        xml,
        count=1,
        flags=re.S,
    )
    xml = re.sub(
        r'(<w:style w:type="paragraph" w:styleId="Subtitle">.*?)<w:rPr>.*?</w:rPr>',
        r"\1"
        f'<w:rPr><w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}"/>'
        f'<w:color w:val="{ACCENT}"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>',
        xml,
        count=1,
        flags=re.S,
    )

    # --- Captions --------------------------------------------------------------
    for sid in ("Caption", "ImageCaption"):
        xml = re.sub(
            rf'(<w:style w:type="paragraph" w:styleId="{sid}">.*?)<w:rPr>.*?</w:rPr>',
            r"\1"
            f'<w:rPr><w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}"/>'
            f'<w:color w:val="{MUTED}"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr>',
            xml,
            count=1,
            flags=re.S,
        )

    # --- Extra styles pandoc references but the default file does not define ---
    extra = []
    if 'w:styleId="SourceCode"' not in xml:
        extra.append(
            style_block(
                "SourceCode",
                "Source Code",
                ppr=(
                    '<w:shd w:val="clear" w:color="auto" w:fill="F6F3EC"/>'
                    '<w:spacing w:before="50" w:after="90" w:line="240" w:lineRule="auto"/>'
                    '<w:ind w:left="170" w:right="170"/>'
                    '<w:ind w:left="170" w:right="170"/>'
                    "<w:jc w:val=\"left\"/>"
                ),
                rpr=(
                    f'<w:rFonts w:ascii="{MONO}" w:hAnsi="{MONO}" w:eastAsia="{CJK}" w:cs="{MONO}"/>'
                    '<w:sz w:val="18"/><w:szCs w:val="18"/><w:color w:val="24331F"/>'
                ),
            )
        )
    for level in (1, 2, 3):
        sid = f"TOC{level}"
        if f'w:styleId="{sid}"' not in xml:
            extra.append(
                style_block(
                    sid,
                    f"toc {level}",
                    ppr=f'<w:spacing w:before="{60 if level == 1 else 0}" w:after="60"/><w:ind w:left="{(level - 1) * 260}"/>',
                    rpr=(
                        f'<w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{CJK}"/>'
                        f'<w:sz w:val="{21 if level == 1 else 20}"/>'
                        + ("<w:b/>" if level == 1 else "")
                    ),
                )
            )
    if "Table" in xml and "TableCaption" in xml:
        pass
    xml = xml.replace("</w:styles>", "".join(extra) + "</w:styles>")
    return xml


def patch_settings(xml: str) -> str:
    if "themeFontLang" not in xml:
        xml = xml.replace(
            "<w:zoom w:percent=\"100\" />",
            '<w:zoom w:percent="100" />'
            '<w:themeFontLang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/>',
        )
    if "updateFields" not in xml:
        xml = xml.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>')
    return xml


def patch_document(xml: str) -> str:
    sect = (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" '
        'w:header="851" w:footer="992" w:gutter="0"/>'
        '<w:cols w:space="425"/><w:docGrid w:linePitch="312"/>'
        "</w:sectPr>"
    )
    if "<w:sectPr" in xml:
        xml = re.sub(r"<w:sectPr.*?</w:sectPr>", sect, xml, count=1, flags=re.S)
    else:
        xml = xml.replace("</w:body>", sect + "</w:body>")
    return xml


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    with zipfile.ZipFile(SRC) as archive:
        archive.extractall(WORK)

    plan = {
        "word/theme/theme1.xml": patch_theme,
        "word/styles.xml": patch_styles,
        "word/settings.xml": patch_settings,
        "word/document.xml": patch_document,
    }
    for name, func in plan.items():
        path = WORK / name
        text = path.read_text(encoding="utf-8")
        path.write_text(func(text), encoding="utf-8")

    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(WORK.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(WORK))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
