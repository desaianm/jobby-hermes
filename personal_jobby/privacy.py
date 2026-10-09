"""Shared output/storage filtration; private phone entry remains separate."""
import re
from urllib.parse import unquote, unquote_plus, urlsplit

PHONE = re.compile(r'(?<!\w)\+?\d[\d ()\t.\-]{7,40}\d(?!\w)')
_SECRET_FIELDS = {'password', 'passwd', 'passphrase', 'apikey', 'accesskey',
                  'token', 'accesstoken', 'refreshtoken', 'idtoken', 'authtoken',
                  'secret', 'clientsecret', 'credential', 'credentials',
                  'authorization', 'cookie', 'setcookie', 'session', 'sessionid',
                  'privatekey', 'csrf', 'csrftoken'}
_SECRET_PARAMETERS = _SECRET_FIELDS | {'auth', 'key', 'signature', 'sig', 'code',
    'authcode', 'xamzsignature', 'xamzcredential', 'xamzsecuritytoken',
    'xgoogsignature', 'xgoogcredential'}


def _secret_field(key):
    return re.sub(r'[^a-z0-9]', '', unquote_plus(key).lower()) in _SECRET_FIELDS


_CREDENTIAL = re.compile(
    r'\bbearer\s+[^\s,;]+|\b(?:password|passwd|passphrase|token|access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|secret|credential)\s*["\']?\s*[:=]\s*(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;]+)'
    r'|\b(?:sk-[\w-]+|ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b'
    r'|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', re.IGNORECASE)


def _mask_credentials(text):
    return _CREDENTIAL.sub('[private credential]', text)


def _mask_text(text):
    return _mask_phone(_mask_credentials(text))


def _mask_phone(text):
    def replace(match):
        value=match.group();digits=re.sub(r'\D','',value)
        groups=re.findall(r'\d+',value)
        # Do not mistake a salary range or separated large metrics for a telephone.
        if sum(len(g)>=5 for g in groups)>1: return value
        return '[private phone]' if 10<=len(digits)<=15 else value
    return PHONE.sub(replace,text)


# Only these public job routes give a numeric token identifier semantics.
_SLUG = r'[A-Za-z0-9_-]{1,100}'
_ID = r'[A-Za-z0-9][A-Za-z0-9_]{0,99}'
_UUID = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
_URL = re.compile(r'https?://(?:\[private (?:phone|credential)\]|[^\s<>"\'])+', re.IGNORECASE)


def _job_identifier_spans(host, path):
    pattern = None
    keys = set()
    if host in {'job-boards.greenhouse.io', 'boards.greenhouse.io'}:
        pattern = rf'/{_SLUG}/jobs/([0-9]{{1,15}})/?'
        keys = {'gh_jid'}
    elif host == 'jobs.ashbyhq.com':
        pattern = rf'/{_SLUG}/({_UUID})/?'
    elif host == 'jobs.lever.co':
        pattern = rf'/{_SLUG}/({_UUID})/?'
    elif host in {'www.indeed.com', 'ca.indeed.com', 'indeed.com'}:
        if path == '/viewjob': keys = {'jk'}
    elif re.fullmatch(r'[a-z0-9-]+\.taleo\.net', host):
        if re.fullmatch(rf'/careersection/{_SLUG}/jobdetail\.ftl', path): keys = {'job'}
    elif re.fullmatch(r'[a-z0-9-]+\.wd[0-9]{1,2}\.myworkdayjobs\.com', host):
        pattern = rf'/(?:[a-z]{{2}}-[A-Z]{{2}}/)?{_SLUG}/job/{_SLUG}/{_SLUG}_([A-Za-z]{{0,8}}[0-9]{{1,15}})/?'
    spans = []
    if pattern:
        match = re.fullmatch(pattern, path)
        if not match: return [], set()
        spans.append(match.span(1))
    return spans, keys


def _sanitize_url(match):
    original = match.group()
    try:
        parsed = urlsplit(original)
        host = parsed.hostname or ''
        valid = (parsed.scheme in {'http', 'https'} and not parsed.username and
                 not parsed.password and parsed.netloc.lower() == host and '%' not in parsed.path)
        spans, keys = _job_identifier_spans(host, parsed.path) if valid else ([], set())
    except ValueError:
        return _mask_text(unquote(original))
    # Preserve only validated identifiers, not the rest of a trusted host's URL.
    protected = []
    def protect(value):
        marker = 'JOBIDENTIFIER' + ('X' * (len(protected) + 1)) + 'TOKEN'
        while marker in original or any(marker == saved for saved, _ in protected): marker += 'X'
        protected.append((marker, value))
        return marker
    path = parsed.path
    for start, end in reversed(spans): path = path[:start] + protect(path[start:end]) + path[end:]
    path_decoded = unquote(path)
    path_masked = _mask_text(path_decoded)
    if path_masked != path_decoded: path = path_masked
    def query_value(m):
        key, value = m.group(1), m.group(2)
        if re.sub(r'[^a-z0-9]', '', unquote_plus(key).lower()) in _SECRET_PARAMETERS:
            return key + '=[private credential]'
        if key in keys and re.fullmatch(_ID, value) and _mask_credentials(value)==value: return key + '=' + protect(value)
        decoded = unquote_plus(value)
        masked = _mask_text(decoded)
        return key + '=' + (masked if masked != decoded else value)
    query = re.sub(r'([^&=]+)=([^&]*)', query_value, parsed.query)
    fragment = parsed.fragment
    decoded = unquote(fragment)
    # Filter routes, parameter names and trailing text as well as values.
    parts = []
    end = 0
    for parameter in re.finditer(r'([^&=]+)=([^&]*)', decoded):
        key = parameter.group(1)
        parts.extend((_mask_text(decoded[end:parameter.start()]),
                      _mask_text(key) + query_value(parameter)[len(key):]))
        end = parameter.end()
    parts.append(_mask_text(decoded[end:]))
    masked = ''.join(parts)
    if masked != decoded: fragment = masked
    # Replace components in the original string to retain separators, query order and encoding.
    prefix = original[:original.find(parsed.path, len(parsed.scheme) + 3)] if parsed.path else original.split('?', 1)[0].split('#', 1)[0]
    if parsed.username is not None or parsed.password is not None:
        prefix = re.sub(r'(?<=//)[^/]*@', '[private phone]@', prefix)
    result = prefix + path
    if '?' in original.split('#', 1)[0]: result += '?' + query
    if '#' in original: result += '#' + fragment
    result = _mask_phone(result)
    for marker, value in protected: result = result.replace(marker, value)
    return result


def sanitize_text(text):
    # Process URL tokens separately so phone-shaped identifiers have bounded context.
    parts = []
    end = 0
    for match in _URL.finditer(text):
        parts.extend((_mask_text(text[end:match.start()]), _sanitize_url(match)))
        end = match.end()
    parts.append(_mask_text(text[end:]))
    return ''.join(parts)


def sanitize(value):
    if isinstance(value,dict):
        return {k: (v if k in {'requisition', 'job_id', 'jobID', 'jobId', 'posting_id'}
                    and isinstance(v, str) and re.fullmatch(_ID, v) and _mask_credentials(v)==v else sanitize(v))
                for k,v in value.items() if k not in {'phone','phone_history'} and not _secret_field(k)}
    if isinstance(value,list): return [sanitize(v) for v in value]
    if isinstance(value,str): return sanitize_text(value)
    return value
