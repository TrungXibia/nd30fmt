#!/usr/bin/env python3
"""
Document to Markdown converter.
Ho tro: PDF, DOCX, TXT, MD, PNG, JPG, TIFF
Output: thu muc <stem>_chunks/ voi manifest.json va cac phan 001.md, 002.md...

Tu ban cap nhat nay: cung trich xuat anh nhung trong PDF/DOCX ra file rieng
(luu canh markdown, chen link ![...] dung vi tri), va nhan dien bang trong PDF
tot hon bang bo tim bang cua pymupdf (page.find_tables()).

Yeu cau: pymupdf (>=1.23, de co find_tables()), python-docx, tesseract (vie+eng)
"""

import sys
import os
import json
import re
from pathlib import Path

CHUNK_SIZE = 8000  # ky tu moi chunk
# So trang PDF toi da (doi bang bien moi truong MD_MAX_PAGES). Trang vuot gioi han KHONG bi bo im lang:
# dau van ban co ghi chu ro so trang da chuyen.
MAX_PAGES = int(os.environ.get("MD_MAX_PAGES", "300") or 300)
OCR_DPI = int(os.environ.get("MD_OCR_DPI", "200") or 200)
# psm 4 (mot cot, co dong cao thap khac nhau): giu duoc dong "So: …  Ha Noi, ngay …" va dau tieng Viet tot hon psm 6
OCR_PSM = os.environ.get("MD_OCR_PSM", "4") or "4"
TRUNCATED_MARK = "[Chỉ chuyển"
OCR_OPEN, OCR_CLOSE = "\ue010", "\ue011"   # vùng chữ do OCR sinh ra (bộ sửa dấu chỉ làm việc trong vùng này)


def ocr_workers() -> int:
    """So trang OCR chay song song. Moi tien trinh tesseract chi dung 1 luong (OMP_THREAD_LIMIT=1):
    tesseract mac dinh tu chia nhieu luong va tranh CPU voi nhau, cham hon ~4 lan tren VPS it nhan."""
    env = os.environ.get("MD_OCR_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, min(4, os.cpu_count() or 1))


def _tesseract(image_path, timeout: int = 180) -> str:
    import subprocess
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    try:
        result = subprocess.run(["tesseract", str(image_path), "stdout", "-l", "vie+eng", "--psm", OCR_PSM],
                                capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as e:
        raise RuntimeError("Chưa cài bộ nhận dạng chữ (Tesseract). Bản máy tính: chạy CongCuVanBanND30-OCR.exe để cài thêm; "
                           "máy chủ: cài tesseract-ocr và tesseract-ocr-vie") from e
    except subprocess.TimeoutExpired:
        return "[OCR quá thời gian ở trang này]"
    return result.stdout


SCAN_COVER = 0.6         # anh phu >= 60% trang -> coi la trang quet
SCAN_MAX_TEXT = 400      # trang quet thuong chi co lop chu ky so ("Ky boi: ... Thoi gian ky: ...") vai chuc ky tu


def _image_cover(page) -> float:
    """Ti le dien tich trang bi anh phu (anh quet ca trang ~ 1.0)."""
    area = abs(page.rect) or 1.0
    best = 0.0
    try:
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                best = max(best, abs(r & page.rect) / area)
    except Exception:  # noqa: BLE001 - ban pymupdf cu
        return 0.0
    return best


def needs_ocr(page, text: str) -> bool:
    """Trang can nhan dang chu: gan nhu khong co chu, HOAC la anh quet ca trang chi kem it chu
    (VD van ban scan co lop chu ky so "Ky boi: BO TAI CHINH ... Thoi gian ky: ..." – truoc day bi bo qua OCR)."""
    t = text.strip()
    if len(t) < 50:
        return True
    return len(t) < SCAN_MAX_TEXT and _image_cover(page) >= SCAN_COVER


def _text_page_parts(doc, page, i, text, images_dir, image_url_prefix):
    page_parts = [f"--- Trang {i + 1} ---", text]
    # Bang: dung bo nhan dien bang cua pymupdf (giu cau truc hang/cot).
    try:
        tables = page.find_tables()
        for t_idx, tbl in enumerate(tables.tables):
            try:
                md_table = tbl.to_markdown()
            except Exception:
                md_table = None
            if md_table and md_table.strip():
                page_parts.append(f"**Bang {i + 1}.{t_idx + 1} (nhan dien tu dong tu PDF):**\n\n{md_table}")
    except Exception:
        pass  # ban pymupdf cu khong co find_tables()
    # Anh nhung trong trang: trich xuat ra file rieng, chen link markdown.
    if images_dir is not None:
        area = abs(page.rect) or 1.0
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                if any(abs(r & page.rect) / area >= SCAN_COVER for r in page.get_image_rects(xref)):
                    continue  # anh chup ca trang (PDF quet co lop chu): chu da co, khong chen anh nang
            except Exception:  # noqa: BLE001
                pass
            try:
                base = doc.extract_image(xref)
                ext = base.get("ext", "png")
                fname = f"pdf_p{i + 1}_img{img_idx + 1}.{ext}"
                images_dir.mkdir(parents=True, exist_ok=True)
                (images_dir / fname).write_bytes(base["image"])
                page_parts.append(f"![Hinh trang {i + 1}]({image_url_prefix}{fname})")
            except Exception as e:
                page_parts.append(f"[Khong trich xuat duoc anh trang {i + 1}: {e}]")
    return "\n\n".join(page_parts)


def pdf_to_text(path: Path, images_dir: Path = None, image_url_prefix: str = "", progress=None) -> str:
    """PDF -> Markdown theo trang. Trang co chu: lay chu + bang + anh nhung. Trang quet (gan nhu khong co chu):
    OCR song song nhieu trang, anh quet ca trang khong chen vao Markdown (da co chu nhan dang).
    progress(done, total) duoc goi sau moi trang."""
    import shutil
    import tempfile
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    import pymupdf
    doc = pymupdf.open(str(path))
    total = len(doc)
    n = min(total, MAX_PAGES)
    parts = [""] * n
    stamps = {}   # chu san co tren trang quet (thuong la thong tin chu ky so), giu lai
    done = 0

    def tick():
        if progress:
            progress(done, n)

    tick()
    workers = ocr_workers()
    tmp = tempfile.mkdtemp(prefix="ocr_")
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pending = {}

            def collect(futs):
                nonlocal done
                for fut in futs:
                    i = pending.pop(fut)
                    try:
                        txt = fut.result()
                    except Exception as e:  # noqa: BLE001
                        txt = f"[OCR loi: {e}]"
                    stamp = stamps.get(i)
                    head = f"--- Trang {i + 1} ---\n\n" + (f"> Chữ ký số: {stamp}\n\n" if stamp else "")
                    parts[i] = head + OCR_OPEN + txt + OCR_CLOSE
                    done += 1
                    tick()

            for i in range(n):
                page = doc[i]
                text = page.get_text()
                if needs_ocr(page, text):
                    # anh xam du cho OCR, nhe hon anh mau; ve trang o luong chinh (pymupdf khong an toan da luong)
                    png = os.path.join(tmp, f"p{i}.png")
                    page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY).save(png)
                    pending[ex.submit(_tesseract, png)] = i
                    stamps[i] = " ".join(text.split())
                    if len(pending) >= workers * 2:  # gioi han so anh tam cho xu ly
                        fin, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                        collect(fin)
                else:
                    parts[i] = _text_page_parts(doc, page, i, text, images_dir, image_url_prefix)
                    done += 1
                    tick()
            while pending:
                fin, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                collect(fin)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        doc.close()
    out = "\n\n".join(parts)
    if total > n:
        out = (f"> {TRUNCATED_MARK} {n}/{total} trang đầu của PDF (giới hạn MD_MAX_PAGES={MAX_PAGES}); "
               f"tách file để chuyển phần còn lại.]\n\n" + out)
    return out


def ocr_page(page) -> str:
    """Giu cho tuong thich: OCR mot trang PDF."""
    import tempfile
    import pymupdf
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY).save(tmp)
        return _tesseract(tmp)
    finally:
        os.unlink(tmp)


_DOCX_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_DOCX_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _extract_docx_paragraph_images(doc, para, images_dir: Path, image_url_prefix: str, counter: list):
    """Tim cac the <a:blip> (anh nhung) trong 1 doan van DOCX, luu ra file va
    tra ve danh sach dong markdown ![...] tuong ung, theo dung thu tu xuat hien."""
    if images_dir is None:
        return []
    out = []
    blips = para._element.findall(f".//{{{_DOCX_A_NS}}}blip")
    for blip in blips:
        rid = blip.get(f"{{{_DOCX_R_NS}}}embed")
        if not rid:
            continue
        try:
            part = doc.part.related_parts[rid]
            counter[0] += 1
            ext = part.content_type.split("/")[-1]
            ext = {"jpeg": "jpg"}.get(ext, ext)
            fname = f"docx_img{counter[0]}.{ext}"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / fname).write_bytes(part.blob)
            out.append(f"![Hinh {counter[0]}]({image_url_prefix}{fname})")
        except Exception as e:
            out.append(f"[Khong trich xuat duoc anh: {e}]")
    return out


def _md_cell(text: str) -> str:
    lines = [x.strip() for x in text.strip().split("\n") if x.strip()]
    return "<br>".join(lines).replace("|", "\\|")


def docx_to_text(path: Path, images_dir: Path = None, image_url_prefix: str = "") -> str:
    """Doc DOCX theo dung thu tu doan van / bang trong than van ban; giu dam/nghieng, tieu de, danh sach."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(str(path))
    parts = []
    img_counter = [0]

    def inline(para):
        out = []
        for r in para.runs:
            t = r.text
            if not t:
                continue
            core = t.strip()
            if core and (r.bold or r.italic):
                lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
                mark = "**" if r.bold and not r.italic else "*" if r.italic and not r.bold else "***"
                t = f"{lead}{mark}{core}{mark}{trail}"
            out.append(t)
        text = "".join(out).strip()
        return text or para.text.strip()

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            img_lines = _extract_docx_paragraph_images(doc, para, images_dir, image_url_prefix, img_counter)
            if para.text.strip():
                style = (para.style.name if para.style is not None else "") or ""
                m = re.match(r"(?:Heading|Tiêu đề)\s*(\d)", style, re.I)
                if m and int(m.group(1)) <= 4:
                    parts.append("#" * int(m.group(1)) + " " + para.text.strip())
                elif style.lower().startswith("list bullet"):
                    parts.append("- " + inline(para))
                else:
                    parts.append(inline(para))
            parts.extend(img_lines)
        elif tag == "tbl":
            table = Table(child, doc)
            rows = []
            for i, row in enumerate(table.rows):
                cells = []
                for c in row.cells:
                    cells.append(_md_cell(c.text))
                rows.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    rows.append("|" + "|".join(["---"] * len(cells)) + "|")
            if rows:
                parts.append("\n".join(rows))
    return "\n\n".join(parts)


def image_to_text(path: Path) -> str:
    return OCR_OPEN + _tesseract(path, timeout=180) + OCR_CLOSE


def txt_to_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def convert(path: Path, images_dir: Path = None, image_url_prefix: str = "{IMGBASE}/", progress=None) -> str:
    """Chuyen 1 file sang Markdown.

    images_dir: neu khac None, anh nhung trong PDF/DOCX se duoc luu vao thu
      muc nay (tao moi neu chua co).
    image_url_prefix: chuoi chen truoc ten file anh trong link markdown
      ![...](image_url_prefix + filename). Mac dinh la placeholder
      "{IMGBASE}/" de code goi (vi du app.py) tu thay the bang duong dan
      thuc te (URL rieng, hoac duong dan tuong doi khi dung CLI truc tiep).
    """
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_to_text(path, images_dir=images_dir, image_url_prefix=image_url_prefix, progress=progress)
    elif ext == ".docx":
        return docx_to_text(path, images_dir=images_dir, image_url_prefix=image_url_prefix)
    elif ext == ".doc":
        return legacy_doc_to_text(path)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"):
        return image_to_text(path)
    elif ext in (".txt", ".md", ".markdown"):
        return txt_to_text(path)
    else:
        raise ValueError(f"Dinh dang khong ho tro: {ext}")


def legacy_doc_to_text(path: Path) -> str:
    """File .doc (Word 97-2003, dang nhi phan OLE) khac han .docx (zip/XML) nen
    python-docx khong doc duoc. Dung antiword de trich text thuan (khong giu
    duoc bang/anh nhu .docx, nhung it nhat lay duoc noi dung chu)."""
    import subprocess
    try:
        result = subprocess.run(
            ["antiword", str(path)], capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        converted = _doc_via_libreoffice(path)
        if converted is not None:
            return converted
        raise RuntimeError(
            "File .doc (Word cu) can cong cu 'antiword' de doc, nhung VPS chua cai. "
            "Chay: sudo apt install -y antiword -- roi upload lai file nay. "
            "Hoac mo file bang Word/LibreOffice, luu lai dang .docx roi upload."
        )
    if result.returncode != 0 or not result.stdout.strip():
        err = (result.stderr or "").strip()[:300]
        raise RuntimeError(
            f"Khong doc duoc file .doc nay bang antiword ({err or 'khong co noi dung'}). "
            "Hay mo file bang Word/LibreOffice, luu lai dang .docx roi upload lai."
        )
    return result.stdout


def _doc_via_libreoffice(path: Path):
    """Khi may khong co antiword: dung LibreOffice (co san trong container) chuyen .doc -> .docx roi doc."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([exe, "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)],
                           capture_output=True, timeout=120)
        except Exception:
            return None
        out = Path(tmp) / (path.stem + ".docx")
        if not out.exists():
            return None
        return docx_to_text(out)


def chunk_text(text: str, size: int = CHUNK_SIZE):
    paragraphs = re.split(r"\n{2,}", text)
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > size and current:
            chunks.append(current.strip())
            current = para
        else:
            current += ("\n\n" if current else "") + para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def process(input_path: str):
    path = Path(input_path).resolve()
    if not path.exists():
        print(f"Loi: Khong tim thay file '{path}'")
        sys.exit(1)

    print(f"Dang xu ly: {path.name}", file=sys.stderr)

    chunk_dir = path.parent / (path.stem + "_chunks")
    chunk_dir.mkdir(exist_ok=True)
    images_dir = chunk_dir / "images"

    # Dung CLI: anh luu vao <stem>_chunks/images/, link markdown la duong dan
    # tuong doi "images/<file>" (mo duoc ngay khi doc file .md canh do).
    text = convert(path, images_dir=images_dir, image_url_prefix="images/")

    chunks = chunk_text(text)
    manifest = {
        "source": str(path),
        "total_chars": len(text),
        "total_chunks": len(chunks),
        "chunk_size": CHUNK_SIZE,
        "chunks": []
    }

    for i, chunk in enumerate(chunks):
        fname = f"{i + 1:03d}.md"
        (chunk_dir / fname).write_text(chunk, encoding="utf-8")
        manifest["chunks"].append({
            "file": fname,
            "chars": len(chunk),
            "preview": chunk[:120].replace("\n", " ")
        })

    (chunk_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # In ra stdout de skill doc duoc
    print(f"OK:{len(chunks)}:{chunk_dir}")
    return chunk_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Dung: python3 doc_to_md.py <file>")
        sys.exit(1)
    process(sys.argv[1])
