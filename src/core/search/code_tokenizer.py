"""Code-aware tokenization for BM25 (E32).

Splits identifiers across camelCase / PascalCase / snake_case / kebab-case /
digit boundaries, keeps the raw identifier as a token (exact-match signal), and
optionally filters a small language-agnostic stopword set.

References (see experiments/e32_code_bm25/RESEARCH.md):
- ripvec-core `split_code_identifier` + Tantivy code analyzer
- pi-lens `splitIdentifier` / word-index
- trusty-search-core three-pass tokenizer
- Scout `tokenize_code`
"""

from __future__ import annotations

import re

__all__ = [
    "split_identifier",
    "tokenize_code",
    "CODE_STOPWORDS",
    "LANGUAGE_KEYWORDS",
]

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")

# Small, language-agnostic stopword set. Deliberately excludes meaningful code
# verbs (get/set/add/update) that are often part of an identifier.
CODE_STOPWORDS = frozenset(
    """
    the and or of to in is for on with as by at from that this it an be are
    was were will can if else while return class def function const let var
    async await pub impl use mod import public private protected static void
    int float double string bool boolean true false null none nil self super
    try catch except finally raise throw throws package interface struct enum
    type fn func method property namespace using include require new delete
    break continue switch case default do elif then end begin where select
    """.split()
)

# Common reserved words per language. Used only for stopword filtering; the
# tokenizer itself is language-agnostic.
LANGUAGE_KEYWORDS = {
    "python": "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self".split(),
    "javascript": "await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new return static super switch this throw try typeof var void while with yield async of get set".split(),
    "typescript": "abstract any as async await boolean break case catch class const constructor continue declare default delete do else enum export extends false finally for from function get if implements import in instanceof interface let module namespace never new null number object of package private protected public readonly require return set static string super switch symbol this throw true try type typeof undefined var void while with yield".split(),
    "rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while".split(),
    "go": "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil".split(),
    "java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null".split(),
    "csharp": "abstract as base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while async await var".split(),
    "ruby": "BEGIN END alias and begin break case class def defined? do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield require include extend".split(),
    "php": "abstract and array as break callable case catch class clone const continue declare default die do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile eval exit extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new or print private protected public readonly require require_once return static switch throw trait try unset use var while xor yield".split(),
    "kotlin": "as break class continue do else false for fun if in interface is null object package return super this throw true try typealias typeof val var when where while by catch constructor delegate dynamic field file finally get import init param property receiver set setparam".split(),
    "swift": "associatedtype class deinit enum extension fileprivate func import init inout internal let open operator private protocol public rethrows static struct subscript typealias var break case continue default defer do else fallthrough for guard if in repeat return switch where while as catch false is nil super self Self throw throws true try".split(),
    "c": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while".split(),
    "cpp": "alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq".split(),
    "scala": "abstract case catch class def do else extends false final finally for forSome if implicit import lazy match new null object override package private protected return sealed super this throw trait try true type val var while with yield".split(),
    "dart": "abstract as assert async await break case catch class const continue covariant default deferred do dynamic else enum export extends extension external factory false final finally for Function get hide if implements import in interface is late library mixin new null on operator part required rethrow return set show static super switch sync this throw true try typedef var void while with yield".split(),
}


def split_identifier(name: str) -> list[str]:
    """Split one identifier into lowercased sub-words.

    ``parseJsonConfig`` -> ``["parse", "json", "config"]``
    ``MAX_RETRY_2``      -> ``["max", "retry", "2"]``
    ``HTML5Parser``      -> ``["html5", "parser"]``
    """
    if not name:
        return []

    parts: list[str] = []
    for segment in re.split(r"[_\-\s]+", name):
        if not segment:
            continue
        chars = list(segment)
        n = len(chars)
        start = 0
        i = 0
        while i < n:
            if i > start:
                prev = chars[i - 1]
                cur = chars[i]
                lower_to_upper = (prev.islower() or prev.isdigit()) and cur.isupper()
                upper_run_to_lower = (
                    i >= 2
                    and prev.isupper()
                    and cur.islower()
                    and chars[i - 2].isupper()
                )
                digit_boundary = prev.isdigit() != cur.isdigit()
                if lower_to_upper or digit_boundary:
                    parts.append("".join(chars[start:i]).lower())
                    start = i
                elif upper_run_to_lower:
                    parts.append("".join(chars[start : i - 1]).lower())
                    start = i - 1
            i += 1
        if start < n:
            parts.append("".join(chars[start:n]).lower())
    return [p for p in parts if p]


def tokenize_code(
    text: str,
    *,
    language: str | None = None,
    stopwords: bool = True,
    keep_raw: bool = True,
) -> list[str]:
    """Tokenize code for BM25.

    Emits the raw lowercased identifier first (exact-match signal), then its
    sub-words. Deduplicates while preserving order.
    """
    if not text:
        return []

    stop = set(CODE_STOPWORDS)
    if language and language in LANGUAGE_KEYWORDS:
        stop.update(w.lower() for w in LANGUAGE_KEYWORDS[language])
    if not stopwords:
        stop = set()

    out: list[str] = []
    seen: set[str] = set()
    for raw in _IDENT_RE.findall(text):
        low = raw.lower()
        if keep_raw:
            if len(low) >= 2 and low not in stop and low not in seen:
                seen.add(low)
                out.append(low)
        for part in split_identifier(raw):
            if len(part) < 2 or part in stop or part in seen:
                continue
            seen.add(part)
            out.append(part)
    return out
