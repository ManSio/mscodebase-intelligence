"""Russian → English code-term synonyms for query expansion (E40).

The existing `_QUERY_SYNONYMS` map is English-only; Russian queries get no
expansion. This dictionary covers common Russian code/engineering terms and
their inflected forms, so a Russian NL query can also match English identifiers.

Curated, deterministic, no model. Keep entries code-specific; generic Russian
words are intentionally absent.
"""

from __future__ import annotations

__all__ = ["RU_EN", "RU_PHRASES", "expand_ru_variants"]

# Single-word forms -> English code terms.
RU_EN = {
    # cache
    "кэш": ["cache"], "кэша": ["cache"], "кэшу": ["cache"], "кэшем": ["cache"],
    "кэше": ["cache"], "кэши": ["cache"], "кэширование": ["cache", "caching"],
    "кэширования": ["cache", "caching"], "кэшировать": ["cache"],
    "кэшированный": ["cache"], "кэшированная": ["cache"],
    # database / data
    "база": ["database", "base"], "базы": ["database", "base"],
    "базе": ["database"], "базу": ["database"], "базой": ["database"],
    "данные": ["data"], "данных": ["data"], "данными": ["data"],
    "данным": ["data"], "дата": ["date"], "даты": ["date"],
    # error / exception
    "ошибка": ["error"], "ошибки": ["error"], "ошибку": ["error"],
    "ошибок": ["error"], "ошибками": ["error"], "ошибке": ["error"],
    "исключение": ["exception"], "исключения": ["exception"],
    "исключений": ["exception"], "сбой": ["failure", "error"],
    "сбоя": ["failure", "error"], "сбои": ["failure", "error"],
    # config / settings
    "конфиг": ["config"], "конфига": ["config"], "конфигурация": ["configuration"],
    "конфигурации": ["configuration"], "настройка": ["settings", "config"],
    "настройки": ["settings", "config"], "настроек": ["settings"],
    "настройке": ["settings"], "настройку": ["settings"],
    # search / find
    "поиск": ["search", "find"], "поиска": ["search"], "поиске": ["search"],
    "искать": ["search", "find"], "найти": ["find"], "находит": ["find"],
    "найден": ["find"], "поисковый": ["search"], "поисковая": ["search"],
    # index
    "индекс": ["index"], "индекса": ["index"], "индексы": ["index"],
    "индексов": ["index"], "индексация": ["index", "indexing"],
    "индексации": ["index", "indexing"], "индексировать": ["index"],
    "переиндексация": ["reindex"], "переиндексации": ["reindex"],
    # graph / nodes / edges
    "граф": ["graph"], "графа": ["graph"], "графе": ["graph"],
    "графы": ["graph"], "графов": ["graph"], "узел": ["node"],
    "узла": ["node"], "узлы": ["node"], "узлов": ["node"],
    "ребро": ["edge"], "ребра": ["edge"], "ребер": ["edge"],
    "рёбер": ["edge"], "связь": ["relation", "edge"], "связи": ["relation"],
    # vectors / embeddings
    "вектор": ["vector"], "вектора": ["vector"], "векторы": ["vector"],
    "векторов": ["vector"], "векторный": ["vector"], "векторная": ["vector"],
    "эмбеддинг": ["embedding"], "эмбеддинги": ["embedding"],
    "эмбеддингов": ["embedding"], "вложение": ["embedding"],
    "вложения": ["embedding"], "вложений": ["embedding"],
    "реранкер": ["reranker"], "реранкера": ["reranker"], "реранкинг": ["rerank"],
    "переранжирование": ["rerank"], "переранжирования": ["rerank"],
    # concurrency
    "поток": ["thread"], "потока": ["thread"], "потоки": ["thread"],
    "потоков": ["thread"], "очередь": ["queue"], "очереди": ["queue"],
    "очередью": ["queue"], "блокировка": ["lock"], "блокировки": ["lock"],
    "блокировку": ["lock"], "блокировок": ["lock"], "мьютекс": ["mutex"],
    "мьютекса": ["mutex"], "мьютексы": ["mutex"], "асинхронный": ["async"],
    "асинхронная": ["async"], "асинхронно": ["async"], "синхронный": ["sync"],
    # process / server / client
    "процесс": ["process"], "процесса": ["process"], "процессы": ["process"],
    "процессов": ["process"], "сервер": ["server"], "сервера": ["server"],
    "сервере": ["server"], "серверы": ["server"], "клиент": ["client"],
    "клиента": ["client"], "клиенты": ["client"], "клиентов": ["client"],
    "порт": ["port"], "порта": ["port"], "порту": ["port"],
    "хост": ["host"], "хоста": ["host"], "адрес": ["address"],
    "адреса": ["address"], "протокол": ["protocol"], "протокола": ["protocol"],
    "соединение": ["connection"], "соединения": ["connection"],
    "сеть": ["network"], "сети": ["network"], "сетевой": ["network"],
    # files / paths / modules
    "файл": ["file"], "файла": ["file"], "файлы": ["file"], "файлов": ["file"],
    "путь": ["path"], "пути": ["path"], "путям": ["path"], "путей": ["path"],
    "модуль": ["module"], "модуля": ["module"], "модули": ["module"],
    "модулей": ["module"], "пакет": ["package"], "пакета": ["package"],
    "класс": ["class"], "класса": ["class"], "классы": ["class"],
    "классов": ["class"], "функция": ["function"], "функции": ["function"],
    "функцию": ["function"], "функций": ["function"], "метод": ["method"],
    "метода": ["method"], "методы": ["method"], "методов": ["method"],
    "параметр": ["parameter"], "параметра": ["parameter"],
    "параметры": ["parameter"], "параметров": ["parameter"],
    "аргумент": ["argument"], "аргумента": ["argument"],
    "аргументы": ["argument"], "возврат": ["return"], "возвращает": ["return"],
    "вернуть": ["return"], "возвращаемое": ["return"],
    # strings / numbers / collections
    "строка": ["string", "line"], "строки": ["string", "line"],
    "строку": ["string", "line"], "строк": ["string", "line"],
    "число": ["number", "int"], "числа": ["number"], "чисел": ["number"],
    "список": ["list"], "списка": ["list"], "списки": ["list"],
    "словарь": ["dict", "dictionary"], "словаря": ["dict"],
    "словари": ["dict"], "множество": ["set"], "множества": ["set"],
    "ключ": ["key"], "ключа": ["key"], "ключи": ["key"], "ключей": ["key"],
    "значение": ["value"], "значения": ["value"], "значений": ["value"],
    "тип": ["type"], "типа": ["type"], "типы": ["type"], "типов": ["type"],
    "объект": ["object"], "объекта": ["object"], "объекты": ["object"],
    "интерфейс": ["interface"], "интерфейса": ["interface"],
    # actions
    "удаление": ["delete", "remove"], "удалить": ["delete", "remove"],
    "удаляет": ["delete", "remove"], "создание": ["create"],
    "создать": ["create"], "создает": ["create"], "обновление": ["update"],
    "обновить": ["update"], "обновляет": ["update"], "чтение": ["read"],
    "читать": ["read"], "читает": ["read"], "запись": ["write"],
    "записать": ["write"], "записывает": ["write"], "загрузка": ["load"],
    "загрузить": ["load"], "сохранение": ["save"], "сохранить": ["save"],
    "запуск": ["start", "run"], "запустить": ["start", "run"],
    "остановка": ["stop"], "остановить": ["stop"], "ожидание": ["wait"],
    "ждать": ["wait"], "повтор": ["retry"], "повтора": ["retry"],
    "повторный": ["retry"], "повторно": ["retry"], "проверка": ["check", "validate"],
    "проверки": ["check"], "проверить": ["check", "validate"],
    "валидация": ["validation"], "валидации": ["validation"],
    "парсер": ["parser", "parse"], "парсера": ["parser"],
    "парсинг": ["parse"], "парсить": ["parse"], "токен": ["token"],
    "токена": ["token"], "токены": ["token"], "токенизация": ["tokenize"],
    "реализация": ["implementation", "implement"], "реализации": ["implementation"],
    "реализовать": ["implement"], "вызов": ["call"], "вызова": ["call"],
    "вызовы": ["call"], "вызывать": ["call"], "вызывается": ["caller"],
    "ссылка": ["reference", "link"], "ссылки": ["reference"],
    "зависимость": ["dependency"], "зависимости": ["dependency"],
    "импорт": ["import"], "импорта": ["import"], "импортировать": ["import"],
    "экспорт": ["export"], "экспорта": ["export"],
    # memory / model / metrics
    "память": ["memory"], "памяти": ["memory"], "модель": ["model"],
    "модели": ["model"], "моделей": ["model"], "размер": ["size"],
    "размера": ["size"], "размеры": ["size"], "длина": ["length"],
    "длины": ["length"], "скорость": ["speed"], "скорости": ["speed"],
    "время": ["time"], "времени": ["time"], "версия": ["version"],
    "версии": ["version"], "ветка": ["branch"], "ветки": ["branch"],
    "коммит": ["commit"], "коммита": ["commit"], "репозиторий": ["repository"],
    "репозитория": ["repository"], "проект": ["project"], "проекта": ["project"],
    "система": ["system"], "системы": ["system"], "компонент": ["component"],
    "компонента": ["component"], "слой": ["layer"], "слоя": ["layer"],
    "слои": ["layer"], "архитектура": ["architecture"],
    "архитектуры": ["architecture"],
    # misc
    "логи": ["log", "logs"], "лог": ["log"], "логов": ["log"],
    "тест": ["test"], "теста": ["test"], "тесты": ["test"],
    "тестов": ["test"], "тестирование": ["test", "testing"],
    "диск": ["disk"], "диска": ["disk"], "таймаут": ["timeout"],
    "таймаута": ["timeout"], "таймауты": ["timeout"],
    "конкурентность": ["concurrency"], "конкурентный": ["concurrent"],
    "приоритет": ["priority"], "буфер": ["buffer"], "буфера": ["buffer"],
    "семафор": ["semaphore"], "событие": ["event"], "события": ["event"],
    "обработчик": ["handler"], "обработчика": ["handler"],
    "плагин": ["plugin"], "плагина": ["plugin"], "расширение": ["extension"],
    "расширения": ["extension"], "хук": ["hook"], "хука": ["hook"],
}

# Multi-word phrases -> single English term.
RU_PHRASES = {
    "база данных": "database",
    "базы данных": "database",
    "базе данных": "database",
    "обработка ошибок": "error handling",
    "обработки ошибок": "error handling",
    "поиск по коду": "code search",
    "поиска по коду": "code search",
    "векторный поиск": "vector search",
    "векторного поиска": "vector search",
    "полнотекстовый поиск": "full text search",
    "полнотекстового поиска": "full text search",
    "граф вызовов": "call graph",
    "графа вызовов": "call graph",
    "утечка памяти": "memory leak",
    "утечки памяти": "memory leak",
    "состояние гонки": "race condition",
    "состояния гонки": "race condition",
    "блокировка потока": "thread lock",
    "блокировки потока": "thread lock",
}


def expand_ru_variants(
    query: str,
    variants: list[str],
    max_expansions: int = 4,
) -> list[str]:
    """Append variants with Russian terms replaced by English code terms."""
    if not query.strip():
        return variants

    q_low = query.lower()
    # Phrase-level replacements first.
    for ru, en in RU_PHRASES.items():
        if ru in q_low:
            variant = query.replace(ru, en)
            if variant not in variants:
                variants.append(variant)
            if len(variants) >= max_expansions:
                return variants

    words = query.split()
    for i, raw in enumerate(words):
        key = raw.strip(".,!?;:()[]{}\"'«»").lower()
        syns = RU_EN.get(key)
        if not syns:
            continue
        for syn in syns:
            new_words = list(words)
            new_words[i] = syn
            variant = " ".join(new_words)
            if variant not in variants:
                variants.append(variant)
            if len(variants) >= max_expansions:
                return variants
    return variants
