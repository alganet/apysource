# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Run configurable source verification checks."""

import json
import sys
from pathlib import Path

from rdflib import Graph

from apysource.api import check_graph
from apysource.documents import DEFAULT_MAX_BYTES
from apysource.cli._base import CLIContext, UsageError, pop_flag, pop_value
from apysource.graph import load_triples
from apysource.http import CachedFetcher
from apysource.repos import RepoRegistry
from apysource.verification import failed, json_report, print_report


class CheckSourcesCommand:
    """Verify all configured checks against a sources graph.

    Resolves each fragment/term, extracts its cited content, and confirms the
    snippet is present, printing a pass/fail report and exiting non-zero on
    any failure. Accepts ``--refresh`` (re-fetch and re-crawl, bypassing the
    caches), ``--strict-redirects`` (fail, rather than warn, on a source URL
    that has moved), ``--strict-repos`` (fail on a repo that claimed a URL but
    could not serve it), ``--strict-supersession`` (fail on a citation into a
    document its publisher has replaced), ``--no-crawl`` (never fetch a repo
    document that is
    not already cached), ``--format json`` (a machine-readable report; stdout
    then carries only JSON) and ``--provenance <file>`` (write a PROV-O graph).
    """

    #: Opt in to YAML-graph input: ``check`` may take a sources file as its
    #: first positional argument (see ``cli.__main__``).
    accepts_graph = True

    #: Flags whose next argument is a value (see ``cli.__main__``). The first two
    #: take a `.ttl`, so without this `check --provenance run.ttl sources.yaml`
    #: loaded `run.ttl` as the graph to check and wrote provenance over
    #: `sources.yaml`. `--workers` is here for the same reason and a blunter one:
    #: `check --workers 8 sources.yaml` would otherwise try to load `8` as the
    #: graph.
    value_flags = ("--format", "--provenance", "--workers")

    def __init__(self, ctx: CLIContext, registry: RepoRegistry,
                 fetcher: CachedFetcher | None = None,
                 document_cache_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.ctx = ctx
        self.registry = registry
        self.fetcher = fetcher
        self.document_cache_bytes = int(document_cache_bytes)

    def run(self, graph: Graph | None = None, args: list[str] | None = None,
            vetted: bool = False) -> None:
        """Run the configured checks and exit 1 if any fragment fails."""
        if args is None:
            args = []

        # Parse --refresh flag (re-fetch sources, bypassing the HTTP cache)
        force, args = pop_flag(args, "--refresh")

        # A moved source URL warns by default; --strict-redirects fails on it.
        strict_redirects, args = pop_flag(args, "--strict-redirects")

        # A repo that claimed a URL but could not serve it warns by default:
        # the snippet was still checked, but against the fetched page rather
        # than the repository the citation names. --strict-repos fails on it.
        strict_repos, args = pop_flag(args, "--strict-repos")

        # A citation into a document its publisher has replaced warns by
        # default: the quote is genuinely there, and citing a superseded
        # document is sometimes the only option — the successor may have
        # deleted the very thing being described. --strict-supersession fails
        # on it, for a collection that means to track only documents in force.
        strict_supersession, args = pop_flag(args, "--strict-supersession")

        # --no-crawl refuses to fetch a repo document that is not cached,
        # reporting the miss instead of quietly fetching a different document.
        no_crawl, args = pop_flag(args, "--no-crawl")

        try:
            fmt, args = pop_value(args, "--format")
            prov, args = pop_value(args, "--provenance")
            workers, args = pop_value(args, "--workers")
        except UsageError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # How many documents may be in flight. The polite delay is enforced per
        # host, so this parallelises a run across the sites it cites and never
        # within one of them.
        if workers is not None:
            try:
                count = int(workers)
            except ValueError:
                print(f"Error: --workers takes a number, not {workers!r}",
                      file=sys.stderr)
                sys.exit(1)
            if count < 1:
                print("Error: --workers must be at least 1", file=sys.stderr)
                sys.exit(1)
            if self.fetcher is None:
                # Having bothered to reject `--workers 0` and `--workers abc`,
                # accepting a good value and quietly dropping it is the one
                # outcome that leaves the user with nothing to go on — they wait
                # out a serial run believing it is parallel.
                print("Error: --workers needs an HTTP client, and this "
                      "configuration has none. Sources served entirely by repos "
                      "are crawled through those instead.", file=sys.stderr)
                sys.exit(1)
            self.fetcher.workers = count

        if fmt is not None and fmt != "json":
            print(f"Error: unknown --format {fmt!r} (only 'json')", file=sys.stderr)
            sys.exit(1)

        as_json = fmt == "json"
        prov_path = Path(prov) if prov else None

        if graph is not None:
            g = graph
            # `vetted` means it came through `graph_from_data`, the stricter gate
            # of the two: it has already refused everything SHACL would catch
            # here, and more besides. Running the shapes over it again buys
            # nothing and costs a pyshacl import on the path everybody runs.
            #
            # A `.ttl` argument also arrives as a graph, and that one is *not*
            # vetted — nothing has looked at it — so it is checked like any other
            # Turtle. Reading this off `graph is not None` would have skipped
            # precisely the input that needs it most.
            check_shapes = not vetted
        else:
            # stderr, so that --format json leaves stdout carrying only JSON.
            print("\n  Loading RDF...", file=sys.stderr)
            g = load_triples(self.ctx.rdf_root)
            # Turtle has no loader. `load_triples` parses and hands back whatever
            # it read, so the shapes are the only thing standing between a
            # malformed citations graph and a report about it.
            check_shapes = True

        emit_prov = prov_path is not None
        results = check_graph(g, registry=self.registry, fetcher=self.fetcher,
                              emit_provenance=emit_prov, force=force,
                              strict_redirects=strict_redirects,
                              strict_repos=strict_repos,
                              strict_supersession=strict_supersession,
                              crawl=not no_crawl,
                              validate_shapes=check_shapes,
                              document_cache_bytes=self.document_cache_bytes)

        prov_graph = None
        if isinstance(results, tuple):
            results, prov_graph = results

        if as_json:
            report = json_report(results)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print_report(results)

        # One rule, shared by both renderers, so a CI job and a human are never
        # told different things about the same run — including the run that
        # checked nothing at all, which used to be reported as a pass.
        failure = failed(results)

        if prov_path and prov_graph:
            prov_path.write_text(
                prov_graph.serialize(format="turtle"),
                encoding="utf-8",
            )
            print(f"\n  Provenance written to {prov_path}", file=sys.stderr)

        sys.exit(1 if failure else 0)
