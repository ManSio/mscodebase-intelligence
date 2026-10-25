from src.core.search.code_tokenizer import split_identifier, tokenize_code


def test_split_identifier_cases():
    assert split_identifier("parseJsonConfig") == ["parse", "json", "config"]
    assert split_identifier("my_func_name") == ["my", "func", "name"]
    assert split_identifier("HTML5Parser") == ["html", "5", "parser"]
    assert split_identifier("MAX_RETRY_2") == ["max", "retry", "2"]
    assert split_identifier("parser") == ["parser"]


def test_tokenize_code_keeps_raw_and_subwords():
    toks = tokenize_code("authenticateUser", stopwords=False)
    assert toks[0] == "authenticateuser"
    assert "authenticate" in toks and "user" in toks


def test_tokenize_code_stopwords():
    toks = tokenize_code("the function parseJsonConfig", stopwords=True)
    assert "the" not in toks
    assert "function" not in toks
    assert "parse" in toks and "json" in toks and "config" in toks
