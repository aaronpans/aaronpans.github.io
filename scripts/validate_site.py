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
        self.capture = False
        self.buffer = ''
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
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
    rows = list(csv.reader((folder / 'template.csv').open(newline='')))
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
