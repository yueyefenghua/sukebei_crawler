from __future__ import annotations

from sukebei_crawler.config import parse_simple_yaml
from sukebei_crawler.parser import parse_listing
from sukebei_crawler.product_code import extract_product_code
from sukebei_crawler.size import parse_size_to_bytes


def test_parse_size_to_bytes() -> None:
    assert parse_size_to_bytes("1 KiB") == 1024
    assert parse_size_to_bytes("1.5 MiB") == 1572864
    assert parse_size_to_bytes("2 GB") == 2_000_000_000
    assert parse_size_to_bytes("bad") is None


def test_parse_simple_yaml_subset() -> None:
    parsed = parse_simple_yaml(
        """
site:
  base_url: "https://example.com"
  enabled: true
query:
  filters:
    f: 2
    c: "2_0"
    q: "fhd"
conditions:
  title_include: []
"""
    )
    assert parsed["site"]["base_url"] == "https://example.com"
    assert parsed["site"]["enabled"] is True
    assert parsed["query"]["filters"]["f"] == 2
    assert parsed["conditions"]["title_include"] == []


def test_extract_product_code() -> None:
    assert extract_product_code("+++ [FHD] FNS-216 some title") == "FNS-216"
    assert extract_product_code("+++ [FHD] MKMP-734 other title") == "MKMP-734"
    assert extract_product_code("no code title") is None


def test_parse_listing_row_and_next_link() -> None:
    html = """
<table class="table torrent-list"><tbody>
<tr class="success">
  <td><a href="/?c=2_2" title="Real Life - Videos"><img></a></td>
  <td colspan="2"><a href="/view/1" title="+++ [FHD] FNS-216 Sample Title">+++ [FHD] FNS-216 Sample Title</a></td>
  <td class="text-center"><a href="/download/1.torrent"><i></i></a></td>
  <td class="text-center">1.5 GiB</td>
  <td class="text-center" data-timestamp="1">2026-06-08 10:00</td>
  <td class="text-center">10</td>
  <td class="text-center">2</td>
  <td class="text-center">300</td>
</tr>
</tbody></table>
<ul class="pagination"><li class="next"><a href="/?p=2">&raquo;</a></li></ul>
"""
    items, next_url = parse_listing(
        html,
        base_url="https://sukebei.nyaa.si",
        source_url="https://sukebei.nyaa.si/?q=fhd",
        site="https://sukebei.nyaa.si",
        search_query="fhd",
        query_params={"q": "fhd"},
    )
    assert len(items) == 1
    assert items[0].title == "+++ [FHD] FNS-216 Sample Title"
    assert items[0].product_code == "FNS-216"
    assert items[0].detail_url == "https://sukebei.nyaa.si/view/1"
    assert items[0].torrent_url == "https://sukebei.nyaa.si/download/1.torrent"
    assert items[0].completed_downloads == 300
    assert next_url == "https://sukebei.nyaa.si/?p=2"
