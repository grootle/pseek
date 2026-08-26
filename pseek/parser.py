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

    def get_binary_pattern(self):
        """
        Return a binary pre-filter suitable for mmap searching

        The returned matcher must never produce false negatives.
        It's only used as a fast pre-filter; the actual match is
        still performed on decoded text.
        """

        # Binary pattern is not supported for fuzzy matching
        # Regex with Unicode-sensitive semantics may behave differently in bytes
        # Unicode case-insensitive matching can't safely be reproduced with a bytes pattern
        if self.fuzzy or self.whole_word or not self.case_sensitive:
            return None
        
        if not self.regex and self.case_sensitive:
            return self.raw_term.encode("utf-8")

        pattern = self.pattern.pattern.encode("utf-8")
        # The UNICODE flag isn't supported for bytes patterns
        flags = self.pattern.flags & ~re.UNICODE

        return re.compile(pattern, flags)


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


def find_matches(expr: ExprNode, text: str, num: int = 0) -> list[tuple[int, int]]:
    """
    Find all matching parts of the text.
    Only find fuzzy matches when whole_word=True.
    
    num: It should be added to matches because when name is combined with parent path, matches values change.
    """
    matches = []

    def collect_matches(node):
        if isinstance(node, TermNode):
            # Skip fuzzy if whole_word is False
            if node.fuzzy:
                if not node.whole_word:
                    return  # skip finding
                text_cmp = text if node.case_sensitive else text.lower()
                term = node.raw_term if node.case_sensitive else node.raw_term.lower()

                # collect word matches
                for match in re.finditer(r'\w+', text_cmp):
                    word = match.group()
                    if fuzz.ratio(term, word) >= node.fuzzy_level:
                        matches.append((match.start() + num, match.end() + num))
            else:
                for match in node.pattern.finditer(text):
                    matches.append((match.start() + num, match.end() + num))
        elif isinstance(node, (AndNode, OrNode)):
            collect_matches(node.left)
            collect_matches(node.right)

    collect_matches(expr)
    # sort by start position
    matches.sort()
    
    return matches
