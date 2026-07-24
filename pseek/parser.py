import re, sys, click
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


    def count_matches(self, text: str) -> int:
        """Count how many times the pattern or fuzzy term appears in the text"""
        if not self.fuzzy:
            return sum(1 for _ in self.pattern.finditer(text))

        text_cmp = text if self.case_sensitive else text.lower()
        term = self.raw_term if self.case_sensitive else self.raw_term.lower()

        if self.whole_word:
            words = re.findall(r'\w+', text_cmp)
            return sum(1 for word in words if fuzz.ratio(term, word) >= self.fuzzy_level)

        # Optionally could implement a sliding window here, but it's expensive
        return 0

    def get_binary_pattern(self) -> re.Pattern:
        """Return a compiled binary regex pattern"""
        if self.fuzzy:
            raise NotImplementedError("Binary pattern is not supported for fuzzy matching.")
        return re.compile(self.pattern.pattern.encode("utf-8"), self.pattern.flags)


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


class TreeToExpr(Transformer):
    """Transform parsed tree into expression tree (ExprNode subclasses)"""
    def __init__(self, fuzzy_level):
        super().__init__()
        self.fuzzy_level = fuzzy_level

    def string(self, s):
        """ Match normal quoted string: "foo" """
        term = s[0][1:-1]  # Remove surrounding quotes (e.g., "foo" -> foo)
        return TermNode(
            term,
            False,
            False,
            False,
            False,
            None
        )

    def prefixed_string(self, s):
        text = str(s[0])  # e.g., 'rc"pattern"'
        prefix = text.split('"', 1)[0].lower()
        content = text.split('"', 1)[1][:-1]

        return TermNode(
            content,
            regex='r' in prefix,
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
    parser = Lark(query_grammar, parser="lalr")
    try:
        tree = parser.parse(config.query)
        return TreeToExpr(config.fuzzy_level).transform(tree)
    except Exception as e:
        click.echo(click.style("Query parser error:\n\n", fg='red') + str(e))
        sys.exit(1)


def highlight_text(expr: ExprNode, text: str) -> str:
    """
    Highlight matching parts of the text.
    Only highlights fuzzy matches when whole_word=True.
    """
    matches = []

    def collect_matches(node):
        if isinstance(node, TermNode):
            # Skip fuzzy highlight if whole_word is False
            if node.fuzzy:
                if not node.whole_word:
                    return  # skip highlighting
                text_cmp = text if node.case_sensitive else text.lower()
                term = node.raw_term if node.case_sensitive else node.raw_term.lower()

                # collect word matches
                for match in re.finditer(r'\w+', text_cmp):
                    word = match.group()
                    if fuzz.ratio(term, word) >= node.fuzzy_level:
                        matches.append((match.start(), match.end()))
            else:
                for match in node.pattern.finditer(text):
                    matches.append((match.start(), match.end()))
        elif isinstance(node, (AndNode, OrNode)):
            collect_matches(node.left)
            collect_matches(node.right)

    collect_matches(expr)

    # Sort and merge overlapping matches (for example, if one match was inside another match)
    matches.sort()  # sort by start position
    merged = []
    for start, end in matches:
        if not merged or start >= merged[-1][1]:  # no overlap
            merged.append((start, end))
        else:
            # Merge overlapping
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    # Build highlighted text
    result = []
    last = 0
    for start, end in merged:
        result.append(text[last:start])
        result.append(click.style(text[start:end], fg='green'))
        last = end
    result.append(text[last:])

    return ''.join(result)
