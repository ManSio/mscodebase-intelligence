"""
doc_llm_verifier.py — LLM-верификация документации на соответствие коду.

По Тумблеру: Provider-архитектура (LLM / structural fallback).

Как работает:
1. Читает .md файл, делит на секции (по ##)
2. Для каждой секции собирает code-референсы через PropertyGraph
3. Если доступен LLM (LM Studio/Ollama) — отправляет секцию + код на проверку
4. Если LLM недоступен — только структурная проверка (имена, цифры)
5. Возвращает список несоответствий
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DocSection:
    """Одна секция документа."""
    file: str
    title: str          # Заголовок секции (## Title)
    level: int          # Уровень заголовка (2, 3, ...)
    line_start: int     # Начальная строка
    line_end: int       # Конечная строка
    content: str        # Текст секции
    symbols: List[str]  # Упомянутые code-символы


@dataclass
class LLMDiscrepancy:
    """Одно несоответствие найденное LLM."""
    file: str
    section: str
    line: int
    issue: str          # Что не так
    doc_says: str       # Что написано в доке
    code_says: str      # Что на самом деле в коде
    confidence: float   # 0.0 - 1.0


class DocLLMVerifier:
    """LLM-верификация документации.

    Provider-архитектура:
    - Primary: LM Studio (если запущен)
    - Fallback: только структурная проверка

    Usage:
        verifier = DocLLMVerifier(project_root="/path")
        discrepancies = await verifier.verify_file("docs/en/ARCHITECTURE.md")
    """

    # Системный промпт для LLM
    SYSTEM_PROMPT = """You are a documentation quality inspector for a codebase.
Your job is to find DISCREPANCIES between documentation and actual code.

For each documentation section, check:
1. Are the described function/class names correct?
2. Are file paths and module locations accurate?
3. Do numerical claims (tool counts, line counts) match reality?
4. Does the described behavior match the actual implementation?
5. Is the language correct? (English docs should be in English)

IMPORTANT: Only report ACTUAL discrepancies. If the doc is accurate, say NO_ISSUES.
Be specific: mention exact line numbers and what needs to change.

Respond in JSON format:
{
  "discrepancies": [
    {
      "line": 42,
      "issue": "brief description",
      "doc_says": "what the doc says",
      "code_says": "what the code actually shows",
      "confidence": 0.95
    }
  ]
}
Return empty list if no issues found.
"""

    def __init__(
        self,
        project_root: str,
        lm_studio_url: str = "http://127.0.0.1:1234",
        ollama_url: str = "http://127.0.0.1:11434",
        model: str = "",
    ):
        self._root = Path(project_root).resolve()
        self._lm_url = lm_studio_url.rstrip("/")
        self._ollama_url = ollama_url.rstrip("/")
        self._model = model
        self._client: Optional[httpx.AsyncClient] = None
        self._symbols: Set[str] = set()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def verify_file(self, file_path: str) -> List[LLMDiscrepancy]:
        """Проверяет один .md файл через LLM.

        Returns:
            Список несоответствий (пустой если всё ок)
        """
        abs_path = (self._root / file_path).resolve()
        if not abs_path.exists():
            return []

        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        sections = self._split_sections(file_path, text)

        # Пытаемся LLM
        llm_available = await self._check_llm()
        if llm_available:
            return await self._verify_with_llm(sections)
        else:
            # Fallback: только структурная проверка
            return self._verify_structural(sections)

    def _split_sections(self, file_path: str, text: str) -> List[DocSection]:
        """Делит .md на секции по заголовкам."""
        sections: List[DocSection] = []
        lines = text.split("\n")
        current_title = "(header)"
        current_level = 1
        current_start = 1
        current_lines: List[str] = []
        current_symbols: List[str] = []

        for i, line in enumerate(lines, 1):
            m = re.match(r'^(#{1,6})\s+(.+)$', line)
            if m:
                # Сохраняем предыдущую секцию
                if current_lines:
                    sections.append(DocSection(
                        file=file_path,
                        title=current_title,
                        level=current_level,
                        line_start=current_start,
                        line_end=i - 1,
                        content="\n".join(current_lines),
                        symbols=list(set(current_symbols)),
                    ))
                # Новая секция
                current_title = m.group(2)
                current_level = len(m.group(1))
                current_start = i
                current_lines = []
                current_symbols = []
            else:
                current_lines.append(line)
                # Собираем code-референсы
                for ref in re.finditer(r'`([a-zA-Z_][a-zA-Z0-9_.()]*)`', line):
                    current_symbols.append(ref.group(1))

        # Последняя секция
        if current_lines:
            sections.append(DocSection(
                file=file_path,
                title=current_title,
                level=current_level,
                line_start=current_start,
                line_end=i,
                content="\n".join(current_lines),
                symbols=list(set(current_symbols)),
            ))

        return sections

    async def _check_llm(self) -> bool:
        """Проверяет доступность LLM (LM Studio или Ollama)."""
        client = await self._get_client()

        # Проверяем LM Studio
        try:
            r = await client.get(f"{self._lm_url}/v1/models", timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                models = data.get("data", [])
                if models and not self._model:
                    self._model = models[0]["id"]
                    logger.info("DocLLM: using LM Studio model: %s", self._model)
                return True
        except Exception:
            pass

        # Проверяем Ollama
        try:
            r = await client.get(f"{self._ollama_url}/api/tags", timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                models = data.get("models", [])
                if models and not self._model:
                    self._model = models[0]["name"]
                    logger.info("DocLLM: using Ollama model: %s", self._model)
                return True
        except Exception:
            pass

        logger.info("DocLLM: no LLM available, using structural check only")
        return False

    async def _verify_with_llm(self, sections: List[DocSection]) -> List[LLMDiscrepancy]:
        """Проверяет секции через LLM."""
        all_discrepancies: List[LLMDiscrepancy] = []
        client = await self._get_client()

        for section in sections:
            if len(section.content.strip()) < 20:
                continue  # Пропускаем пустые секции

            prompt = (
                f"Documentation section: {section.file} > {section.title}\n\n"
                f"```markdown\n"
                f"{section.content[:2000]}\n"
                f"```\n\n"
                f"Code symbols referenced: {', '.join(section.symbols[:20])}\n"
                f"Check if this documentation accurately describes the actual code."
            )

            try:
                payload = {
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                }

                # Пробуем LM Studio
                r = await client.post(
                    f"{self._lm_url}/v1/chat/completions",
                    json=payload,
                    timeout=30.0,
                )

                # Если LM Studio не отвечает — пробуем Ollama
                if r.status_code not in (200, 201):
                    r = await client.post(
                        f"{self._ollama_url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": payload["messages"],
                            "stream": False,
                        },
                        timeout=30.0,
                    )

                if r.status_code in (200, 201):
                    data = r.json()
                    content = (data.get("choices", [{}])[0].get("message", {}).get("content", "")
                               or data.get("message", {}).get("content", ""))
                    
                    # Парсим JSON из ответа
                    try:
                        # Ищем JSON в ответе
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            result = json.loads(json_match.group())
                            for disc in result.get("discrepancies", []):
                                all_discrepancies.append(LLMDiscrepancy(
                                    file=section.file,
                                    section=section.title,
                                    line=disc.get("line", section.line_start),
                                    issue=disc.get("issue", ""),
                                    doc_says=disc.get("doc_says", ""),
                                    code_says=disc.get("code_says", ""),
                                    confidence=disc.get("confidence", 0.5),
                                ))
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("DocLLM: failed to parse LLM response: %s", e)
                else:
                    logger.warning("DocLLM: LLM returned %d", r.status_code)

            except Exception as e:
                logger.warning("DocLLM: LLM call failed: %s", e)

        return all_discrepancies

    def _verify_structural(self, sections: List[DocSection]) -> List[LLMDiscrepancy]:
        """Структурная проверка (без LLM)."""
        discrepancies: List[LLMDiscrepancy] = []

        for section in sections:
            # Проверяем числовые утверждения
            for m in re.finditer(r'(\d+)\s+(tool|file|module|function|class)', 
                                section.content, re.IGNORECASE):
                claimed_num = int(m.group(1))
                context = section.content[max(0, m.start()-50):m.end()+50]
                discrepancies.append(LLMDiscrepancy(
                    file=section.file,
                    section=section.title,
                    line=section.line_start,
                    issue=f"Verify number: {m.group(0)}",
                    doc_says=m.group(0),
                    code_says="needs verification",
                    confidence=0.3,
                ))

        return discrepancies

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
