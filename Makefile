.PHONY: install mirror mirror-retry dist safe audit serve-dist all release release-dryrun clean help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install dependencies with uv
	uv sync

mirror: ## Download a faithful raw copy of the archive into mirror/ (~30-45 min)
	@echo '──────────────────────────────────────────────────────────────'
	@echo ' make mirror — faithful raw archive crawl'
	@echo ''
	@echo ' Fetches the archive.org snapshot via the Wayback "id_" form and'
	@echo ' saves the ORIGINAL HTML + image assets to mirror/ byte-for-byte.'
	@echo ' No link rewriting, no conversion: this is the source of truth.'
	@echo ''
	@echo ' EXPECT ~30-45 MINUTES. ~300 resources at a polite 2-4s delay.'
	@echo ' archive.org throttles bursts; the crawler backs off and retries,'
	@echo ' and saves state every few pages — so it is safe to Ctrl-C and'
	@echo ' re-run: it resumes from where it stopped. To recover URLs that'
	@echo ' failed on a throttled run, use: make mirror-retry'
	@echo '──────────────────────────────────────────────────────────────'
	uv run python scripts/mirror.py

mirror-retry: ## Re-queue and retry URLs that failed during a throttled crawl
	uv run python scripts/mirror.py --retry-failed

dist: ## Build the browsable, link-fixed static site into dist/ from mirror/
	@test -d mirror || { echo "mirror/ not found — run 'make mirror' first."; exit 1; }
	uv run python scripts/build_site.py

safe: ## Build dist/, then strip copyrighted lyrics for safe public hosting
	@$(MAKE) dist
	uv run python scripts/safe_build.py

audit: ## Audit link health of the built dist/ site
	@test -d dist || { echo "dist/ not found — run 'make dist' first."; exit 1; }
	uv run python scripts/audit_links.py dist

serve-dist: ## Serve the built dist/ site locally at http://localhost:8000
	@test -d dist || $(MAKE) dist
	@echo 'Serving dist/ at http://localhost:8000 (Ctrl-C to stop)'
	uv run python -m http.server 8000 --directory dist

all: ## Full pipeline: mirror (only if missing) -> build -> audit -> serve
	@if [ ! -d mirror ] || [ -z "$$(ls -A mirror 2>/dev/null)" ]; then $(MAKE) mirror; \
	 else echo "mirror/ present — skipping crawl (run 'make mirror' to refresh)"; fi
	@$(MAKE) dist
	@$(MAKE) audit
	@$(MAKE) serve-dist

release: ## Tag a semver release from conventional commits (pushes tag, triggers CI release)
	@./scripts/release.sh $(VERSION)

release-dryrun: ## Preview the next release version + changelog without tagging
	@./scripts/release.sh --dry-run $(VERSION)

clean: ## Remove build artifacts (dist/, logs, caches) — mirror/ is kept
	rm -rf dist/
	rm -f mirror.log
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
