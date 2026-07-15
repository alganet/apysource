import apysource.cli._base
import apysource.cli.add
import apysource.cli.check_sources
import apysource.cli.locate
import apysource.cli.validate
import apysource.http
import apysource.repos
import apysource.repos.archive
import apysource.repos.gutenberg
import apysource.repos.mdn
import apysource.repos.wikisource
import apysource.repos.wiktionary

class Compiled:

    def ctx(self):
        if not hasattr(self, '_ctx'):
            self._ctx = apysource.cli._base.CLIContext(project_root=self.project_root(), rdf_subdir=self.rdf_subdir(), sources_cache_subdir=self.sources_cache_subdir())
        return self._ctx

    def http_client(self):
        if not hasattr(self, '_http_client'):
            self._http_client = apysource.http.CachedFetcher(cache_dir=self.http_cache_dir(), default_delay=self.default_crawl_delay(), default_timeout=self.default_http_timeout())
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
            self._registry = apysource.repos.RepoRegistry(repos=[self.repo_archive(), self.repo_gutenberg(), self.repo_mdn(), self.repo_wikisource(), self.repo_wiktionary()], sources_cache_dir=self.sources_cache_subdir(), http_client=self.http_client(), default_crawl_delay=self.default_crawl_delay())
        return self._registry

    def check_sources_cmd(self):
        if not hasattr(self, '_check_sources_cmd'):
            self._check_sources_cmd = apysource.cli.check_sources.CheckSourcesCommand(ctx=self.ctx(), registry=self.registry(), fetcher=self.http_client())
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
compiled = Compiled()
