# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""apysource — cache-based source verification for RDF-annotated projects.

What a caller is meant to reach for, named here so it does not have to guess —
and so that the README's import line is one that actually runs.
"""

#: Declared before the re-exports below, and it has to be: ``http`` reads it back
#: off this package to build its User-Agent, so importing the API first would
#: close the loop on a module that is still executing.
__version__ = "0.6.0"

from apysource.api import check_graph  # noqa: E402
from apysource.emit import serialize  # noqa: E402
from apysource.patterns import SourcePattern, mint_source, patterns_from_data  # noqa: E402
from apysource.sources import SourceSet, load_sources, sources_from_data  # noqa: E402
from apysource.yaml_input import graph_from_data, load_yaml  # noqa: E402

__all__ = [
    "SourcePattern",
    "SourceSet",
    "__version__",
    "check_graph",
    "graph_from_data",
    "load_sources",
    "load_yaml",
    "mint_source",
    "patterns_from_data",
    "serialize",
    "sources_from_data",
]
