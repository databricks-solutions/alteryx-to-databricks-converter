"""Alteryx expression tokenizer.

Converts Alteryx expression strings into a stream of tokens for parsing.
Handles field references [FieldName], row references [Row-1:Field],
string literals, numbers, operators, comparisons, logical operators,
keywords, function calls, and identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from a2d.expressions.errors import BaseTranslationError


class TokenType(Enum):
    """Token types for Alteryx expressions."""

    FIELD_REF = auto()
    ROW_REF = auto()
    STRING = auto()
    NUMBER = auto()
    OPERATOR = auto()
    COMPARISON = auto()
    LOGICAL = auto()
    KEYWORD = auto()
    FUNCTION = auto()
    IDENTIFIER = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    EOF = auto()


@dataclass
class Token:
    """A single token from an Alteryx expression."""

    token_type: TokenType
    value: str
    position: int


KEYWORDS = {"IF", "THEN", "ELSE", "ELSEIF", "ENDIF", "NULL", "TRUE", "FALSE", "IN"}
LOGICAL_WORDS = {"AND", "OR", "NOT"}
_CONTROL_KEYWORDS = frozenset(KEYWORDS - {"NULL", "TRUE", "FALSE"})

# Row reference pattern: [Row-1:FieldName] or [Row+1:FieldName]
_ROW_REF_PATTERN = re.compile(r"\[Row([+-]\d+):([^\]]+)\]", re.IGNORECASE)


class TokenizerError(BaseTranslationError):
    """Error raised when the tokenizer encounters invalid input."""

    def __init__(self, message: str, position: int):
        super().__init__(f"Position {position}: {message}")
        self.position = position


class AlteryxTokenizer:
    """Tokenize Alteryx expression strings."""

    @staticmethod
    def _strip_comments(expression: str) -> str:
        """Remove ``//``-to-EOL comments that are outside string literals."""
        result: list[str] = []
        i = 0
        length = len(expression)
        while i < length:
            ch = expression[i]
            # Skip over string literals
            if ch in ('"', "'"):
                quote = ch
                result.append(ch)
                i += 1
                while i < length:
                    c = expression[i]
                    if c == "\\" and i + 1 < length:
                        result.append(c)
                        result.append(expression[i + 1])
                        i += 2
                        continue
                    result.append(c)
                    if c == quote:
                        # Check for doubled quotes
                        if i + 1 < length and expression[i + 1] == quote:
                            result.append(expression[i + 1])
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                continue
            # Detect // comment
            if ch == "/" and i + 1 < length and expression[i + 1] == "/":
                # Skip to end of line
                while i < length and expression[i] != "\n":
                    i += 1
                continue
            result.append(ch)
            i += 1
        return "".join(result)

    def tokenize(self, expression: str) -> list[Token]:
        """Tokenize an Alteryx expression into a list of tokens.

        Args:
            expression: The Alteryx expression string to tokenize.

        Returns:
            A list of Token objects, ending with an EOF token.

        Raises:
            TokenizerError: If the expression contains invalid syntax.
        """
        expression = self._strip_comments(expression)
        tokens: list[Token] = []
        pos = 0
        length = len(expression)

        while pos < length:
            # Skip whitespace
            if expression[pos].isspace():
                pos += 1
                continue

            # String literals (double or single quoted)
            if expression[pos] in ('"', "'"):
                token, pos = self._read_string(expression, pos)
                tokens.append(token)
                continue

            # Bracket expressions: field refs or row refs
            if expression[pos] == "[":
                token, pos = self._read_bracket(expression, pos)
                tokens.append(token)
                continue

            # Numbers
            if expression[pos].isdigit() or (
                expression[pos] == "." and pos + 1 < length and expression[pos + 1].isdigit()
            ):
                token, pos = self._read_number(expression, pos)
                tokens.append(token)
                continue

            # Two-character operators / comparisons
            if pos + 1 < length:
                two_char = expression[pos : pos + 2]
                if two_char in ("<=", ">=", "!=", "<>", "&&", "||"):
                    if two_char in ("&&", "||"):
                        tokens.append(Token(TokenType.LOGICAL, two_char, pos))
                    elif two_char == "<>":
                        tokens.append(Token(TokenType.COMPARISON, "!=", pos))
                    else:
                        tokens.append(Token(TokenType.COMPARISON, two_char, pos))
                    pos += 2
                    continue

            # Single-character operators and comparisons
            ch = expression[pos]
            if ch in ("+", "-", "*", "/", "%"):
                tokens.append(Token(TokenType.OPERATOR, ch, pos))
                pos += 1
                continue

            if ch == "=":
                tokens.append(Token(TokenType.COMPARISON, "=", pos))
                pos += 1
                continue

            if ch in ("<", ">"):
                tokens.append(Token(TokenType.COMPARISON, ch, pos))
                pos += 1
                continue

            if ch == "!":
                tokens.append(Token(TokenType.LOGICAL, "!", pos))
                pos += 1
                continue

            if ch == "(":
                tokens.append(Token(TokenType.LPAREN, "(", pos))
                pos += 1
                continue

            if ch == ")":
                tokens.append(Token(TokenType.RPAREN, ")", pos))
                pos += 1
                continue

            if ch == ",":
                tokens.append(Token(TokenType.COMMA, ",", pos))
                pos += 1
                continue

            # Identifiers, keywords, logical words, and function names
            if ch.isalpha() or ch == "_":
                token, pos = self._read_identifier(expression, pos)
                tokens.append(token)
                continue

            raise TokenizerError(f"Unexpected character: {ch!r}", pos)

        tokens.append(Token(TokenType.EOF, "", pos))
        return tokens

    def _read_string(self, expr: str, pos: int) -> tuple[Token, int]:
        """Read a string literal (single or double quoted)."""
        quote = expr[pos]
        start = pos
        pos += 1
        chars: list[str] = []

        while pos < len(expr):
            ch = expr[pos]
            if ch == "\\":
                # Escaped character
                if pos + 1 < len(expr):
                    pos += 1
                    escape_ch = expr[pos]
                    if escape_ch == "n":
                        chars.append("\n")
                    elif escape_ch == "t":
                        chars.append("\t")
                    elif escape_ch == "\\":
                        chars.append("\\")
                    elif escape_ch == quote:
                        chars.append(quote)
                    else:
                        chars.append("\\")
                        chars.append(escape_ch)
                    pos += 1
                else:
                    raise TokenizerError("Unexpected end of string after escape", pos)
            elif ch == quote:
                # Check for doubled quotes (alternative escape in Alteryx)
                if pos + 1 < len(expr) and expr[pos + 1] == quote:
                    chars.append(quote)
                    pos += 2
                else:
                    pos += 1
                    return Token(TokenType.STRING, "".join(chars), start), pos
            else:
                chars.append(ch)
                pos += 1

        raise TokenizerError("Unterminated string literal", start)

    def _read_bracket(self, expr: str, pos: int) -> tuple[Token, int]:
        """Read a bracket expression: [FieldName] or [Row-1:FieldName]."""
        start = pos

        # Find the closing bracket
        end = expr.find("]", pos + 1)
        if end == -1:
            raise TokenizerError("Unterminated bracket expression", start)

        content = expr[pos + 1 : end]
        full = expr[pos : end + 1]

        # Check for row reference pattern
        row_match = _ROW_REF_PATTERN.match(full)
        if row_match:
            # Store as "offset:fieldname"
            offset = row_match.group(1)
            field = row_match.group(2).strip()
            return Token(TokenType.ROW_REF, f"{offset}:{field}", start), end + 1

        # Regular field reference
        return Token(TokenType.FIELD_REF, content, start), end + 1

    def _read_number(self, expr: str, pos: int) -> tuple[Token, int]:
        """Read a numeric literal (integer or decimal)."""
        start = pos
        has_dot = False

        while pos < len(expr):
            ch = expr[pos]
            if ch.isdigit():
                pos += 1
            elif ch == "." and not has_dot:
                has_dot = True
                pos += 1
            else:
                break

        return Token(TokenType.NUMBER, expr[start:pos], start), pos

    def _read_identifier(self, expr: str, pos: int) -> tuple[Token, int]:
        """Read an identifier, keyword, logical word, or function name."""
        start = pos

        while pos < len(expr) and (expr[pos].isalnum() or expr[pos] == "_"):
            pos += 1

        word = expr[start:pos]
        upper = word.upper()

        # Look ahead past whitespace for '(' to detect function calls
        peek = pos
        while peek < len(expr) and expr[peek].isspace():
            peek += 1

        if peek < len(expr) and expr[peek] == "(":
            # It's a function call unless it's a control-flow keyword (IF/THEN/ELSE/etc.).
            # NULL/TRUE/FALSE followed by '(' should be treated as function calls so that
            # Null() (which maps to F.lit(None)) parses correctly.
            if upper not in _CONTROL_KEYWORDS and upper not in LOGICAL_WORDS:
                return Token(TokenType.FUNCTION, word, start), pos

        if upper in LOGICAL_WORDS:
            return Token(TokenType.LOGICAL, upper, start), pos

        if upper in KEYWORDS:
            return Token(TokenType.KEYWORD, upper, start), pos

        return Token(TokenType.IDENTIFIER, word, start), pos
