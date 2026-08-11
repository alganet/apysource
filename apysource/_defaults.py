import apysource.cli._base
import apysource.cli.add
import apysource.cli.check_sources
import apysource.cli.emit
import apysource.cli.locate
import apysource.cli.validate
import apysource.http
import apysource.repos
import apysource.repos.archive
import apysource.repos.gutenberg
import apysource.repos.mdn
import apysource.repos.rfc
import apysource.repos.wikisource
import apysource.repos.wiktionary

class Compiled:

    def emit_cmd(self):
        if not hasattr(self, '_emit_cmd'):
            self._emit_cmd = apysource.cli.emit.EmitCommand()
        return self._emit_cmd

    def ctx(self):
        if not hasattr(self, '_ctx'):
            self._ctx = apysource.cli._base.CLIContext(project_root=self.project_root(), rdf_subdir=self.rdf_subdir(), sources_cache_subdir=self.sources_cache_subdir())
        return self._ctx

    def http_client(self):
        if not hasattr(self, '_http_client'):
            self._http_client = apysource.http.CachedFetcher(cache_dir=self.http_cache_dir(), default_delay=self.default_crawl_delay(), default_timeout=self.default_http_timeout(), workers=self.default_http_workers(), retries=self.default_http_retries(), backoff_factor=self.default_http_backoff())
        return self._http_client

    def repo_archive(self):
        if not hasattr(self, '_repo_archive'):
            self._repo_archive = apysource.repos.archive.ArchiveRepo(url_pattern=self.archive_url_pattern(), base_url=self.archive_base_url())
        return self._repo_archive

    def repo_gutenberg(self):
        if not hasattr(self, '_repo_gutenberg'):
            self._repo_gutenberg = apysource.repos.gutenberg.GutenbergRepo(url_pattern=self.gutenberg_url_pattern(), base_url=self.gutenberg_base_url())
        return self._repo_gutenberg

    def repo_wikisource(self):
        if not hasattr(self, '_repo_wikisource'):
            self._repo_wikisource = apysource.repos.wikisource.WikisourceRepo(url_pattern=self.wikisource_url_pattern(), base_url=self.wikisource_base_url())
        return self._repo_wikisource

    def repo_wiktionary(self):
        if not hasattr(self, '_repo_wiktionary'):
            self._repo_wiktionary = apysource.repos.wiktionary.WiktionaryRepo(url_pattern=self.wiktionary_url_pattern(), base_url=self.wiktionary_base_url())
        return self._repo_wiktionary

    def repo_mdn(self):
        if not hasattr(self, '_repo_mdn'):
            self._repo_mdn = apysource.repos.mdn.MdnRepo(url_pattern=self.mdn_url_pattern(), base_url=self.mdn_base_url(), crawl_delay=self.mdn_crawl_delay())
        return self._repo_mdn

    def repo_rfc(self):
        if not hasattr(self, '_repo_rfc'):
            self._repo_rfc = apysource.repos.rfc.RfcRepo(url_pattern=self.rfc_url_pattern(), base_url=self.rfc_base_url(), draft_base_url=self.rfc_draft_base_url(), supersession_base_url=self.rfc_supersession_base_url())
        return self._repo_rfc

    def validate_cmd(self):
        if not hasattr(self, '_validate_cmd'):
            self._validate_cmd = apysource.cli.validate.ValidateCommand(ctx=self.ctx())
        return self._validate_cmd

    def locate_cmd(self):
        if not hasattr(self, '_locate_cmd'):
            self._locate_cmd = apysource.cli.locate.LocateCommand(http_client=self.http_client())
        return self._locate_cmd

    def add_cmd(self):
        if not hasattr(self, '_add_cmd'):
            self._add_cmd = apysource.cli.add.AddCommand(http_client=self.http_client())
        return self._add_cmd

    def registry(self):
        if not hasattr(self, '_registry'):
            self._registry = apysource.repos.RepoRegistry(repos=[self.repo_archive(), self.repo_gutenberg(), self.repo_mdn(), self.repo_rfc(), self.repo_wikisource(), self.repo_wiktionary()], sources_cache_dir=self.sources_cache_subdir(), http_client=self.http_client(), default_crawl_delay=self.default_crawl_delay())
        return self._registry

    def check_sources_cmd(self):
        if not hasattr(self, '_check_sources_cmd'):
            self._check_sources_cmd = apysource.cli.check_sources.CheckSourcesCommand(ctx=self.ctx(), registry=self.registry(), fetcher=self.http_client(), document_cache_bytes=self.default_document_cache_bytes())
        return self._check_sources_cmd

    def project_root(self):
        return '.'

    def rdf_subdir(self):
        return 'rdf'

    def sources_cache_subdir(self):
        return 'data/sources'

    def http_cache_dir(self):
        return 'data/cache'

    def default_crawl_delay(self):
        return 3.0

    def default_http_timeout(self):
        return 30

    def default_http_workers(self):
        return 8

    def default_http_retries(self):
        return 3

    def default_http_backoff(self):
        return 0.5

    def default_document_cache_bytes(self):
        return 67108864

    def archive_url_pattern(self):
        return 'archive\\.org/details/(.+?)(?:/|$|\\?|#)'

    def archive_base_url(self):
        return 'https://archive.org'

    def gutenberg_url_pattern(self):
        return 'gutenberg\\.org/ebooks/(\\d+)'

    def gutenberg_base_url(self):
        return 'https://www.gutenberg.org'

    def wikisource_url_pattern(self):
        return 'wikisource\\.org/wiki/(.+?)(?:\\?|#|$)'

    def wikisource_base_url(self):
        return 'https://en.wikisource.org'

    def wiktionary_url_pattern(self):
        return 'wiktionary\\.org/wiki/(.+?)(?:\\?|#|$)'

    def wiktionary_base_url(self):
        return 'https://en.wiktionary.org'

    def mdn_url_pattern(self):
        return 'developer\\.mozilla\\.org/(?i:en-US)/docs/([^#?\\s]+)'

    def mdn_base_url(self):
        return 'https://raw.githubusercontent.com/mdn/content/main/files'

    def mdn_crawl_delay(self):
        return 0.5

    def rfc_url_pattern(self):
        return '(?:rfc-editor\\.org/rfc|datatracker\\.ietf\\.org/doc/html|ietf\\.org/archive/id)/((?:rfc|bcp|std)\\d+|draft-[a-zA-Z0-9][a-zA-Z0-9.\\-]*?)(?:\\.[a-z]+)?(?:$|[/?#])'

    def rfc_base_url(self):
        return 'https://www.rfc-editor.org/rfc'

    def rfc_draft_base_url(self):
        return 'https://datatracker.ietf.org/doc/html'

    def rfc_supersession_base_url(self):
        return 'https://datatracker.ietf.org/api/v1'
compiled = Compiled()
