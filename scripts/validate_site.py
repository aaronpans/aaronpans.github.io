"""Dependency-free static-site and governance template validation."""
import csv
import json
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://aaronpans.github.io'
errors = []

def check(condition, message):
    if not condition:
        errors.append(message)

def local_path(url):
    parts = urlsplit(url)
    if parts.netloc != 'aaronpans.github.io':
        return None
    path = ROOT / unquote(parts.path.lstrip('/'))
    return path / 'index.html' if parts.path.endswith('/') else path

class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links, self.canonicals, self.ld, self.ids = [], [], [], set()
        self.language_alternates = []
        self.language = None
        self.capture = False
        self.buffer = ''
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html':
            self.language = a.get('lang')
        if tag == 'link' and a.get('rel') == 'alternate' and a.get('hreflang'):
            self.language_alternates.append((a['hreflang'], a.get('href', '')))
        if a.get('id'):
            self.ids.add(a['id'])
        for key in ('href', 'src'):
            if a.get(key):
                self.links.append(a[key])
        if tag == 'link' and a.get('rel') == 'canonical':
            self.canonicals.append(a.get('href'))
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self.capture, self.buffer = True, ''

    def handle_data(self, data):
        if self.capture:
            self.buffer += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.capture:
            self.ld.append(json.loads(self.buffer))
            self.capture = False

pages = {}
for path in ROOT.rglob('*.html'):
    if '.git' in path.parts:
        continue
    try:
        page = Page(path.read_text(encoding='utf-8-sig'))
        pages[path] = page
        if path.name == 'index.html':
            relative = path.parent.relative_to(ROOT).as_posix()
            expected = ORIGIN + ('/' if relative == '.' else '/' + relative + '/')
            check(page.canonicals == [expected], f'{path}: canonical mismatch')
    except Exception as exc:
        errors.append(f'{path}: {exc}')

# Language variants must resolve to canonical pages and link back.
for path, page in pages.items():
    if not page.language_alternates:
        continue
    languages = [language for language, _ in page.language_alternates]
    check(len(languages) == len(set(languages)), f'{path}: duplicate hreflang')
    check(len(page.canonicals) == 1, f'{path}: language variants need one canonical')
    if len(page.canonicals) != 1:
        continue
    own_url = page.canonicals[0]
    check((page.language, own_url) in page.language_alternates,
          f'{path}: missing self-referencing language alternate')
    for language, url in page.language_alternates:
        parts = urlsplit(url)
        check(parts.scheme in ('http', 'https') and bool(parts.netloc),
              f'{path}: hreflang URL must be absolute: {url}')
        target = local_path(url)
        if target is None:
            continue  # External variants require a separate live check.
        check(target in pages, f'{path}: hreflang target missing: {url}')
        if target not in pages:
            continue
        alternate = pages[target]
        check(alternate.canonicals == [url], f'{path}: hreflang target is not canonical: {url}')
        if language != 'x-default':
            check(alternate.language == language, f'{path}: hreflang/target lang mismatch: {url}')
            check((page.language, own_url) in alternate.language_alternates,
                  f'{path}: missing reciprocal hreflang from {url}')

for path, page in pages.items():
    base = ORIGIN + '/' + path.relative_to(ROOT).as_posix()
    for link in page.links:
        target_url = urljoin(base, link)
        target = local_path(target_url)
        if target is None:
            continue
        check(target.is_file(), f'{path}: missing target {link}')
        fragment = unquote(urlsplit(target_url).fragment)
        if fragment and target in pages:
            check(fragment in pages[target].ids, f'{path}: missing fragment {link}')

for pattern in ('*.json', '*.jsonld'):
    for path in ROOT.rglob(pattern):
        if '.git' not in path.parts:
            try:
                json.loads(path.read_text(encoding='utf-8-sig'))
            except Exception as exc:
                errors.append(f'{path}: {exc}')
for path in ROOT.glob('*.xml'):
    try:
        ET.parse(path)
    except Exception as exc:
        errors.append(f'{path}: {exc}')

manifest = json.loads((ROOT / 'en/templates/templates.json').read_text())
playbooks = json.loads((ROOT / 'en/playbooks/playbooks.json').read_text())
check(len(manifest['templates']) == 3, 'Expected 3 templates')
for template in manifest['templates']:
    folder = local_path(template['url']).parent
    with (folder / 'template.csv').open(newline='', encoding='utf-8') as csv_file:
        rows = list(csv.reader(csv_file))
    html = unescape((folder / 'index.html').read_text())
    md = (folder / 'template.md').read_text()
    check(all(len(row) == len(rows[0]) for row in rows), f'{folder}: CSV width mismatch')
    check(template['fields'] == rows[0], f'{folder}: manifest/CSV fields mismatch')
    for field in rows[0]:
        check(field in html and field in md, f'{folder}: missing field {field}')
    for url in template['downloads'].values():
        check(local_path(url).is_file(), f'Missing download: {url}')
    if template['id'] == 'restaurant-operations-raci':
        check(len(rows) - 1 == 8, 'RACI must have 8 activities')
        for row in rows[1:]:
            roles = row[1:7]
            check(sum('A' in r.split('/') for r in roles) == 1, f'RACI A: {row[0]}')
            check(any('R' in r.split('/') for r in roles), f'RACI R: {row[0]}')
            check(row[0] in html and row[0] in md, f'RACI activity parity: {row[0]}')
    if template['id'] == 'training-certification-checklist':
        check(len(rows) - 1 == 12, 'Certification must have 12 gates')
        for row in rows[1:]:
            for cell in row[:4]:
                check(cell in html and cell in md, f'Certification parity: {cell}')
        for outcome in playbooks['certification_checklist']['outcomes']:
            check(outcome in html and outcome in md, f'Missing outcome: {outcome}')
    if template['id'] == 'store-inspection-closure-tracker':
        check(template['workflow'] == playbooks['closure_workflow']['steps'], 'Closure workflow drift')
        check(len(template['workflow']) == 8, 'Closure must have 8 stages')
        for step in template['workflow']:
            check(step['name'] in html and step['name'] in md, 'Closure stage parity')
        for rule in template['decision_rules']:
            check(rule in html and rule in md, 'Closure rule parity')

comparisons = json.loads((ROOT / 'en/decisions/comparisons.json').read_text())
for comparison in comparisons['comparisons']:
    target = comparison.get('working_template')
    check(bool(target), f'Missing working template: {comparison["query"]}')
    if target:
        check(local_path(target).is_file(), f'Missing decision template: {target}')
        source = local_path(comparison['url']).read_text()
        check(urlsplit(target).path in source, f'Decision page/manifest link mismatch: {target}')

# Check every bilingual FAQ answer, not only the model question.
class FAQAnswers(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.question = None
        self.capture = None
        self.buffer = []
        self.answers = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'h3':
            self.capture, self.buffer = 'question', []
        elif tag == 'p' and 'direct-answer' in attributes.get('class', '').split():
            self.capture, self.buffer = 'answer', []

    def handle_data(self, data):
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'h3' and self.capture == 'question':
            self.question = ''.join(self.buffer).strip()
            self.capture = None
        elif tag == 'p' and self.capture == 'answer':
            self.answers.append((self.question, ''.join(self.buffer).strip()))
            self.capture = None

for folder in ('faq', 'en/faq'):
    faq_path = ROOT / folder / 'index.html'
    faq_data = json.loads((ROOT / folder / 'questions.json').read_text())
    expected = [(q['question'], q['answer']) for q in faq_data['questions']]
    check(len({q for q, _ in expected}) == len(expected), f'{folder}: duplicate FAQ question')
    visible = FAQAnswers(faq_path.read_text()).answers
    structured = []
    for document in pages[faq_path].ld:
        for node in document.get('@graph', [document]):
            if node.get('@type') == 'FAQPage':
                structured.extend((q['name'], q['acceptedAnswer']['text']) for q in node.get('mainEntity', []))
    check(visible == expected, f'{folder}: visible answers differ from questions.json')
    check(structured == expected, f'{folder}: JSON-LD answers differ from questions.json')

# Keep the Chinese model answer aligned across visible HTML, JSON-LD and JSON.
model = json.loads((ROOT / 'frameworks/restaurant-operations-maturity-model/model.json').read_text())
faq_data = json.loads((ROOT / 'faq/questions.json').read_text())
model_question = '连锁餐饮营运标准化成熟度模型如何使用？'
matches = [q for q in faq_data['questions'] if q['question'] == model_question]
check(len(matches) == 1, 'Chinese model FAQ must occur exactly once in questions.json')
if len(matches) == 1:
    answer = matches[0]['answer']
    faq_path = ROOT / 'faq/index.html'
    faq_source = faq_path.read_text()
    faq_page = pages[faq_path]
    structured = []
    for document in faq_page.ld:
        for node in document.get('@graph', [document]):
            if node.get('@type') == 'FAQPage':
                structured.extend(q['acceptedAnswer']['text'] for q in node.get('mainEntity', []) if q.get('name') == model_question)
    check(structured == [answer], 'Chinese model FAQ JSON-LD/JSON mismatch')
    check(f'<h3>{model_question}</h3><p class="direct-answer">{answer}</p>' in faq_source,
          'Chinese model FAQ visible answer/JSON mismatch')
    for group in ('dimensions', 'levels'):
        names = [item['name'] for item in model[group]]
        check('、'.join(names) in answer, f'Chinese model FAQ {group} names/order mismatch')
    check('待确认' in answer and '不计算总分或判定总分区间' in answer,
          'Chinese model FAQ missing incomplete-evidence rule')

sitemap = ET.parse(ROOT / 'sitemap.xml')
urls = [e.text for e in sitemap.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
check(len(urls) == len(set(urls)), 'Duplicate sitemap URLs')
for path in pages:
    if path.name == 'index.html':
        check(pages[path].canonicals[0] in urls, f'Not in sitemap: {path}')
for url in urls:
    check(local_path(url).is_file(), f'Sitemap target missing: {url}')
if errors:
    print('\n'.join(errors))
    raise SystemExit(1)
print(f'PASS: {len(pages)} HTML files; JSON-LD, JSON, XML, links/fragments, canonicals, sitemap; 3 template manifests and downloads; 8 RACI activities, 8 closure stages, 12 certification gates.')
