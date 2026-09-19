"""The two ends of the content contract must agree on the slot categories (R8).

``CATEGORY_ORDER`` in ``web/js/catalog.js`` is the web version's copy of
``dressup_pipeline.models.CATEGORIES``: the pipeline writes each Item's category,
the page groups the supply by it in that order. Nothing notices at runtime when
the two drift — a category the page has never heard of quietly falls to the end
of the supply instead of failing — so the copy is read back out of the source
and compared here. A literal scan, like test_plain_build_purity: no browser.
"""

from __future__ import annotations

import re

from dressup_pipeline.models import CATEGORIES

from tests.web.conftest import WEB_DIR

CATEGORY_ORDER = re.compile(r"CATEGORY_ORDER\s*=\s*Object\.freeze\(\[(.*?)\]\)", re.DOTALL)


def test_the_page_lists_the_pipelines_categories_in_the_pipelines_order():
    source = (WEB_DIR / "js" / "catalog.js").read_text(encoding="utf-8")

    match = CATEGORY_ORDER.search(source)

    assert match, "web/js/catalog.js has no CATEGORY_ORDER = Object.freeze([...]) to read"
    assert re.findall(r'"([^"]+)"', match.group(1)) == list(CATEGORIES)
