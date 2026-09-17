"""Check shared layout hooks; this does not replace browser visual QA."""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SHELLS = {'home', 'section', 'article-shell', 'article-page'}
LEGACY_STYLESHEET = '/assets/legacy-article.css?v=20260916'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.classes = set()
        self.body_classes = set()
        self.stylesheets = []
        self.h1 = 0
        self.viewport = False
        self.images_missing_alt = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        self.classes.update(classes)
        if tag == 'body':
            self.body_classes = classes
        if tag == 'h1':
            self.h1 += 1
        if tag == 'meta' and attrs.get('name') == 'viewport':
            self.viewport = 'width=device-width' in attrs.get('content', '')
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.stylesheets.append(attrs.get('href'))
        if tag == 'img' and 'alt' not in attrs:
            self.images_missing_alt.append(attrs.get('src'))


def main():
    errors = []
    count = 0
    for path in ROOT.rglob('*.html'):
        if '.git' in path.parts:
            continue
        source = path.read_text(encoding='utf-8-sig')
        if path.parent == ROOT and source.strip().startswith('google-site-verification:'):
            continue
        count += 1
        page = Page(source)
        checks = {
            'exactly one H1': page.h1 == 1,
            'responsive viewport': page.viewport,
            'navigation layout': {'nav', 'nav-links'} <= page.classes,
            'supported content shell': bool(SUPPORTED_SHELLS & page.classes),
            'stylesheet': bool(page.stylesheets),
            'image alt attributes': not page.images_missing_alt,
        }
        legacy = 'legacy-article' in page.body_classes
        checks['legacy CSS and scope agree'] = legacy == (LEGACY_STYLESHEET in page.stylesheets)
        if 'article-page' in page.classes:
            checks['old article shell has compatibility styles'] = legacy
        for label, valid in checks.items():
            if not valid:
                errors.append(f'{path.relative_to(ROOT)}: {label}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'PASS: {count} content pages; layout hooks, viewport, H1 and image alt attributes. Visual QA remains separate.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
