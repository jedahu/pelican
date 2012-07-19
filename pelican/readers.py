# -*- coding: utf-8 -*-
try:
    import docutils
    import docutils.core
    import docutils.io
    from docutils.writers.html4css1 import HTMLTranslator

    # import the directives to have pygments support
    from pelican import rstdirectives  # NOQA
except ImportError:
    core = False
try:
    from markdown import Markdown
except ImportError:
    Markdown = False  # NOQA
try:
    from asciidocapi import AsciiDocAPI
except ImportError:
    AsciiDocAPI = False
import re
import StringIO
from codecs import open as _open

from pelican.contents import Category, Tag, Author
from pelican.utils import get_date, open


_METADATA_PROCESSORS = {
    'tags': lambda x, y: [Tag(tag, y) for tag in unicode(x).split(',')],
    'date': lambda x, y: get_date(x),
    'status': lambda x, y: unicode.strip(x),
    'category': Category,
    'author': Author,
}


class Reader(object):
    enabled = True
    extensions = None

    def __init__(self, settings):
        self.settings = settings

    def process_metadata(self, name, value):
        if name in _METADATA_PROCESSORS:
            return _METADATA_PROCESSORS[name](value, self.settings)
        return value


class _FieldBodyTranslator(HTMLTranslator):

    def __init__(self, document):
        HTMLTranslator.__init__(self, document)
        self.compact_p = None

    def astext(self):
        return ''.join(self.body)

    def visit_field_body(self, node):
        pass

    def depart_field_body(self, node):
        pass


def render_node_to_html(document, node):
    visitor = _FieldBodyTranslator(document)
    node.walkabout(visitor)
    return visitor.astext()


class PelicanHTMLTranslator(HTMLTranslator):

    def visit_abbreviation(self, node):
        attrs = {}
        if node.hasattr('explanation'):
            attrs['title'] = node['explanation']
        self.body.append(self.starttag(node, 'abbr', '', **attrs))

    def depart_abbreviation(self, node):
        self.body.append('</abbr>')


class RstReader(Reader):
    enabled = bool(docutils)
    file_extensions = ['rst']

    def _parse_metadata(self, document):
        """Return the dict containing document metadata"""
        output = {}
        for docinfo in document.traverse(docutils.nodes.docinfo):
            for element in docinfo.children:
                if element.tagname == 'field':  # custom fields (e.g. summary)
                    name_elem, body_elem = element.children
                    name = name_elem.astext()
                    if name == 'summary':
                        value = render_node_to_html(document, body_elem)
                    else:
                        value = body_elem.astext()
                else:  # standard fields (e.g. address)
                    name = element.tagname
                    value = element.astext()
                name = name.lower()

                output[name] = self.process_metadata(name, value)
        return output

    def _get_publisher(self, filename):
        extra_params = {'initial_header_level': '2'}
        pub = docutils.core.Publisher(
                destination_class=docutils.io.StringOutput)
        pub.set_components('standalone', 'restructuredtext', 'html')
        pub.writer.translator_class = PelicanHTMLTranslator
        pub.process_programmatic_settings(None, extra_params, None)
        pub.set_source(source_path=filename)
        pub.publish()
        return pub

    def read(self, filename):
        """Parses restructured text"""
        pub = self._get_publisher(filename)
        parts = pub.writer.parts
        content = parts.get('body')

        metadata = self._parse_metadata(pub.document)
        metadata.setdefault('title', parts.get('title'))

        return content, metadata


class MarkdownReader(Reader):
    enabled = bool(Markdown)
    file_extensions = ['md', 'markdown', 'mkd']
    extensions = ['codehilite', 'extra']

    def read(self, filename):
        """Parse content and metadata of markdown files"""
        text = open(filename)
        md = Markdown(extensions=set(self.extensions + ['meta']))
        content = md.convert(text)

        metadata = {}
        for name, value in md.Meta.items():
            name = name.lower()
            metadata[name] = self.process_metadata(name, value[0])
        return content, metadata


class AsciiDocReader(Reader):
  enabled = bool(AsciiDocAPI)
  file_extensions = ['txt']

  def read(self, filename):
    """Parse content and metadata of asciidoc files"""
    ad = AsciiDocAPI()
    ad.options('--no-header-footer')
    ad.attributes['pygments'] = 'pygments'
    if self.settings['ASCIIDOC_CONF']:
      ad.attributes['conf-files'] = self.settings['ASCIIDOC_CONF']
    buf = StringIO.StringIO()
    ad.execute(filename, buf, 'html5')
    content = buf.getvalue()
    buf.close()
    meta = self.read_meta(filename)
    return content, meta

  meta_re = re.compile(r'^:(.+?): (.+)$')
  author_re = re.compile(r'^([^\s].+?) <([^\s]+?)>$')
  rev_re = re.compile(r'^(?:(.+?),)? *(.+?): *(.+?)$')

  def read_meta(self, filename):
    title = None
    metadata = {}
    with _open(filename, encoding='utf-8') as f:
      for line in f:
        line = line.rstrip()
        meta_match = self.meta_re.match(line)
        author_match = self.author_re.match(line)
        rev_match = self.rev_re.match(line)
        if line.strip() != '' and title == None:
          title = line
          metadata['title'] = title
        elif line.strip() == '' and title != None:
          break
        elif meta_match:
          name = meta_match.group(1).lower()
          value = meta_match.group(2)
          metadata[name] = self.process_metadata(name, value)
          if name == 'revdate':
            metadata['date'] = self.process_metadata(name, value)
        elif author_match:
          author = author_match.group(1)
          email = author_match.group(2)
          metadata['author'] = self.process_metadata('author', author)
          metadata['email'] = self.process_metadata('email', email)
        elif rev_match:
          rev = rev_match.group(1)
          date = rev_match.group(2)
          comment = rev_match.group(3)
          metadata['revdate'] = date
          metadata['date'] = self.process_metadata('date', date)
          metadata['revnumber'] = rev
          metadata['revremark'] = comment
        else:
          continue
    return metadata


class HtmlReader(Reader):
    file_extensions = ['html', 'htm']
    _re = re.compile('\<\!\-\-\#\s?[A-z0-9_-]*\s?\:s?[A-z0-9\s_-]*\s?\-\-\>')

    def read(self, filename):
        """Parse content and metadata of (x)HTML files"""
        with open(filename) as content:
            metadata = {'title': 'unnamed'}
            for i in self._re.findall(content):
                key = i.split(':')[0][5:].strip()
                value = i.split(':')[-1][:-3].strip()
                name = key.lower()
                metadata[name] = self.process_metadata(name, value)

            return content, metadata


_EXTENSIONS = {}

for cls in Reader.__subclasses__():
    for ext in cls.file_extensions:
        _EXTENSIONS[ext] = cls


def read_file(filename, fmt=None, settings=None):
    """Return a reader object using the given format."""
    if not fmt:
        fmt = filename.split('.')[-1]

    if fmt not in _EXTENSIONS:
        raise TypeError('Pelican does not know how to parse %s' % filename)

    reader = _EXTENSIONS[fmt](settings)
    settings_key = '%s_EXTENSIONS' % fmt.upper()

    if settings and settings_key in settings:
        reader.extensions = settings[settings_key]

    if not reader.enabled:
        raise ValueError("Missing dependencies for %s" % fmt)

    content, metadata = reader.read(filename)

    # eventually filter the content with typogrify if asked so
    if settings and settings['TYPOGRIFY']:
        from typogrify import Typogrify
        content = Typogrify.typogrify(content)
        metadata['title'] = Typogrify.typogrify(metadata['title'])

    return content, metadata
