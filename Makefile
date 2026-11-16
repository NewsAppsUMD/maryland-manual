PY ?= python3
DB = data/manual.db

.PHONY: help crawl crawl-mvp crawl-officials officials parse load peers site serve datasette test clean

help:
	@echo "Targets:"
	@echo "  crawl-mvp   Crawl the MVP slice (counties + departments + glance indexes)"
	@echo "  crawl       Full crawl (all in-scope pages)"
	@echo "  parse       Parse cached HTML -> records (implied by load)"
	@echo "  load        Parse + load records into $(DB)"
	@echo "  peers       Compute derived peer scores"
	@echo "  site        Build the static site into site/dist/"
	@echo "  serve       Serve the built site locally"
	@echo "  datasette   Open manual.db in Datasette (QA console)"
	@echo "  crawl-officials  Crawl roster pages + bios for the officials dataset"
	@echo "  officials   Build data/officials.csv and the officeholders table"
	@echo "  test        Run the test suite"

crawl-mvp:
	$(PY) -m crawler.crawl --profile mvp

crawl:
	$(PY) -m crawler.crawl --profile full

crawl-officials:
	$(PY) -m crawler.crawl --profile officials

officials:
	$(PY) -m graph.officials

load:
	$(PY) -m graph.load

peers: load
	$(PY) -m graph.peers

site: peers
	$(PY) site/build.py

serve:
	cd site/dist && $(PY) -m http.server 8000

datasette:
	datasette $(DB)

test:
	$(PY) -m pytest -q

clean:
	rm -f $(DB)
	rm -rf site/dist
