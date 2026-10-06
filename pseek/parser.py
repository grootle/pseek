import re, click, json
from lark import Lark, Transformer
from .utils import compile_regex
from rapidfuzz import fuzz


class ExprNode:
    """Base class for expression tree nodes"""
    def evaluate(self, text: str) -> bool:
        raise NotImplementedError


class TermNode(ExprNode):
    """Node representing a single search term"""
    def __init__(self, term: str, regex, whole_word, case_sensitive, fuzzy, fuzzy_level):
        self.raw_term = term
        self.term_lower = term.lower()
        self.regex = regex
        self.whole_word = whole_word
        self.case_sensitive = case_sensitive
        self.fuzzy = fuzzy
        self.fuzzy_level = fuzzy_level

        if not fuzzy:
            flags = 0 if case_sensitive else re.IGNORECASE  # Adjust case sensitivity

            # Build the regex pattern
            if not regex:
                term = re.escape(term)  # Escape if not regex
                # Apply whole-word matching only if not using regex (or if desired behavior is defined)
                if whole_word:
                    term = r'\b' + term + r'\b'

            self.pattern = compile_regex(term, flags)  # Precompile the regex pattern for performance

    def evaluate(self, text: str) -> bool:
        # Fuzzy search mode
        text_cmp = text if self.case_sensitive else text.lower()
        term = self.raw_term if self.case_sensitive else self.term_lower
        
        if not self.fuzzy:
            # Use substring search for more speed
            if not self.regex and not self.whole_word:
                return term in text_cmp

            return bool(self.pattern.search(text))

        if self.whole_word:
            words = re.findall(r'\w+', text_cmp)
            return any(fuzz.ratio(term, word) >= self.fuzzy_level for word in words)
        else:
            # Use the correct method depending on the len of str to increase accuracy and avoid illogical matching
            if len(text_cmp) > len(term):
                score = fuzz.partial_ratio(term, text_cmp)
            else:
                score = fuzz.ratio(term, text_cmp)
            return score >= self.fuzzy_level

    def get_binary_pattern(self):
        """
        Return a safe byte pattern for mmap pre-filtering

        The pre-filter must never produce false negatives.
        Only exact, case-sensitive literal searches are supported.
        It's only used as a fast pre-filter; the actual match is
        still performed on decoded text.
        """

        # Binary pattern is not supported for fuzzy matching.
        # Regex may behave differently in bytes.
        # Unicode case-insensitive matching can't safely
        # be reproduced with a bytes pattern.
        if (
            self.fuzzy
            or self.whole_word
            or not self.case_sensitive
            or self.regex
        ):
            return None

        return self.raw_term.encode('utf-8')


class NotNode(ExprNode):
    """Node representing logical NOT"""
    def __init__(self, child: ExprNode):
        self.child = child

    def evaluate(self, text: str) -> bool:
        return not self.child.evaluate(text)


class AndNode(ExprNode):
    """Node representing logical AND"""
    def __init__(self, left: ExprNode, right: ExprNode):
        self.left = left
        self.right = right

    def evaluate(self, text: str) -> bool:
        return self.left.evaluate(text) and self.right.evaluate(text)


class OrNode(ExprNode):
    """Node representing logical OR"""
    def __init__(self, left: ExprNode, right: ExprNode):
        self.left = left
        self.right = right

    def evaluate(self, text: str) -> bool:
        return self.left.evaluate(text) or self.right.evaluate(text)


# Lark grammar for parsing logical expressions
query_grammar = r"""
?start: expr

?expr: or_expr

?or_expr: and_expr
        | or_expr "or" and_expr     -> or_expr

?and_expr: not_expr
         | and_expr "and" not_expr  -> and_expr

?not_expr: "not" not_expr           -> not_expr
         | term

?term: PREFIXED_STRING          -> prefixed_string
     | ESCAPED_STRING           -> string
     | "(" expr ")"

PREFIXED_STRING: /(r|c|w|f|rc|cr|cw|wc|cf|fc|wf|fw|cwf|cfw|wcf|wfc|fcw|fwc)"([^"\\]|\\.)*"/

%import common.ESCAPED_STRING
%import common.WS
%ignore WS
"""

QUERY_PARSER = Lark(query_grammar, parser='lalr')


def decode_expr_string(token: str, regex: bool = False) -> str:
    """
    Decode a quoted expression string.

    Normal strings use JSON-style escaping.
    """
    if not regex:
        return json.loads(token)

    # Keep regex escapes such as \b, \d, and \w intact
    return token[1:-1]


class TreeToExpr(Transformer):
    """Transform parsed tree into expression tree (ExprNode subclasses)"""
    def __init__(self, fuzzy_level):
        super().__init__()
        self.fuzzy_level = fuzzy_level

    def string(self, s):
        """ Match normal quoted string: "foo" """
        term = decode_expr_string(str(s[0]))
        return TermNode(
            term,
            False,
            False,
            False,
            False,
            None
        )

    def prefixed_string(self, s):
        """Transform a prefixed search term"""
        text = str(s[0])  # e.g., 'rc"pattern"'

        quote_index = text.index('"')
        prefix = text[:quote_index].lower()
        quoted = text[quote_index:]

        is_regex = 'r' in prefix
        content = decode_expr_string(quoted, is_regex)

        return TermNode(
            content,
            regex=is_regex,
            whole_word='w' in prefix,
            case_sensitive='c' in prefix,
            fuzzy='f' in prefix,
            fuzzy_level=self.fuzzy_level
        )

    def and_expr(self, args):
        return AndNode(args[0], args[1])

    def or_expr(self, args):
        return OrNode(args[0], args[1])

    def not_expr(self, args):
        return NotNode(args[0])


def parse_query_expression(config) -> ExprNode:
    """
    Function to parse the query and return expression tree.
    If expr is False, treat the whole query as a single term.
    """

    if config.query is None:
        return None

    if not config.expr:
        return TermNode(
            config.query,
            config.regex,
            config.word,
            config.case_sensitive,
            config.fuzzy,
            config.fuzzy_level
        )

    # Otherwise, parse using Lark
    try:
        tree = QUERY_PARSER.parse(config.query)
        return TreeToExpr(config.fuzzy_level).transform(tree)
    except Exception as e:
        click.echo(click.style("Query parser error:\n\n", fg='red') + str(e))
        raise click.exceptions.Exit(1)


def find_term_matches(node: TermNode, text: str, num: int) -> list[tuple[int, int]]:
    """Find matching spans for a single term"""

    if node.fuzzy:
        # Fuzzy partial matching currently has no span extraction
        if not node.whole_word:
            return []

        text_cmp = (
            text if node.case_sensitive
            else text.lower()
        )
        term = (
            node.raw_term if node.case_sensitive
            else node.term_lower
        )

        matches = []

        for match in re.finditer(r'\w+', text_cmp):
            word = match.group()

            if fuzz.ratio(term, word) >= node.fuzzy_level:
                matches.append((
                    match.start() + num,
                    match.end() + num
                ))

        return matches

    return [
        (match.start() + num, match.end() + num)
        for match in node.pattern.finditer(text)
    ]


def evaluate_with_matches(
    node: ExprNode,
    text: str,
    num: int,
    positive: bool = True
) -> tuple[bool, list[tuple[int, int]]]:
    """
    Evaluate an expression and collect spans from successful positive branches

    Args:
        node: Expression tree node
        text: Text to search
        num: Offset added to returned match positions,
            because when name is combined with parent path,
            matches values change
        positive: Whether the current expression is evaluated
            in a positive or negated context

    Returns:
        A tuple of (matched, matching_spans).
    """

    if isinstance(node, TermNode):
        matched = node.evaluate(text)

        # A negated term can make an expression true by its
        # absence, but it does not provide a span to highlight
        if not positive:
            return not matched, []

        if not matched:
            return False, []

        return True, find_term_matches(node, text, num)

    if isinstance(node, NotNode):
        # NOT reverses the polarity of its child
        return evaluate_with_matches(
            node.child,
            text,
            num,
            not positive,
        )

    if isinstance(node, (AndNode, OrNode)):
        is_and = isinstance(node, AndNode)

        # Negation reverses the operator.
        # AND becomes OR, and OR becomes AND (De Morgan's law):
        # NOT (A AND B) = NOT A OR NOT B
        # NOT (A OR B)  = NOT A AND NOT B
        # The equality checks whether the original and effective operators match.
        effective_and = is_and == positive

        left_matched, left_matches = evaluate_with_matches(
            node.left,
            text,
            num,
            positive
        )

        if effective_and:
            # Both operands must match
            if not left_matched:
                return False, []

            right_matched, right_matches = evaluate_with_matches(
                node.right,
                text,
                num,
                positive
            )

            if not right_matched:
                return False, []

            return True, left_matches + right_matches

        # OR: evaluate both branches so that matches from
        # every successful branch can be collected
        right_matched, right_matches = evaluate_with_matches(
            node.right,
            text,
            num,
            positive
        )

        matched = left_matched or right_matched

        if not matched:
            return False, []

        matches = []

        if left_matched:
            matches.extend(left_matches)

        if right_matched:
            matches.extend(right_matches)

        return True, matches

    raise TypeError(
        f'Unsupported expression node: {type(node).__name__}'
    )


def find_matches(expr: ExprNode, text: str, num: int = 0) -> list[tuple[int, int]]:
    """Find spans that contribute to a successful expression"""

    if expr is None:
        return []

    matched, matches = evaluate_with_matches(expr, text, num)
    # Remove duplicate ranges
    return list(dict.fromkeys(matches)) if matched else []
