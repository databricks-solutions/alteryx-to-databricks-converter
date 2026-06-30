"""Recursive descent parser for Alteryx expressions.

Parses a tokenized Alteryx expression into an AST (Abstract Syntax Tree).

Operator precedence (lowest to highest):
  1. OR
  2. AND
  3. NOT
  4. Comparisons: =, !=, <, >, <=, >=
  5. Addition, subtraction: +, -
  6. Multiplication, division, modulo: *, /, %
  7. Unary: -, NOT
  8. Primary: literals, field refs, function calls, parenthesized exprs, IF

Also handles:
  - IF / THEN / ELSEIF / ELSE / ENDIF blocks
  - IN expressions: value IN (item1, item2, ...)
  - Function calls with variable arguments
"""

from __future__ import annotations

from a2d.expressions.ast import (
    BinaryOp,
    ComparisonOp,
    Expr,
    FieldRef,
    FunctionCall,
    IfExpr,
    InExpr,
    Literal,
    LogicalOp,
    NotOp,
    RowRef,
    UnaryOp,
)
from a2d.expressions.errors import BaseTranslationError
from a2d.expressions.tokenizer import AlteryxTokenizer, Token, TokenType


class ParserError(BaseTranslationError):
    """Error raised when the parser encounters invalid syntax.

    Inherits from ``BaseTranslationError`` so that generators' catch-all
    blocks for expression failures handle parse errors gracefully.
    """

    def __init__(self, message: str, token: Token | None = None):
        if token is not None:
            super().__init__(f"Position {token.position}: {message} (got {token.token_type.name} {token.value!r})")
        else:
            super().__init__(message)
        self.token = token


class ExpressionParser:
    """Recursive descent parser for Alteryx expressions.

    Usage::

        parser = ExpressionParser()
        ast = parser.parse('[Price] * [Quantity]')
    """

    def __init__(self) -> None:
        self._tokens: list[Token] = []
        self._pos: int = 0

    # -- Public API ----------------------------------------------------------

    def parse(self, expression: str) -> Expr:
        """Parse an Alteryx expression string into an AST.

        Args:
            expression: The raw Alteryx expression string.

        Returns:
            The root Expr node of the AST.

        Raises:
            ParserError: If the expression has invalid syntax.
        """
        self._tokens = AlteryxTokenizer().tokenize(expression)
        self._pos = 0
        result = self._parse_expression()

        # Make sure we consumed all tokens (except EOF)
        if self._current().token_type != TokenType.EOF:
            raise ParserError("Unexpected token after expression", self._current())

        return result

    # -- Token helpers -------------------------------------------------------

    def _current(self) -> Token:
        """Return the current token."""
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        # Should not happen since we always have EOF
        return Token(TokenType.EOF, "", -1)

    def _peek(self) -> Token:
        """Return the current token without consuming it (alias for _current)."""
        return self._current()

    def _advance(self) -> Token:
        """Consume and return the current token, advancing position."""
        token = self._current()
        self._pos += 1
        return token

    def _expect(self, token_type: TokenType, value: str | None = None) -> Token:
        """Consume a token of the expected type, raising on mismatch."""
        token = self._current()
        if token.token_type != token_type:
            expected = f"{token_type.name}"
            if value:
                expected += f" {value!r}"
            raise ParserError(f"Expected {expected}", token)
        if value is not None and token.value.upper() != value.upper():
            raise ParserError(f"Expected {value!r}", token)
        return self._advance()

    def _match_keyword(self, keyword: str) -> bool:
        """Check if the current token is a specific keyword."""
        token = self._current()
        return token.token_type == TokenType.KEYWORD and token.value.upper() == keyword.upper()

    # -- Precedence-climbing grammar -----------------------------------------

    def _parse_expression(self) -> Expr:
        """Entry point: parse a full expression."""
        return self._parse_or()

    def _parse_or(self) -> Expr:
        """Parse OR expressions (lowest precedence binary)."""
        left = self._parse_and()

        while self._current().token_type == TokenType.LOGICAL and self._current().value.upper() in ("OR", "||"):
            self._advance()
            right = self._parse_and()
            left = LogicalOp(left=left, operator="OR", right=right)

        return left

    def _parse_and(self) -> Expr:
        """Parse AND expressions."""
        left = self._parse_not()

        while self._current().token_type == TokenType.LOGICAL and self._current().value.upper() in ("AND", "&&"):
            self._advance()
            right = self._parse_not()
            left = LogicalOp(left=left, operator="AND", right=right)

        return left

    def _parse_not(self) -> Expr:
        """Parse NOT / ! prefix."""
        if self._current().token_type == TokenType.LOGICAL and self._current().value.upper() in ("NOT", "!"):
            self._advance()
            operand = self._parse_not()
            return NotOp(operand=operand)

        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        """Parse comparison expressions: =, !=, <, >, <=, >=."""
        left = self._parse_in()

        if self._current().token_type == TokenType.COMPARISON:
            op_token = self._advance()
            right = self._parse_in()
            return ComparisonOp(left=left, operator=op_token.value, right=right)

        return left

    def _parse_in(self) -> Expr:
        """Parse IN / NOT IN expressions: expr [NOT] IN (val1, val2, ...)."""
        left = self._parse_addition()

        # Check for NOT IN (two-token lookahead)
        negate = False
        if (
            self._current().token_type == TokenType.LOGICAL
            and self._current().value.upper() in ("NOT", "!")
            and self._pos + 1 < len(self._tokens)
            and self._tokens[self._pos + 1].token_type == TokenType.KEYWORD
            and self._tokens[self._pos + 1].value.upper() == "IN"
        ):
            self._advance()  # consume NOT
            negate = True

        if self._match_keyword("IN"):
            self._advance()  # consume IN
            self._expect(TokenType.LPAREN)
            items: list[Expr] = []

            if self._current().token_type != TokenType.RPAREN:
                items.append(self._parse_expression())
                while self._current().token_type == TokenType.COMMA:
                    self._advance()
                    items.append(self._parse_expression())

            self._expect(TokenType.RPAREN)
            in_expr = InExpr(value=left, items=items)
            if negate:
                return NotOp(operand=in_expr)
            return in_expr

        return left

    def _parse_addition(self) -> Expr:
        """Parse addition and subtraction."""
        left = self._parse_multiplication()

        while self._current().token_type == TokenType.OPERATOR and self._current().value in ("+", "-"):
            op = self._advance().value
            right = self._parse_multiplication()
            left = BinaryOp(left=left, operator=op, right=right)

        return left

    def _parse_multiplication(self) -> Expr:
        """Parse multiplication, division, and modulo."""
        left = self._parse_unary()

        while self._current().token_type == TokenType.OPERATOR and self._current().value in ("*", "/", "%"):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryOp(left=left, operator=op, right=right)

        return left

    def _parse_unary(self) -> Expr:
        """Parse unary minus."""
        if self._current().token_type == TokenType.OPERATOR and self._current().value == "-":
            self._advance()
            operand = self._parse_unary()
            return UnaryOp(operator="-", operand=operand)

        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        """Parse primary expressions: literals, field refs, functions, parens, IF."""
        token = self._current()

        # IF expression
        if self._match_keyword("IF"):
            return self._parse_if()

        # Field reference
        if token.token_type == TokenType.FIELD_REF:
            self._advance()
            return FieldRef(field_name=token.value)

        # Row reference
        if token.token_type == TokenType.ROW_REF:
            self._advance()
            # Parse "offset:fieldname"
            parts = token.value.split(":", 1)
            offset = int(parts[0])
            field_name = parts[1]
            return RowRef(field_name=field_name, row_offset=offset)

        # String literal
        if token.token_type == TokenType.STRING:
            self._advance()
            return Literal(value=token.value, literal_type="string")

        # Number literal
        if token.token_type == TokenType.NUMBER:
            self._advance()
            if "." in token.value:
                return Literal(value=float(token.value), literal_type="number")
            return Literal(value=int(token.value), literal_type="number")

        # Keywords: TRUE, FALSE, NULL
        if token.token_type == TokenType.KEYWORD:
            upper = token.value.upper()
            if upper == "TRUE":
                self._advance()
                return Literal(value=True, literal_type="boolean")
            if upper == "FALSE":
                self._advance()
                return Literal(value=False, literal_type="boolean")
            if upper == "NULL":
                self._advance()
                return Literal(value=None, literal_type="null")
            raise ParserError(f"Unexpected keyword {token.value!r} in primary position", token)

        # Function call
        if token.token_type == TokenType.FUNCTION:
            self._advance()
            return self._parse_function_call(token.value)

        # Parenthesized expression
        if token.token_type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        # Bare identifier (treat as field ref or error)
        if token.token_type == TokenType.IDENTIFIER:
            self._advance()
            return FieldRef(field_name=token.value)

        raise ParserError("Unexpected token in expression", token)

    def _parse_if(self) -> IfExpr:
        """Parse an IF/THEN/ELSEIF/ELSE/ENDIF block."""
        self._expect(TokenType.KEYWORD, "IF")
        condition = self._parse_expression()
        self._expect(TokenType.KEYWORD, "THEN")
        then_expr = self._parse_expression()

        elseif_clauses: list[tuple[Expr, Expr]] = []
        else_expr: Expr | None = None

        while self._match_keyword("ELSEIF"):
            self._advance()
            elseif_cond = self._parse_expression()
            self._expect(TokenType.KEYWORD, "THEN")
            elseif_then = self._parse_expression()
            elseif_clauses.append((elseif_cond, elseif_then))

        if self._match_keyword("ELSE"):
            self._advance()
            else_expr = self._parse_expression()

        self._expect(TokenType.KEYWORD, "ENDIF")

        return IfExpr(
            condition=condition,
            then_expr=then_expr,
            elseif_clauses=elseif_clauses,
            else_expr=else_expr,
        )

    def _parse_function_call(self, name: str) -> FunctionCall:
        """Parse a function call: name(arg1, arg2, ...)."""
        self._expect(TokenType.LPAREN)
        arguments: list[Expr] = []

        if self._current().token_type != TokenType.RPAREN:
            arguments.append(self._parse_expression())
            while self._current().token_type == TokenType.COMMA:
                self._advance()
                arguments.append(self._parse_expression())

        self._expect(TokenType.RPAREN)
        return FunctionCall(function_name=name, arguments=arguments)
