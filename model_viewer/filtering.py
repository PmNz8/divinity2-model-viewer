"""Case-insensitive logical-path filters; no filesystem glob expansion."""
from fnmatch import translate
import re


def path_filter(query):
    query = query.casefold().replace('\\', '/')
    if not any(char in query for char in '*?'):
        return lambda path: query in path.casefold().replace('\\', '/')
    pattern = re.compile(translate(query))
    def matches(path):
        path = path.casefold().replace('\\', '/')
        return bool(pattern.fullmatch(path) or pattern.fullmatch(path.rsplit('/', 1)[-1]))
    return matches
