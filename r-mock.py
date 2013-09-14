import traceback
import hashlib
import urlparse
import urllib
import cPickle
import cgi
import logging
from w3lib.url import safe_url_string
from requests import api, sessions, get, post, models

try:  # Python 2.7+
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logger = logging.getLogger(__name__)
logger.addHandler(NullHandler())


def parse_url(url, encoding=None):
    """Return urlparsed url from the given argument (which could be an already
    parsed url)
    """
    return url if isinstance(url, urlparse.ParseResult) else \
        urlparse.urlparse(unicode_to_str(url, encoding))


def unicode_to_str(text, encoding=None, errors='strict'):
    """Return the str representation of text in the given encoding. Unlike
    .encode(encoding) this function can be applied directly to a str
    object without the risk of double-decoding problems (which can happen if
    you don't use the default 'ascii' encoding)
    """

    if encoding is None:
        encoding = 'utf-8'
    if isinstance(text, unicode):
        return text.encode(encoding, errors)
    elif isinstance(text, str):
        return text
    else:
        raise TypeError('unicode_to_str must receive a unicode or str object, got %s' % type(text).__name__)


def _unquotepath(path):
    for reserved in ('2f', '2F', '3f', '3F'):
        path = path.replace('%' + reserved, '%25' + reserved.upper())
    return urllib.unquote(path)


def canonicalize_url(url, extra_params, keep_blank_values=True, keep_fragments=False,
        encoding=None):
    """Canonicalize the given url by applying the following procedures:

    - sort query arguments, first by key, then by value
    - percent encode paths and query arguments. non-ASCII characters are
      percent-encoded using UTF-8 (RFC-3986)
    - normalize all spaces (in query arguments) '+' (plus symbol)
    - normalize percent encodings case (%2f -> %2F)
    - remove query arguments with blank values (unless keep_blank_values is True)
    - remove fragments (unless keep_fragments is True)

    The url passed can be a str or unicode, while the url returned is always a
    str.

    For examples see the tests in scrapy.tests.test_utils_url
    """

    scheme, netloc, path, params, query, fragment = parse_url(url)
    keyvals = cgi.parse_qsl(query, keep_blank_values)
    keyvals.sort()
    if extra_params:
        keyvals += extra_params.items()

    query = urllib.urlencode(keyvals)
    path = safe_url_string(_unquotepath(path)) or '/'
    fragment = '' if not keep_fragments else fragment
    return urlparse.urlunparse((scheme, netloc.lower(), path, params, query, fragment))


def request_fingerprint(request, include_headers=None):
    if include_headers:
        include_headers = tuple([h.lower() for h in sorted(include_headers)])

    fp = hashlib.sha1()
    fp.update(request["method"])
    fp.update(canonicalize_url(request["url"], request.get("params")))
    fp.update(request.get("body", ""))
    fp.update(request.get("tb", str((None, None, None, None))))

    if include_headers:
        for hdr in include_headers:
            if hdr in request.headers:
                fp.update(hdr)
                for v in request.headers.getlist(hdr):
                    fp.update(v)

    return fp.hexdigest()

class CacheStorage(object):
    def get(self, fingerprint):
        raise NotImplemented

    def put(self, fingerprint, obj):
        raise NotImplemented


class InMemoryStorage(CacheStorage):
    def __init__(self):
        self._cache = {}

    def get(self, fingerprint):
        if fingerprint in self._cache:
            return cPickle.loads(self._cache[fingerprint])

    def put(self, fingerprint, obj):
        self._cache[fingerprint] = cPickle.dumps(obj)


def _wrapper_for_request(filters, storage, tb_ignores):
    def _patched_request(method, url, **kwargs):
        """Constructs and sends a :class:`Request <Request>`.
        Returns :class:`Response <Response>` object.

        :param method: method for the new :class:`Request` object.
        :param url: URL for the new :class:`Request` object.
        :param params: (optional) Dictionary or bytes to be sent in the query string for the :class:`Request`.
        :param data: (optional) Dictionary, bytes, or file-like object to send in the body of the :class:`Request`.
        :param headers: (optional) Dictionary of HTTP Headers to send with the :class:`Request`.
        :param cookies: (optional) Dict or CookieJar object to send with the :class:`Request`.
        :param files: (optional) Dictionary of 'name': file-like-objects (or {'name': ('filename', fileobj)}) for multipart encoding upload.
        :param auth: (optional) Auth tuple to enable Basic/Digest/Custom HTTP Auth.
        :param timeout: (optional) Float describing the timeout of the request.
        :param allow_redirects: (optional) Boolean. Set to True if POST/PUT/DELETE redirect following is allowed.
        :param proxies: (optional) Dictionary mapping protocol to the URL of the proxy.
        :param verify: (optional) if ``True``, the SSL cert will be verified. A CA_BUNDLE path can also be provided.
        :param stream: (optional) if ``False``, the response content will be immediately downloaded.
        :param cert: (optional) if String, path to ssl client cert file (.pem). If Tuple, ('cert', 'key') pair.

        Usage::

          >>> import requests
          >>> req = requests.request('GET', 'http://httpbin.org/get')
          <Response [200]>
        """

        session = sessions.Session()
        tb = [
            (tb[0] if not tb_ignores.get("filename", False) else None,
             tb[1] if not tb_ignores.get("lineno", False) else None,
             tb[2] if not tb_ignores.get("scope", False) else None,
             tb[3] if not tb_ignores.get("source", False) else None,)
         for tb in traceback.extract_stack()]

        request_data = {
            "url": url,
            "method": method,
            "traceback": tb,
            "body": kwargs.get("data", ""),
            "params": kwargs.get("params")
        }

        fp = request_fingerprint(request_data)
        if any(flt(request_data) for flt in filters):
            logger.debug("Cache is disabled for: %s %s" % (method, url))
            return session.request(method=method, url=url, **kwargs)

        result = storage.get(fp)
        if not result:
            result = session.request(method=method, url=url, **kwargs)
            storage.put(fp, result)
        else:
            logger.debug("Cache hit: %s %s" % (method, url))

        return result

    return _patched_request


def patch_requests(filters=[], 
                   storage=InMemoryStorage(),
                   tb_ignores={"source": True}):

    def __getstate__(self):
        # consume everything
        if not self._content_consumed:
            self.content
        attrs = (attr for attr in self.__dict__.keys() if attr != 'raw')
        return dict((attr, getattr(self, attr, None)) for attr in attrs)

    def __setstate__(self, state):
        for name, value in state.items():
            setattr(self, name, value)

    models.Response.__getstate__ = __getstate__
    models.Response.__setstate__ = __setstate__
    api.request = _wrapper_for_request(filters, storage, tb_ignores)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    patch_requests(
        filters=[lambda r: "yahoo.com" in r["url"]],
        tb_ignores={"source": True, "lineno": True})

    print get("http://google.com/?foo=bar2", params={"foo": "bar"})
    print get("http://google.com/?foo=bar2", params={"foo": "bar"})

    print get("http://yahoo.com/")
    print get("http://yahoo.com/")