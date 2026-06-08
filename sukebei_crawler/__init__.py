from pathlib import Path

_src_package = Path(__file__).resolve().parent.parent / "src" / "sukebei_crawler"
__path__.append(str(_src_package))
