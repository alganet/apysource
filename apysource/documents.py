# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""One document, read once and extracted once, for the length of a run.

A citation names a place in a document, and a document is usually named by more
than one citation. Nothing here changes what is checked; it changes how many
times the same bytes are turned into the same text before checking it.

The cost this removes is not small. Verification loads every fragment twice —
once to say the extraction is non-empty, once to look for the snippet — and each
load re-read the file, re-detected the format, and re-parsed it. On a page cited
by a hundred fragments that is two hundred parses of one document, and for HTML
each one is a full BeautifulSoup tree.

**It is injected, never global.** ``run_checks`` builds one and passes it down;
``load_text`` takes ``cache=None`` and then behaves exactly as it always did.
That is deliberate: a module-level memo would outlive the run that filled it, so
two checks of the same URL in one process — a test suite, a long-lived
generator — could be answered from a document fetched before the change anybody
was trying to detect. A cache with a lifetime is a cache you can reason about.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, TypeVar

from apysource.formats import default_formats
from apysource.http import document_url
from apysource.results import FetcherResult, RepoResult, ResolveResult

T = TypeVar("T")

#: Roughly how much extracted and raw text one run may hold on to. A budget in
#: bytes rather than in entries, because the entries are documents and documents
#: differ in size by four orders of magnitude — a thousand-entry cap means eight
#: megabytes of RFCs or eight gigabytes of book scans.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def document_key(result: ResolveResult) -> str | None:
    """What identifies the document this result names, or None if nothing does.

    For a fetched source it is the *document* URL — the fragment stripped off,
    exactly as ``CachedFetcher`` keys its own cache, so two citations into
    ``rfc9110.html`` at different anchors are recognised as one document here for
    the same reason they are one download there.

    For a repo-backed source the location is part of the identity, not incidental
    to it: ``repo.extract_content(location, path)`` slices the file by chapter or
    by line range, so two fragments naming different locations in one file are
    genuinely different texts and must not share an entry.
    """
    if isinstance(result, FetcherResult):
        return f"url:{document_url(result.url)}"
    if isinstance(result, RepoResult):
        return f"repo:{result.module}:{result.key}:{result.location}"
    return None


class _Memo:
    """An LRU bounded by both bytes and entry count, safe to share across threads.

    **Two bounds, because one is not enough.** A byte budget alone cannot see the
    entries that matter most on a failing run: a fetch that came back ``None``,
    or any of the ``unavailable`` / ``not_found`` / ``no_section`` / ``empty``
    outcomes, measures zero. Those never push ``_bytes`` past the budget, so the
    eviction loop never reaches them — and a large codebase whose citations have
    drifted produces thousands of exactly those. The dict would grow without
    limit while reporting almost no bytes held.

    **Locked, because a worker reaches it.** ``prefetch`` warms documents from a
    thread pool, so ``get`` runs concurrently. ``self._bytes += size`` is a
    read-modify-write with a thread-switch boundary in the middle; a lost update
    makes the counter under-report, the eviction stop firing, and the budget
    silently fail to hold. The GIL hides this on CPython today and the project
    supports 3.13, where a free-threaded build does not. The lock costs nothing
    next to the fetch it guards, and it also makes "miss, then produce" one
    decision rather than two, so two threads cannot both produce the same key.
    """

    def __init__(self, max_bytes: int, max_entries: int,
                 size_of: Callable[[Any], int]) -> None:
        self._max_bytes = max_bytes
        self._max_entries = max(1, max_entries)
        self._size_of = size_of
        self._entries: OrderedDict[Any, Any] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Any, produce: Callable[[], T]) -> T:
        with self._lock:
            try:
                value = self._entries[key]
            except KeyError:
                pass
            else:
                self._entries.move_to_end(key)
                return value  # type: ignore[no-any-return]

        # Produced outside the lock: this fetches documents and parses them, and
        # holding a lock across it would serialize the very work the workers are
        # there to overlap. Two threads racing on one key both produce, and the
        # second simply replaces an equal value — `produce` is a pure read of
        # the same document either way.
        value = produce()
        size = self._size_of(value)

        with self._lock:
            # A single document bigger than the whole budget is served and
            # dropped. Storing it would evict everything else to hold one thing.
            if size > self._max_bytes:
                return value

            if key in self._entries:
                self._bytes -= self._size_of(self._entries.pop(key))
            self._entries[key] = value
            self._bytes += size

            while (len(self._entries) > self._max_entries
                   or self._bytes > self._max_bytes) and len(self._entries) > 1:
                _, evicted = self._entries.popitem(last=False)
                self._bytes -= self._size_of(evicted)

        return value

    @property
    def stored_bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._entries)


def _text_size(value: Any) -> int:
    text = getattr(value, "text", value)
    return len(text) if isinstance(text, str) else 0


#: How many parsed HTML documents to keep. Small on purpose — a tree is several
#: times the size of its source and there is no cheap way to weigh one, so this
#: is bounded by count and kept low. Citations of a page arrive together, so the
#: window only has to span one document's worth of fragments.
SOUP_CACHE_DOCUMENTS = 4

#: How many extractions and bodies to hold, regardless of how small they are.
#: See ``_Memo``: a failing run produces zero-size entries by the thousand, and
#: a byte budget cannot see them.
DEFAULT_MAX_ENTRIES = 4096


class _SoupCache:
    """The ``{body: parsed tree}`` mapping ``HtmlFormat`` is given.

    A thin adapter over ``_Memo`` rather than a ``dict`` subclass. Subclassing
    ``dict`` and overriding only ``__setitem__`` advertises an interface where
    ``update``, ``setdefault`` and ``|=`` all write straight past the bound —
    and the thing being bounded is a full document plus a parse tree, which is
    the one entry you cannot afford to leak. Exposing two methods that are
    actually implemented is smaller and cannot be got wrong.
    """

    def __init__(self, limit: int) -> None:
        # Trees cannot be weighed cheaply, so the byte budget is left wide open
        # and the entry count is what does the work.
        self._memo = _Memo(max_bytes=2**62, max_entries=limit,
                           size_of=lambda _: 0)

    def get(self, body: str, produce: Callable[[], Any]) -> Any:
        return self._memo.get(body, produce)

    def __len__(self) -> int:
        return len(self._memo)


class DocumentCache:
    """Per-run memo for document bodies and the texts extracted from them."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES,
                 max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        # Two budgets rather than one shared pot, so a run over many small
        # extractions cannot be starved by the raw bodies they came from.
        self._bodies = _Memo(max_bytes // 2, max_entries, _text_size)
        self._extractions = _Memo(max_bytes // 2, max_entries, _text_size)
        self._forced: set[str] = set()
        # `claim_force` is a check-then-act, and prefetch calls it from workers.
        # Deduping by document means two threads never present the same key
        # today; a lock costs nothing and does not depend on that staying true.
        self._forced_lock = threading.Lock()

        #: An HTML parse costs far more than the text it yields, and a page with
        #: five citations was parsed five times. Bounded hard and separately from
        #: the text budget: a BeautifulSoup tree is several times the size of the
        #: document, and unlike text it cannot be measured cheaply. Citations of
        #: one page arrive together — fragments are walked in sorted order, and
        #: sources file order clusters them — so a very small window catches
        #: almost all of it.
        self._soups = _SoupCache(SOUP_CACHE_DOCUMENTS)
        self.formats = default_formats(soup_cache=self._soups)

    def body(self, key: str, produce: Callable[[], T]) -> T:
        """The document's raw text, fetched or read at most once per run."""
        return self._bodies.get(key, produce)

    def extraction(self, key: Any, produce: Callable[[], T]) -> T:
        """The text a given targetting extracts, computed at most once per run."""
        return self._extractions.get(key, produce)

    def claim_force(self, key: str) -> bool:
        """Is this the call that gets to do the forced re-fetch?

        ``--refresh`` is asked for once per *fragment*, and it deletes the cached
        body before re-fetching. Twenty fragments citing one page therefore
        deleted and re-downloaded that page twenty times — twenty requests where
        the citation count should not have been visible to the server at all, and
        nineteen of them impolite. The first caller refreshes; the rest read what
        it fetched, which is the same document and the answer they would have got.
        """
        with self._forced_lock:
            if key in self._forced:
                return False
            self._forced.add(key)
            return True

    @property
    def stored_bytes(self) -> int:
        return self._bodies.stored_bytes + self._extractions.stored_bytes
