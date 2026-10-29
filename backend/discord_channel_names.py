"""Readable personal channel names, independent of the Discord account ID."""
import re
import unicodedata


def personal_channel_name(full_name, *, fallback_name='', existing_names=()):
    person = (full_name or '').strip() or fallback_name.strip() or 'personi'
    occupied = set(existing_names)

    def slug(value):
        plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
        return re.sub(r'[^a-z0-9]+', '-', plain).strip('-')

    first = slug(re.split(r'[\s.]+', person)[0]) or 'personi'
    base = 'primeflow-' + first
    for value in (first, slug(person), slug(fallback_name)):
        if value:
            candidate = ('primeflow-' + value)[:100].rstrip('-')
            if candidate not in occupied:
                return candidate
    suffix = 2
    while f'{base[:90]}-{suffix}' in occupied:
        suffix += 1
    return f'{base[:90]}-{suffix}'
