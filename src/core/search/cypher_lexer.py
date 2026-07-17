"""Cypher query engine — компонент для подмножества openCypher."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List

# ════════════════════════════════════════════════════════════
# Lexer
# ════════════════════════════════════════════════════════════

class TokenType(Enum):
    KEYWORD = auto()
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    PUNCTUATION = auto()
    OPERATOR = auto()
    LABEL = auto()       # :Label
    REL_TYPE = auto()    # :TYPE or :TYPE*min..max
    VARIABLE = auto()    # n, m, f


KEYWORDS = {
    "MATCH", "OPTIONAL", "WHERE", "RETURN", "DISTINCT",
    "ORDER", "BY", "ASC", "DESC", "LIMIT", "SKIP",
    "AND", "OR", "XOR", "NOT", "IN", "CONTAINS",
    "STARTS", "ENDS", "WITH", "IS", "NULL", "TRUE", "FALSE",
    "AS", "COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "EXISTS",
}

DIRECTION_LEFT = "<-"
DIRECTION_RIGHT = "->"
DIRECTION_NONE = "--"  # undirected


@dataclass
class Token:
    type: TokenType
    value: str
    pos: int  # позиция в исходном запросе


class CypherLexer:
    """Лексер для подмножества openCypher."""

    def __init__(self, query: str):
        self._query = query
        self._pos = 0
        self._tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        """Разбивает строку запроса на токены."""
        tokens: List[Token] = []
        i = 0
        q = self._query

        while i < len(q):
            ch = q[i]

            # Пропускаем пробелы
            if ch in " \t\n\r":
                i += 1
                continue

            # Комментарии //
            if ch == "/" and i + 1 < len(q) and q[i + 1] == "/":
                end = q.find("\n", i)
                if end == -1:
                    break
                i = end + 1
                continue

            # Строки в кавычках
            if ch in "\"'":
                end = ch
                j = i + 1
                while j < len(q) and q[j] != end:
                    if q[j] == "\\":
                        j += 1
                    j += 1
                if j >= len(q):
                    raise SyntaxError(f"Unterminated string at pos {i}")
                tokens.append(Token(TokenType.STRING, q[i + 1:j], i))
                i = j + 1
                continue

            # Числа
            if ch.isdigit() or (ch == "." and i + 1 < len(q) and q[i + 1].isdigit()):
                j = i
                while j < len(q) and (q[j].isdigit() or q[j] in "."):
                    j += 1
                tokens.append(Token(TokenType.NUMBER, q[i:j], i))
                i = j
                continue

            # Идентификаторы, ключевые слова, метки
            if ch.isalpha() or ch == "_" or ch == "`":
                if ch == "`":
                    # Backtick-escaped identifier
                    j = q.find("`", i + 1)
                    if j == -1:
                        raise SyntaxError(f"Unterminated backtick at pos {i}")
                    tokens.append(Token(TokenType.IDENTIFIER, q[i + 1:j], i))
                    i = j + 1
                    continue

                j = i
                while j < len(q) and (q[j].isalnum() or q[j] == "_"):
                    j += 1
                word = q[i:j]
                upper = word.upper()

                if upper in KEYWORDS:
                    tt = TokenType.KEYWORD
                elif word[0].isupper() and ":" not in word:
                    tt = TokenType.LABEL
                else:
                    tt = TokenType.IDENTIFIER

                tokens.append(Token(tt, word, i))
                i = j
                continue

            # Операторы сравнения (двухсимвольные)
            if i + 1 < len(q) and q[i:i + 2] in (">=", "<=", "<>", "!=", "=~"):
                tokens.append(Token(TokenType.OPERATOR, q[i:i + 2], i))
                i += 2
                continue

            # Стрелки направлений
            if i + 2 < len(q) and q[i:i + 2] == "<-":
                tokens.append(Token(TokenType.PUNCTUATION, "<-", i))
                i += 2
                continue
            if i + 1 < len(q) and q[i:i + 2] == "->":
                tokens.append(Token(TokenType.PUNCTUATION, "->", i))
                i += 2
                continue
            if i + 1 < len(q) and q[i:i + 2] == "--":
                tokens.append(Token(TokenType.PUNCTUATION, "--", i))
                i += 2
                continue

            # Односимвольные операторы
            if ch in "=<>!+-*/%":
                tokens.append(Token(TokenType.OPERATOR, ch, i))
                i += 1
                continue

            # Скобки и пунктуация
            if ch in "()[]{}.,*":
                tokens.append(Token(TokenType.PUNCTUATION, ch, i))
                i += 1
                continue

            # Метка :Label или :TYPE или :TYPE*min..max
            if ch == ":":
                j = i + 1
                while j < len(q) and (q[j].isalnum() or q[j] in "_"):
                    j += 1

                # Проверяем на variable-length path
                label = q[i + 1:j]
                rest = q[j:j + 10]  # смотрим вперед на *min..max

                if rest.startswith("*"):
                    # :TYPE*min..max или :TYPE*
                    k = j + 1
                    while k < len(q) and (q[k].isdigit() or q[k] in ".."):
                        k += 1
                    path_range = q[j:k]  # *1..3 или *
                    tokens.append(Token(TokenType.REL_TYPE, f"{label}{path_range}", i))
                    i = k
                else:
                    tokens.append(Token(TokenType.LABEL, label if label else "", i))
                    i = j
                continue

            # Неизвестный символ
            raise SyntaxError(f"Unexpected character '{ch}' at pos {i}")

        self._tokens = tokens
        return tokens
