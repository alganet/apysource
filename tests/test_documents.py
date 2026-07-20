# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The per-run document cache: what it holds, and what bounds it."""



class TestTheMemoIsBoundedBothWays:
    """A byte budget alone cannot see the entries a failing run produces."""

    def test_zero_size_entries_are_still_evicted(self):
        """The gap a byte budget cannot close.

        A failed fetch and every empty extraction measure zero, so they never
        push the byte counter past its budget and the eviction loop never
        reaches them. On a large codebase whose citations have drifted, those
        are most of the entries — the cache would grow without limit while
        reporting almost nothing held.
        """
        from apysource.documents import _Memo

        memo = _Memo(max_bytes=10**9, max_entries=8, size_of=lambda v: 0)
        for i in range(500):
            memo.get(f"failed-{i}", lambda: None)

        assert len(memo) <= 8
        assert memo.stored_bytes == 0

    def test_the_byte_budget_still_holds_for_real_documents(self):
        from apysource.documents import _Memo

        memo = _Memo(max_bytes=1000, max_entries=10**6, size_of=len)
        for i in range(100):
            memo.get(f"doc-{i}", lambda: "x" * 300)

        assert memo.stored_bytes <= 1000

    def test_a_document_larger_than_the_budget_is_served_but_not_kept(self):
        from apysource.documents import _Memo

        memo = _Memo(max_bytes=100, max_entries=10, size_of=len)
        huge = memo.get("huge", lambda: "x" * 5000)

        assert huge == "x" * 5000
        assert len(memo) == 0

    def test_two_threads_racing_on_one_key_do_not_double_count_it(self):
        """`produce` runs outside the lock, so both may run for one key.

        That is deliberate — holding a lock across a fetch would serialize the
        work the workers exist to overlap — and it means the store path has to
        cope with the key already being there. Adding the size a second time
        would drift the counter up and start evicting entries that fit.
        """
        import threading

        from apysource.documents import _Memo

        memo = _Memo(max_bytes=10**9, max_entries=10, size_of=len)
        both_missed = threading.Barrier(2)

        def produce():
            both_missed.wait(timeout=5)      # guarantee both saw the miss
            return "x" * 100

        threads = [threading.Thread(target=lambda: memo.get("k", produce))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(memo) == 1
        assert memo.stored_bytes == 100

    def test_it_survives_being_reached_from_several_threads(self):
        """`prefetch` warms documents from a thread pool, so `get` is concurrent.

        The counter is a read-modify-write; a lost update makes it under-report
        and the budget silently stop holding. The GIL hides that on CPython
        today, and the project supports 3.13.
        """
        import threading

        from apysource.documents import _Memo

        memo = _Memo(max_bytes=10**9, max_entries=10**6, size_of=len)

        def work(worker):
            for i in range(300):
                memo.get(f"{worker}:{i}", lambda: "x" * 100)

        threads = [threading.Thread(target=work, args=(w,)) for w in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert memo.stored_bytes == len(memo) * 100


class TestTheRepoClaimMemoIsPerDocument:
    def test_anchors_share_one_entry(self):
        """A fragment names a place inside a document, not another document.

        Keyed on the URL as written, fifty citations of one page at fifty
        anchors were fifty entries and fifty regex scans — the fan-in shape the
        memo exists for was the one it helped least.
        """
        from apysource.repos import RepoRegistry

        registry = RepoRegistry([])
        for section in range(50):
            registry.get_repo(f"https://example.com/spec.html#section-{section}")

        assert len(registry._claims) == 1

    def test_the_answer_is_unchanged_by_an_anchor(self, tmp_path):
        from apysource.repos import RepoRegistry
        from tests.test_resolution import _make_mock_repo

        repo = _make_mock_repo(tmp_path)
        registry = RepoRegistry([repo])
        plain = registry.get_repo("https://example.com/doc/1")
        anchored = registry.get_repo("https://example.com/doc/1#part-2")

        assert plain is anchored
