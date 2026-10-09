"""Reviewed terminology equivalences only. No product, metric, role, or claim rewrites."""
import re

EQUIVALENCES = (
    ('retrieval-augmented generation','RAG'),
    ('Model Context Protocol','MCP'),
    ('continuous integration and continuous delivery','CI/CD'),
    ('large language models','LLMs'),
    ('large language model','LLM'),
    ('application programming interfaces','APIs'),
    ('application programming interface','API'),
)


def pattern(term): return r'(?<!\w)'+re.escape(term)+r'(?!\w)'


def tailor(fact,posting):
    original=fact['text'];rendered=original;ledger=[]
    for expanded,short in EQUIVALENCES:
        has_expanded=bool(re.search(pattern(expanded),posting,re.I))
        has_short=bool(re.search(pattern(short),posting,re.I))
        if has_expanded==has_short: continue  # No preference, or no equivalent wording in the posting.
        target=expanded if has_expanded else short
        combined=pattern(expanded)+r'\s*\('+re.escape(short)+r'\)'
        combined_reverse=pattern(short)+r'\s*\('+re.escape(expanded)+r'\)'
        source=short if has_expanded else expanded
        expression=combined+'|'+combined_reverse+'|'+pattern(source)
        def replace(match):
            before=match.group()
            ledger.append(dict(before=before,after=target,reason='Reviewed identical terminology: '+expanded+' / '+short))
            return target
        rendered=re.sub(expression,replace,rendered,flags=re.I)
    if re.findall(r'\d+(?:\.\d+)?',original)!=re.findall(r'\d+(?:\.\d+)?',rendered): raise ValueError('Terminology substitution changed numeric evidence')
    return dict(fact_id=fact['id'],original=original,rendered=rendered,substitutions=ledger)
