import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from app.schemas.artwork import ArtworkInfo


class DownloadPathBuilder:
    """
    负责下载文件的本地路径和文件名规则。
    """

    def __init__(self, download_dir: str | Path):
        self.download_dir = Path(download_dir)

    def infer_extension(self, url: str, content_type: str | None = None) -> str:
        """
        优先根据响应头推断扩展名，其次再回退到 URL 后缀。
        """
        if content_type:
            normalized_type = content_type.split(";")[0].strip().lower()
            guessed = mimetypes.guess_extension(normalized_type)
            if guessed:
                return ".jpg" if guessed == ".jpe" else guessed

        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix:
            return suffix

        return ".bin"

    def _sanitize_path_part(self, text: str) -> str:
        """
        清理不适合 Windows 文件系统的字符。
        """
        sanitized = re.sub(r'[<>:"/\\|?*]+', "_", text).strip(" .")
        if not sanitized:
            return "unknown_author"
        return sanitized[:80]

    def build_author_folder_name(self, artwork: ArtworkInfo) -> str:
        """
        生成作者目录名。
        """
        safe_author_name = self._sanitize_path_part(artwork.author_name or "unknown_author")
        safe_user_id = self._sanitize_path_part(artwork.user_id)

        if artwork.user_id:
            return f"{safe_author_name}_{safe_user_id}"

        return safe_author_name

    def build_file_stem(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
    ) -> str:
        """
        生成图片文件名主干。
        """
        safe_title = self._sanitize_path_part(artwork.title or artwork.artwork_id)
        base_name = f"{safe_title}__{artwork.artwork_id}"

        if total_pages <= 1:
            return base_name

        return f"{base_name}_p{page_index}"

    def build_output_path(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        url: str,
        content_type: str | None = None,
        total_pages: int | None = None,
    ) -> Path:
        """
        生成图片最终落盘路径。
        """
        author_dir = self.download_dir / self.build_author_folder_name(artwork)
        author_dir.mkdir(parents=True, exist_ok=True)

        extension = self.infer_extension(url, content_type=content_type)
        stem = self.build_file_stem(
            artwork,
            page_index,
            total_pages=total_pages if total_pages is not None else artwork.page_count,
        )
        return author_dir / f"{stem}{extension}"

    def find_existing_file_for_page(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
    ) -> Path | None:
        """
        查找某一页是否已经存在任意扩展名的本地文件。
        """
        author_dir = self.download_dir / self.build_author_folder_name(artwork)
        if not author_dir.exists():
            return None

        stem = self.build_file_stem(artwork, page_index, total_pages=total_pages)
        matches = sorted(author_dir.glob(f"{stem}.*"))
        return matches[0] if matches else None
