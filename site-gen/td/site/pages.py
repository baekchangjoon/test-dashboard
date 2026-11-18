"""사이트 페이지 공통 보조(Task 6이 최소분을 만들고 Task 7이 확장한다)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

SITE_DIR = Path(__file__).parent
TEMPLATES_DIR = SITE_DIR / "templates"
STATIC_DIR = SITE_DIR / "static"


def slug(test_id: str) -> str:
    """testId -> 파일 이름에 안전한 결정적 슬러그(sha1 앞 10자). `#`, 한글 등 어떤 문자도 안전하다."""
    return hashlib.sha1(test_id.encode("utf-8")).hexdigest()[:10]


def jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html", "j2"]),
                       trim_blocks=True, lstrip_blocks=True)


def json_for_script(data) -> str:
    """`<script type="application/json">` 안에 안전하게 넣을 JSON(`</script>` 탈출 방지)."""
    import json
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
