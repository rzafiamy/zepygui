"""Incremental renders: send only the parts of the UI tree that changed.

After the first render of a window, each new tree is compared with the one the window
already shows, and the window receives a *patch* instead of the whole tree:

* an integer ``i`` means "keep old child number ``i`` exactly as it is";
* a dict with ``"o": i`` is an update of old child ``i`` (same tag and key); when it also
  has ``"d": 1`` its ``"c"`` list is itself a patch, otherwise ``"c"`` is a full list;
* anything else is a new node.

So typing into a field of a page that also shows a 5,000-row table sends a few hundred
bytes instead of megabytes, and the client never walks the rows that did not change.

Old children are paired with new ones the way the client always matched them: by key
when there is one, otherwise in order among the unkeyed children, and only when the tag
and key agree. The indices make the patch unambiguous, so the client does not have to
repeat that pairing.
"""
from __future__ import annotations


def _key(v):
    return v.get("k") if type(v) is dict else None


def _same(old, new):
    """Would ``old``'s node be reused for ``new``?"""
    if type(new) is str:
        return type(old) is str
    return type(old) is dict and old.get("t") == new.get("t") and old.get("k") == new.get("k")


def _pairs(olds, news):
    """For each new child, the index of the old child it updates (or None)."""
    keyed, unkeyed = {}, []
    for i, o in enumerate(olds):
        k = _key(o)
        if k is not None:
            keyed[k] = i  # duplicate keys: the last one wins
        else:
            unkeyed.append(i)
    used, u, out = set(), 0, []
    for v in news:
        k = _key(v)
        cand = None
        if k is not None:
            cand = keyed.get(k)
        elif u < len(unkeyed):
            cand = unkeyed[u]
            u += 1
        if cand is not None and cand not in used and _same(olds[cand], v):
            used.add(cand)
            out.append(cand)
        else:
            out.append(None)
    return out


def diff(old, new):
    """The patch that turns tree ``old`` into tree ``new`` (``new`` itself if ``old`` is None).

    The root is treated as the only child of the window, so an unchanged page diffs to ``0``.
    """
    if old is None:
        return new
    return _children([old], [new])[0]


def _children(olds, news):
    out = []
    for v, i in zip(news, _pairs(olds, news)):
        if i is None:
            out.append(v)
            continue
        o = olds[i]
        if o == v:  # deep comparison in C: far cheaper than encoding and patching the subtree
            out.append(i)
        elif type(v) is dict:
            out.append(_element(o, v, i))
        else:
            out.append(v)  # a changed text node
    return out


def _element(old, new, index):
    patched = dict(new)
    patched["o"] = index
    nc, oc = new.get("c"), old.get("c")
    if nc and oc and "h" not in old:
        patched["c"] = _children(oc, nc)
        patched["d"] = 1
    return patched


def apply(old, patch):
    """Rebuild the full tree from the previous tree and a patch (what the window does).

    Used by tests and tools; the window applies patches to the DOM directly."""
    if old is None:
        return patch
    return _apply_children([old], [patch])[0]


def _apply_children(olds, patches):
    out = []
    for p in patches:
        if type(p) is int:
            out.append(olds[p])
        elif type(p) is dict and "o" in p:
            node = {k: v for k, v in p.items() if k not in ("o", "d")}
            if p.get("d"):
                node["c"] = _apply_children(olds[p["o"]].get("c") or [], p["c"])
            out.append(node)
        else:
            out.append(p)
    return out
