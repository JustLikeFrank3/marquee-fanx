"""Match source genre labels, never infer a genre from an artist name."""
import re

def canonical(value):
    return ' '.join(re.findall(r'\w+', value.casefold()))

# Equivalent spellings only: do not broaden punk rock to all rock, for example.
ALIASES = {'punk rock':'punk', 'hip hop':'hip hop', 'r b':'rnb', 'r and b':'rnb',
           'rhythm and blues':'rnb', 'edm':'electronic dance music'}

def key(value):
    name=canonical(value)
    return ALIASES.get(name,name)

def labels(raw):
    return [{'performer':p.get('name','Unknown performer'),'name':g['name'],'slug':g.get('slug','')}
            for p in raw.get('performers',[]) or [] for g in p.get('genres',[]) or []
            if isinstance(g,dict) and isinstance(g.get('name'),str) and g['name'].strip()]

def matches(raw, requested):
    return any(key(want) in {key(g['name']),key(g['slug'])} for want in requested for g in labels(raw))

def query_genres(query):
    known={'punk','punk rock','rock','indie','indie rock','jazz','pop','techno','hard techno',
           'electronic','edm','hip hop','rap','country','metal','folk','soul','rnb','r b','classical'}
    parts=re.split(r'\s+(?:or|and)\s+|,|/',query.strip().casefold())
    return parts if parts and all(canonical(p) in known for p in parts) else []
