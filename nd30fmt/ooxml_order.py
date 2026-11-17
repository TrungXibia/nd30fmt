"""Sắp lại thứ tự phần tử con theo lược đồ OOXML trước khi lưu file Word.

python-docx chèn phần tử mới (w:b, w:u, w:jc, w:outlineLvl, w:rFonts...) dựa trên danh sách
"phần tử đứng sau" của riêng nó; danh sách này KHÔNG có w:rPrChange, w:pPrChange và các phần tử
mở rộng w14:*. Với file Word thật có theo dõi thay đổi (Track Changes) hoặc định dạng Word 2010+,
phần tử mới bị nối vào SAU w:rPrChange/w14:* -> sai lược đồ -> Word báo
"Word found unreadable content" / "file bị hỏng" khi mở bản đã sửa.

Hàm normalize_document() chỉ đổi THỨ TỰ phần tử con (không thêm/bớt nội dung), nên an toàn để
gọi trước mọi lần lưu.
"""
from __future__ import annotations

from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# CT_RPr / EG_RPrBase (ECMA-376 Part 1, 17.3.2)
_RPR_BASE = ("rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
             "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
             "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
             "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath")
# CT_ParaRPr (rPr của dấu đoạn trong w:pPr) có thêm các dấu sửa đổi ở đầu
_PARA_RPR_HEAD = ("ins", "del", "moveFrom", "moveTo")

# CT_PPrBase + phần đuôi của CT_PPr (17.3.1.26)
_PPR_BASE = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
             "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
             "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
             "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
             "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle")
_PPR_TAIL = ("rPr", "sectPr", "pPrChange")

# CT_Settings (17.15.1.78) – dùng để đặt w:updateFields đúng chỗ
SETTINGS_SEQ = (
    "writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
    "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
    "printFractionalCharacterWidth", "printFormsData", "embedTrueTypeFonts", "embedSystemFonts",
    "saveSubsetFonts", "saveFormsData", "mirrorMargins", "alignBordersAndEdges", "bordersDoNotSurroundHeader",
    "bordersDoNotSurroundFooter", "gutterAtTop", "hideSpellingErrors", "hideGrammaticalErrors",
    "activeWritingStyle", "proofState", "formsDesign", "attachedTemplate", "linkStyles",
    "stylePaneFormatFilter", "stylePaneSortMethod", "documentType", "mailMerge", "revisionView",
    "trackRevisions", "doNotTrackMoves", "doNotTrackFormatting", "documentProtection", "autoFormatOverride",
    "styleLockTheme", "styleLockQFSet", "defaultTabStop", "autoHyphenation", "consecutiveHyphenLimit",
    "hyphenationZone", "doNotHyphenateCaps", "showEnvelope", "summaryLength", "clickAndTypeStyle",
    "defaultTableStyle", "evenAndOddHeaders", "bookFoldRevPrinting", "bookFoldPrinting",
    "bookFoldPrintingSheets", "drawingGridHorizontalSpacing", "drawingGridVerticalSpacing",
    "displayHorizontalDrawingGridEvery", "displayVerticalDrawingGridEvery",
    "doNotUseMarginsForDrawingGridOrigin", "drawingGridHorizontalOrigin", "drawingGridVerticalOrigin",
    "doNotShadeFormData", "noPunctuationKerning", "characterSpacingControl", "printTwoOnOne",
    "strictFirstAndLastChars", "noLineBreaksAfter", "noLineBreaksBefore", "savePreviewPicture",
    "doNotValidateAgainstSchema", "saveInvalidXml", "ignoreMixedContent", "alwaysShowPlaceholderText",
    "doNotDemarcateInvalidXml", "saveXmlDataOnly", "useXSLTWhenSaving", "saveThroughXslt", "showXMLTags",
    "alwaysMergeEmptyNamespace", "updateFields", "hdrShapeDefaults", "footnotePr", "endnotePr", "compat",
    "docVars", "rsids", "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping",
    "doNotIncludeSubdocsInStats", "doNotAutoCompressPictures", "forceUpgrade", "captions",
    "readModeInkLockDown", "smartTagType", "schemaLibrary", "shapeDefaults", "doNotEmbedSmartTags",
    "decimalSymbol", "listSeparator")


def _rank_map(seq: tuple[str, ...]) -> dict[str, int]:
    return {f"{{{W_NS}}}{name}": i for i, name in enumerate(seq)}


_RPR_RANK = _rank_map(_RPR_BASE)
_PARA_RPR_RANK = _rank_map(_PARA_RPR_HEAD + _RPR_BASE)
_PPR_RANK = _rank_map(_PPR_BASE)
_SETTINGS_RANK = _rank_map(SETTINGS_SEQ) | {f"{{{M_NS}}}mathPr": SETTINGS_SEQ.index("mathPr")}

_RPR_CHANGE = qn("w:rPrChange")
_PPR_CHANGE = qn("w:pPrChange")


def _reorder(parent, key) -> bool:
    kids = list(parent)
    if len(kids) < 2:
        return False
    ranked = sorted(range(len(kids)), key=lambda i: (key(kids[i]), i))  # sắp ổn định
    if ranked == list(range(len(kids))):
        return False
    new = [kids[i] for i in ranked]
    for k in kids:
        parent.remove(k)
    parent.extend(new)
    return True


def _rpr_key(rank: dict[str, int]):
    n = len(rank)

    def key(el):
        tag = el.tag
        if not isinstance(tag, str):          # chú thích/processing instruction: để cuối nhóm cơ sở
            return n
        if tag == _RPR_CHANGE:
            return n + 2                      # luôn đứng cuối
        if tag in rank:
            return rank[tag]
        return n + 1                          # w14:*, phần tử mở rộng: sau nhóm cơ sở, trước rPrChange
    return key


def _ppr_key(el):
    n = len(_PPR_RANK)
    tag = el.tag
    if not isinstance(tag, str):
        return n
    if tag in _PPR_RANK:
        return _PPR_RANK[tag]
    local = tag.rsplit("}", 1)[-1]
    if tag.startswith(f"{{{W_NS}}}") and local in _PPR_TAIL:
        return n + 1 + _PPR_TAIL.index(local)
    return n                                  # phần tử mở rộng: sau nhóm cơ sở, trước rPr/sectPr/pPrChange


def normalize_element(root) -> int:
    """Sắp lại mọi w:rPr và w:pPr bên dưới root. Trả về số phần tử đã đổi thứ tự."""
    changed = 0
    run_key = _rpr_key(_RPR_RANK)
    para_key = _rpr_key(_PARA_RPR_RANK)
    ppr_tag, rpr_tag = qn("w:pPr"), qn("w:rPr")
    for ppr in root.iter(ppr_tag):
        changed += _reorder(ppr, _ppr_key)
    for rpr in root.iter(rpr_tag):
        parent = rpr.getparent()
        is_mark = parent is not None and parent.tag == ppr_tag
        changed += _reorder(rpr, para_key if is_mark else run_key)
    return changed


def insert_update_fields(settings_el) -> None:
    """Đặt <w:updateFields w:val="true"/> đúng vị trí theo lược đồ CT_Settings."""
    el = settings_el.find(qn("w:updateFields"))
    if el is None:
        from docx.oxml import OxmlElement
        el = OxmlElement("w:updateFields")
        el.set(qn("w:val"), "true")
    else:
        settings_el.remove(el)
    limit = _SETTINGS_RANK[qn("w:updateFields")]
    for child in settings_el:
        if isinstance(child.tag, str) and _SETTINGS_RANK.get(child.tag, -1) > limit:
            child.addprevious(el)
            return
    # không có phần tử nào đứng sau updateFields: đặt sau phần tử cuối cùng đứng trước nó
    settings_el.append(el)


def _parts_with_xml(doc):
    """document.xml + header/footer + styles (các phần python-docx đã nạp thành cây XML)."""
    seen = set()
    for part in doc.part.package.iter_parts():
        el = getattr(part, "_element", None)
        if el is not None and id(el) not in seen:
            seen.add(id(el))
            yield part, el


def normalize_document(doc) -> int:
    """Gọi ngay trước doc.save(): sửa thứ tự w:pPr/w:rPr trên mọi phần XML và vị trí updateFields."""
    changed = 0
    for part, el in _parts_with_xml(doc):
        changed += normalize_element(el)
    try:
        settings_el = doc.settings.element
    except Exception:  # noqa: BLE001 - file không có settings.xml
        settings_el = None
    if settings_el is not None and settings_el.find(qn("w:updateFields")) is not None:
        insert_update_fields(settings_el)
    return changed


def save_docx(doc, path) -> None:
    normalize_document(doc)
    doc.save(str(path))
