"""Tests for the Alteryx expression tokenizer."""

from __future__ import annotations

import pytest

from a2d.expressions.tokenizer import AlteryxTokenizer, Token, TokenizerError, TokenType


@pytest.fixture
def tokenizer() -> AlteryxTokenizer:
    return AlteryxTokenizer()


class TestFieldReferences:
    """Test tokenization of [FieldName] references."""

    def test_simple_field_ref(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Age]")
        assert tokens[0] == Token(TokenType.FIELD_REF, "Age", 0)

    def test_field_ref_with_spaces(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[First Name]")
        assert tokens[0] == Token(TokenType.FIELD_REF, "First Name", 0)

    def test_field_ref_with_underscores(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[order_total]")
        assert tokens[0] == Token(TokenType.FIELD_REF, "order_total", 0)


class TestRowReferences:
    """Test tokenization of [Row-1:FieldName] references."""

    def test_previous_row(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Row-1:Amount]")
        assert tokens[0].token_type == TokenType.ROW_REF
        assert tokens[0].value == "-1:Amount"

    def test_next_row(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Row+1:Amount]")
        assert tokens[0].token_type == TokenType.ROW_REF
        assert tokens[0].value == "+1:Amount"

    def test_row_ref_multiple_offset(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Row-3:Name]")
        assert tokens[0].token_type == TokenType.ROW_REF
        assert tokens[0].value == "-3:Name"


class TestStringLiterals:
    """Test tokenization of string literals."""

    def test_double_quoted_string(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize('"hello world"')
        assert tokens[0] == Token(TokenType.STRING, "hello world", 0)

    def test_single_quoted_string(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("'hello world'")
        assert tokens[0] == Token(TokenType.STRING, "hello world", 0)

    def test_escaped_quote_in_string(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize('"he said \\"hi\\"!"')
        assert tokens[0].token_type == TokenType.STRING
        assert tokens[0].value == 'he said "hi"!'

    def test_doubled_quote_escape(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize('"he said ""hi""!"')
        assert tokens[0].token_type == TokenType.STRING
        assert tokens[0].value == 'he said "hi"!'

    def test_unterminated_string_raises(self, tokenizer: AlteryxTokenizer) -> None:
        with pytest.raises(TokenizerError):
            tokenizer.tokenize('"unterminated')


class TestNumbers:
    """Test tokenization of numeric literals."""

    def test_integer(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("42")
        assert tokens[0] == Token(TokenType.NUMBER, "42", 0)

    def test_decimal(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("3.14")
        assert tokens[0] == Token(TokenType.NUMBER, "3.14", 0)

    def test_leading_dot(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize(".5")
        assert tokens[0] == Token(TokenType.NUMBER, ".5", 0)


class TestOperators:
    """Test tokenization of operators."""

    def test_arithmetic_operators(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("+ - * / %")
        ops = [t for t in tokens if t.token_type == TokenType.OPERATOR]
        assert [o.value for o in ops] == ["+", "-", "*", "/", "%"]


class TestComparisons:
    """Test tokenization of comparison operators."""

    def test_all_comparisons(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A] = [B]")
        cmp_tokens = [t for t in tokens if t.token_type == TokenType.COMPARISON]
        assert len(cmp_tokens) == 1
        assert cmp_tokens[0].value == "="

    def test_not_equal(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A] != [B]")
        cmp_tokens = [t for t in tokens if t.token_type == TokenType.COMPARISON]
        assert cmp_tokens[0].value == "!="

    def test_angle_bracket_not_equal(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A] <> [B]")
        cmp_tokens = [t for t in tokens if t.token_type == TokenType.COMPARISON]
        assert cmp_tokens[0].value == "!="

    def test_less_equal_greater_equal(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A] <= [B] >= [C]")
        cmp_tokens = [t for t in tokens if t.token_type == TokenType.COMPARISON]
        assert cmp_tokens[0].value == "<="
        assert cmp_tokens[1].value == ">="


class TestLogical:
    """Test tokenization of logical operators."""

    def test_and_or_not_words(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("AND OR NOT")
        logical = [t for t in tokens if t.token_type == TokenType.LOGICAL]
        assert [tok.value for tok in logical] == ["AND", "OR", "NOT"]

    def test_symbolic_logical(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("&& || !")
        logical = [t for t in tokens if t.token_type == TokenType.LOGICAL]
        assert [tok.value for tok in logical] == ["&&", "||", "!"]


class TestKeywords:
    """Test tokenization of keywords."""

    def test_if_then_else_endif(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("IF THEN ELSE ELSEIF ENDIF")
        kw = [t for t in tokens if t.token_type == TokenType.KEYWORD]
        assert [k.value for k in kw] == ["IF", "THEN", "ELSE", "ELSEIF", "ENDIF"]

    def test_null_true_false(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("NULL TRUE FALSE")
        kw = [t for t in tokens if t.token_type == TokenType.KEYWORD]
        assert [k.value for k in kw] == ["NULL", "TRUE", "FALSE"]

    def test_in_keyword(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[X] IN (1, 2)")
        kw = [t for t in tokens if t.token_type == TokenType.KEYWORD]
        assert kw[0].value == "IN"


class TestFunctions:
    """Test tokenization of function calls."""

    def test_function_name(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize('Contains([Name], "test")')
        assert tokens[0].token_type == TokenType.FUNCTION
        assert tokens[0].value == "Contains"

    def test_function_with_space_before_paren(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("ABS  ([Value])")
        assert tokens[0].token_type == TokenType.FUNCTION
        assert tokens[0].value == "ABS"

    def test_nested_functions(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("Trim(LowerCase([Name]))")
        funcs = [t for t in tokens if t.token_type == TokenType.FUNCTION]
        assert [f.value for f in funcs] == ["Trim", "LowerCase"]


class TestEOF:
    """Test that tokenizer always ends with EOF."""

    def test_empty_string(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("")
        assert len(tokens) == 1
        assert tokens[0].token_type == TokenType.EOF

    def test_eof_at_end(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A]")
        assert tokens[-1].token_type == TokenType.EOF


class TestCommentStripping:
    """Test that // comments are stripped before tokenization."""

    def test_trailing_comment(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Age] > 25 //check age limit")
        types = [t.token_type for t in tokens]
        assert types == [TokenType.FIELD_REF, TokenType.COMPARISON, TokenType.NUMBER, TokenType.EOF]

    def test_comment_does_not_affect_string(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize('"hello//world"')
        assert tokens[0].token_type == TokenType.STRING
        assert tokens[0].value == "hello//world"

    def test_comment_after_expression(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Cust#] = '8721' //and [Note#] = '123'")
        # Should only tokenize the part before //
        field_refs = [t for t in tokens if t.token_type == TokenType.FIELD_REF]
        assert len(field_refs) == 1
        assert field_refs[0].value == "Cust#"

    def test_no_comment(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[A] / [B]")
        # Single / is division, not a comment
        ops = [t for t in tokens if t.token_type == TokenType.OPERATOR]
        assert len(ops) == 1
        assert ops[0].value == "/"


class TestFullExpressions:
    """Test tokenization of complete expressions."""

    def test_comparison_expression(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Age] > 25")
        types = [t.token_type for t in tokens]
        assert types == [
            TokenType.FIELD_REF,
            TokenType.COMPARISON,
            TokenType.NUMBER,
            TokenType.EOF,
        ]

    def test_arithmetic_expression(self, tokenizer: AlteryxTokenizer) -> None:
        tokens = tokenizer.tokenize("[Price] * [Qty] + [Tax]")
        types = [t.token_type for t in tokens]
        assert types == [
            TokenType.FIELD_REF,
            TokenType.OPERATOR,
            TokenType.FIELD_REF,
            TokenType.OPERATOR,
            TokenType.FIELD_REF,
            TokenType.EOF,
        ]
