"""
PDF 处理模块
- 矢量文本提取（用于规则前置检查）
- 页面渲染（全局缩略图 + 标题栏切片 + 高密度标注区分块）
- 资源上限：页数 / 页面尺寸 / 渲染像素总量限制，防止超大或恶意输入导致内存峰值
"""
import io
import base64
import math
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:
    import fitz  # PyMuPDF < 1.24 (legacy)
from PIL import Image

from config import PDF_CONFIG


class PDFOpenError(Exception):
    """PDF 打开/校验失败（含明确的中文原因分类）"""


class PDFChunk:
    """一个渲染切片"""
    def __init__(self, chunk_type: str, page_num: int, image: Image.Image,
                 bbox: Optional[Tuple[float, float, float, float]] = None,
                 description: str = ""):
        self.chunk_type = chunk_type      # global / title_block / detail
        self.page_num = page_num
        self.image = image
        self.bbox = bbox                  # 原图坐标 (x0, y0, x1, y1)
        self.description = description

    def to_base64(self, max_size: int = 1536, quality: int = 80) -> str:
        """转为 JPEG base64，限制最大边长（默认 1536，平衡清晰度与传输体积）"""
        img = self.image.copy()
        w, h = img.size
        scale = min(1.0, max_size / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def save(self, path: str):
        self.image.save(path)


class PDFProcessor:
    """PDF 处理器（打开时即校验：损坏 / 加密 / 空 / 超限）"""

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        try:
            self.doc = fitz.open(str(pdf_path))
        except Exception as e:
            raise PDFOpenError(f"无法打开 PDF（文件损坏或格式不正确）: {e}") from e

        # 加密 PDF
        if self.doc.needs_pass:
            self.doc.close()
            raise PDFOpenError("PDF 已加密，无法读取。请先解除密码保护后重试。")

        self.page_count = len(self.doc)

        # 空 PDF
        if self.page_count == 0:
            self.doc.close()
            raise PDFOpenError("PDF 没有任何页面（空文件）。")

        # 页数上限
        max_pages = PDF_CONFIG.get("max_pages", 30)
        if self.page_count > max_pages:
            self.doc.close()
            raise PDFOpenError(
                f"PDF 共 {self.page_count} 页，超过单张图纸最多 {max_pages} 页的限制。"
                "请拆分后分批审核。")

        # 页面尺寸上限（防超大页面导致渲染内存峰值）
        max_side = PDF_CONFIG.get("max_page_side_pt", 8000)
        for page in self.doc:
            pw, ph = page.rect.width, page.rect.height
            if pw > max_side or ph > max_side:
                self.doc.close()
                raise PDFOpenError(
                    f"页面尺寸 {pw:.0f}×{ph:.0f}pt 超过上限 {max_side}pt，"
                    "可能是异常或超大图纸，请检查文件。")

    def close(self):
        if getattr(self, "doc", None) is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 矢量文本提取 ──────────────────────────────────────────

    def extract_text(self) -> str:
        """提取全文档矢量文本"""
        texts = []
        for page in self.doc:
            texts.append(page.get_text("text"))
        return "\n".join(texts)

    def extract_text_with_positions(self, page_num: int = 0) -> List[Dict[str, Any]]:
        """提取指定页文本及位置（用于定位标题栏）"""
        page = self.doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        results = []
        for block in blocks:
            if block["type"] != 0:  # 只处理文本块
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    results.append({
                        "text": span["text"].strip(),
                        "bbox": span["bbox"],  # (x0, y0, x1, y1)
                        "size": span["size"],
                        "font": span["font"],
                    })
        return [r for r in results if r["text"]]

    def find_title_block_bbox(self, page_num: int = 0) -> Optional[fitz.Rect]:
        """
        尝试定位标题栏区域（通常在右下角）。
        策略：取页面右下角 1/3 宽度、1/4 高度的区域。
        """
        page = self.doc[page_num]
        pw, ph = page.rect.width, page.rect.height
        # 标题栏通常在右下角
        x0 = pw * 0.55
        y0 = ph * 0.72
        x1 = pw * 0.98
        y1 = ph * 0.98
        return fitz.Rect(x0, y0, x1, y1)

    def extract_title_block_text(self, page_num: int = 0) -> str:
        """
        提取标题栏区域内的文本（坐标过滤），用于规则前置检查，
        降低"图号/版本/材料"从技术要求或备注中被误识别为标题栏字段的误报率。
        返回空串表示未定位到标题栏文本（调用方可回退到全文）。
        """
        try:
            bbox = self.find_title_block_bbox(page_num)
            spans = self.extract_text_with_positions(page_num)
        except Exception:
            return ""
        lines = []
        for span in spans:
            b = span["bbox"]
            # span 中心点落在标题栏区域内才收录
            cx = (b[0] + b[2]) / 2.0
            cy = (b[1] + b[3]) / 2.0
            if bbox.x0 <= cx <= bbox.x1 and bbox.y0 <= cy <= bbox.y1:
                lines.append(span["text"])
        return "\n".join(lines)

    # ── 页面渲染 ──────────────────────────────────────────────

    def render_page(self, page_num: int, dpi: int = 200,
                    clip: Optional[fitz.Rect] = None) -> Image.Image:
        """渲染单页（或局部区域）为 PIL Image（自动按像素上限降 DPI）"""
        page = self.doc[page_num]
        zoom = dpi / 72.0
        max_pixels = PDF_CONFIG.get("max_render_pixels", 400_000_000)
        # 若按当前 DPI 渲染会超过单次像素上限，则自动降低 DPI
        try:
            if clip:
                rw, rh = clip.width, clip.height
            else:
                rw, rh = page.rect.width, page.rect.height
            est = int(rw * zoom) * int(rh * zoom)
            if est > max_pixels:
                zoom = zoom * math.sqrt(max_pixels / est)
        except Exception:
            pass
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img

    def render_thumbnail(self, page_num: int = 0, max_width: int = 400) -> str:
        """渲染缩略图 base64（用于前端列表展示）"""
        img = self.render_page(page_num, dpi=PDF_CONFIG["global_dpi"])
        w, h = img.size
        scale = max_width / w
        img = img.resize((max_width, int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    # ── 智能分块（核心） ───────────────────────────────────────

    def generate_chunks(self) -> List[PDFChunk]:
        """
        为整个 PDF 生成审核切片集合。
        策略（每页）：
        1. 全局缩略图（150 DPI）— 审查总体布局、视图完整性、图框位置
        2. 标题栏切片（400 DPI）— 右下角高保真识别
        3. 高密度标注区分块（300 DPI）— 切成 2~4 个局部区域
        累计渲染像素超过上限后停止新增切片，防止内存峰值。
        """
        chunks = []
        total_pixels = 0
        max_total = PDF_CONFIG.get("max_total_pixels", 800_000_000)

        for page_num in range(self.page_count):
            page = self.doc[page_num]
            pw, ph = page.rect.width, page.rect.height

            # 1. 全局缩略图
            global_img = self.render_page(page_num, dpi=PDF_CONFIG["global_dpi"])
            total_pixels += global_img.width * global_img.height
            chunks.append(PDFChunk(
                chunk_type="global",
                page_num=page_num,
                image=global_img,
                description=f"第{page_num+1}页全局视图，用于审查总体布局、视图完整性、图框位置"
            ))

            # 2. 标题栏切片
            title_bbox = self.find_title_block_bbox(page_num)
            if title_bbox:
                title_img = self.render_page(page_num, dpi=PDF_CONFIG["title_block_dpi"],
                                              clip=title_bbox)
                total_pixels += title_img.width * title_img.height
                chunks.append(PDFChunk(
                    chunk_type="title_block",
                    page_num=page_num,
                    image=title_img,
                    bbox=(title_bbox.x0, title_bbox.y0, title_bbox.x1, title_bbox.y1),
                    description=f"第{page_num+1}页标题栏区域（右下角），高保真识别图名/图号/版本/签名/材料"
                ))

            # 3. 高密度标注区分块
            detail_chunks = self._generate_detail_chunks(page_num, pw, ph)
            for dc in detail_chunks:
                total_pixels += dc.image.width * dc.image.height
            chunks.extend(detail_chunks)

            # 累计像素超限：停止继续渲染，避免内存峰值
            if total_pixels > max_total:
                break

        return chunks

    def _generate_detail_chunks(self, page_num: int, pw: float, ph: float) -> List[PDFChunk]:
        """
        将页面切分为 2~4 个高密度标注区域。
        策略：按网格均分，排除标题栏区域（已单独切片）。
        """
        max_chunks = PDF_CONFIG["max_detail_chunks"]
        dpi = PDF_CONFIG["detail_dpi"]

        # 确定行列数（2x2 = 4块，或 2x1 = 2块）
        if pw / ph > 1.3:  # 横版图纸
            cols, rows = 2, 2
        else:
            cols, rows = 2, 2

        chunks = []
        title_bbox = self.find_title_block_bbox(page_num)

        for row in range(rows):
            for col in range(cols):
                x0 = pw * col / cols
                y0 = ph * row / rows
                x1 = pw * (col + 1) / cols
                y1 = ph * (row + 1) / rows

                # 跳过完全被标题栏覆盖的块（右下角块）
                if title_bbox and col == cols - 1 and row == rows - 1:
                    # 缩小该块，排除标题栏区域
                    y1 = title_bbox.y0 - 5
                    if y1 - y0 < PDF_CONFIG["min_chunk_size"] * 72 / dpi:
                        continue

                clip = fitz.Rect(x0, y0, x1, y1)
                img = self.render_page(page_num, dpi=dpi, clip=clip)

                # 过滤过小或空白块
                if img.width < PDF_CONFIG["min_chunk_size"] or \
                   img.height < PDF_CONFIG["min_chunk_size"]:
                    continue
                if self._is_blank(img):
                    continue

                chunks.append(PDFChunk(
                    chunk_type="detail",
                    page_num=page_num,
                    image=img,
                    bbox=(x0, y0, x1, y1),
                    description=f"第{page_num+1}页局部区域（{col+1}/{cols}列, {row+1}/{rows}行），高密度标注审查"
                ))

                if len([c for c in chunks if c.chunk_type == "detail"]) >= max_chunks:
                    return chunks

        return chunks

    @staticmethod
    def _is_blank(img: Image.Image, threshold: int = 250, ratio: float = 0.98) -> bool:
        """判断图片是否为空白（用于过滤无内容切片）"""
        gray = img.convert("L")
        # 采样检查
        w, h = gray.size
        sample = gray.resize((max(1, w // 10), max(1, h // 10)))
        pixels = list(sample.getdata())
        white_count = sum(1 for p in pixels if p >= threshold)
        return white_count / len(pixels) > ratio


def scan_pdf_folder(folder_path: str, recursive: bool = True) -> List[str]:
    """扫描文件夹中的所有 PDF 文件"""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_files = sorted(folder.glob(pattern), key=lambda p: str(p).lower())
    return [str(p) for p in pdf_files if p.is_file()]
