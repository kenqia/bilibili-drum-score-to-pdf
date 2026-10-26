"""Explicit website-only heart policy; no inference from emoji names or glyphs."""
from contextlib import contextmanager
from contextvars import ContextVar

# Frozen policy v1. Includes heart ornaments; excludes faces, hands, letters
# and the anatomical heart. Variation selectors and ZWJ forms contain a base.
HEARTS = frozenset('♡♥❤❣❥☙❦❧🎔💓💔💕💖💗💘💙💚💛💜💝💞💟🖤🤍🤎🧡🩷🩵🩶')
enabled = ContextVar('website_description_policy', default=False)
last_details = ContextVar('website_source_details', default=None)


@contextmanager
def website_policy(active=True):
    token = enabled.set(active)
    details_token = last_details.set(None)
    try:
        yield
    finally:
        last_details.reset(details_token)
        enabled.reset(token)


def check(description, origin):
    if not enabled.get():
        return None
    valid = isinstance(description, str)
    matched = sorted(set(description) & HEARTS) if valid else []
    result = {'rule': 'description_hearts_v1', 'valid_description': valid,
              'matched': bool(matched), 'codepoints': [f'U+{ord(value):04X}' for value in matched]}
    last_details.set({'url': origin['url'], 'description_policy': result})
    if matched:
        from .public_video import InputError
        raise InputError('description_policy_rejected', '该视频暂不支持整理。',
                         {**origin, 'description_policy': result})
    return result
