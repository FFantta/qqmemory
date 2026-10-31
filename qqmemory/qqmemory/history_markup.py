"""Split well-formed feed cards without building and serializing an HTML tree."""
from html.parser import HTMLParser


class CardSplitter(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.markup = markup
        self.lines = [0]
        for index, char in enumerate(markup):
            if char == '\n':
                self.lines.append(index + 1)
        self.start = None
        self.depth = 0
        self.cards = []
        self.nested_cards = False

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag != 'li':
            return
        if self.start is not None:
            self.depth += 1
            if 'f-single' in (dict(attrs).get('class') or '').split():self.nested_cards=True
        elif 'f-single' in (dict(attrs).get('class') or '').split():
            self.start, self.depth = self.position(), 1

    def handle_endtag(self, tag):
        if tag != 'li' or self.start is None:
            return
        self.depth -= 1
        if not self.depth:
            end = self.markup.find('>', self.position()) + 1
            self.cards.append(self.markup[self.start:end])
            self.start = None


def split_cards(markup):
    parser = CardSplitter(markup)
    parser.feed(markup)
    parser.close()
    if parser.start is not None or parser.nested_cards:
        # Retain the established repair behavior for malformed legacy markup.
        from bs4 import BeautifulSoup
        return [str(node) for node in BeautifulSoup(markup, 'html.parser').select('li.f-single')]
    return parser.cards
