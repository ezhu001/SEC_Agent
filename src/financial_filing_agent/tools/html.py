import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


def parse_html(html):
    # SEC Inline XBRL is XHTML with namespaces. We deliberately preserve the
    # HTML table tree and separately read the namespace-qualified XBRL tags.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, "lxml")
