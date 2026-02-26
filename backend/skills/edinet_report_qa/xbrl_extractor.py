import html as html_module
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from lxml import etree


class XbrlExtractor:
    def __init__(self, xbrl_path: Path):
        parser = etree.XMLParser(recover=True)
        self.tree = etree.parse(str(xbrl_path), parser=parser)
        self.root = self.tree.getroot()
        self._available_tags = {
            etree.QName(el).localname for el in self.root.iter() if isinstance(el.tag, str)
        }
        self._id_index: dict[str, Any] = {}
        for el in self.root.iter():
            if not isinstance(el.tag, str):
                continue
            el_id = el.get("id")
            if el_id:
                self._id_index[el_id] = el

    def extract_first_available(self, tag_candidates: list[str]) -> tuple[str | None, str]:
        if not tag_candidates:
            return None, "未対応セクション（XBRLタグ未定義）"

        selected_tag = next((tag for tag in tag_candidates if tag in self._available_tags), None)
        if selected_tag is None:
            return None, "対応タグが該当XBRL内に見つかりませんでした"

        texts: list[str] = []
        for el in self.root.iter():
            if not isinstance(el.tag, str):
                continue
            if etree.QName(el).localname != selected_tag:
                continue
            raw_payload = self._collect_payload_with_continuation(el)
            if not raw_payload:
                continue
            decoded = html_module.unescape(raw_payload)
            plain_text = self._html_to_text(decoded)
            if plain_text.strip():
                texts.append(plain_text.strip())

        if not texts:
            return None, f"{selected_tag} は見つかりましたが本文抽出できませんでした"

        return "\n\n".join(texts), selected_tag

    def _collect_payload_with_continuation(self, el: Any) -> str:
        chunks: list[str] = []
        head = self._element_payload(el)
        if head:
            chunks.append(head)

        continued_at = el.get("continuedAt")
        visited: set[str] = set()
        while continued_at and continued_at not in visited:
            visited.add(continued_at)
            cont = self._id_index.get(continued_at)
            if cont is None:
                break
            cont_payload = self._element_payload(cont)
            if cont_payload:
                chunks.append(cont_payload)
            continued_at = cont.get("continuedAt")

        return "".join(chunks).strip()

    def _element_payload(self, el: Any) -> str:
        parts: list[str] = []
        if el.text:
            parts.append(el.text)
        for child in el:
            parts.append(etree.tostring(child, encoding="unicode"))
        return "".join(parts)

    def _html_to_text(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        for table in soup.find_all("table"):
            table_rows: list[str] = []
            for tr in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
                if cells:
                    table_rows.append(" | ".join(cells))
            replacement = "\n".join(table_rows) if table_rows else table.get_text(" ", strip=True)
            table.replace_with(f"\n{replacement}\n")

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
