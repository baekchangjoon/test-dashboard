"""공통 띠(설계 §5.5): run 아래 모든 페이지 맨 위의 경로와 같은 run의 다른 리포트로 가는 메뉴.

직접 만드는 페이지는 템플릿(`base_v2.html.j2`)이 `render`의 결과를 그리고, 외부 도구가 만든 HTML은
사이트로 복사한 뒤 `inject`로 끼워 넣는다. 띠에는 스크립트가 없고, 스타일은 띠 안의 `<style>` 하나뿐이다.
높이가 고정이고 `position: static`이라 원래 화면을 가리지 않고 아래로 밀기만 한다.
링크는 모두 run 디렉터리 기준 상대 경로로 만들어 접두(`_test/...`) 아래에 게시해도 동작한다.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

# 단계 이름(시안 project.html의 "파이프라인 14단계")
STAGE_LABELS: dict[str, str] = {
    "S00": "준비",
    "S01": "기존 블랙박스 테스트",
    "S02": "bbtg 정적 분석",
    "S03": "jQA 온톨로지",
    "S04": "온톨로지 시각화",
    "S05": "OWL 온톨로지",
    "S06": "BDD 시나리오 생성",
    "S07": "생성 E2E 실행",
    "S08": "커버리지 집계",
    "S09": "hotspot 분석",
    "S10": "변경 영향 분석(TIA)",
    "S11": "SonarQube",
    "S12": "방식 비교",
    "S13": "게시",
}

# run 디렉터리 -> 사이트(접두) 루트: suts/<sut>/runs/<runId>/
_RUN_TO_ROOT = "../../../../"
# run 디렉터리 -> SUT 안내 페이지(바뀌지 않는 주소 suts/<sut>/index.html)
_RUN_TO_SUT = "../../index.html"

_BODY_OPEN = re.compile(r"<body[^>]*>", re.IGNORECASE)
_CURRENT = ' aria-current="page"'

# 띠 스타일: 외부 리포트는 app.css를 읽지 않으므로 색을 여기에 직접 둔다(값은 app.css의 토큰과 같다).
_STYLE = (
    ".tdnav{all:initial;box-sizing:border-box;display:block;position:static;"
    "height:40px;min-height:40px;max-height:40px;margin:0;padding:0;overflow:hidden;"
    "background:#fff;border-bottom:1px solid #d9dfe7;color:#465263;"
    "font:13px/40px \"Pretendard\",\"Apple SD Gothic Neo\",\"Malgun Gothic\",system-ui,sans-serif}"
    ".tdnav *{box-sizing:border-box}"
    ".tdnav-in{display:flex;align-items:center;gap:14px;height:40px;max-width:1240px;margin:0 auto;padding:0 16px}"
    ".tdnav a{color:#2a78d6;text-decoration:none}.tdnav a:hover{text-decoration:underline}"
    ".tdnav a:focus-visible{outline:2px solid #2a78d6;outline-offset:2px}"
    ".tdnav-crumbs{flex:0 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
    ".tdnav-sep{color:#6b7686;margin:0 6px}"
    ".tdnav-here{color:#131a24;font-weight:600}"
    ".tdnav-menu{flex:1 1 auto;min-width:0;display:flex;gap:4px;justify-content:flex-end;margin:0;padding:0;"
    "list-style:none;overflow-x:auto;white-space:nowrap;scrollbar-width:thin}"
    ".tdnav-menu li{display:inline;margin:0;padding:0}"
    ".tdnav-item{display:inline-block;line-height:24px;padding:0 9px;border:1px solid transparent;border-radius:999px}"
    ".tdnav-item[aria-current=page]{border-color:#2a78d6;color:#131a24;font-weight:600}"
    "@media (prefers-color-scheme:dark){.tdnav{background:#131a24;border-bottom-color:#263141;color:#b4bdc9}"
    ".tdnav a{color:#4a94ee}.tdnav-here,.tdnav-item[aria-current=page]{color:#e8edf3}"
    ".tdnav-item[aria-current=page]{border-color:#4a94ee}.tdnav-sep{color:#8490a0}}"
    "@media (max-width:640px){.tdnav-menu{display:none}}"
)


def links_for(report_rel: str | None, reports: list[dict], *, sut_name: str | None = None,
              run_id: str | None = None) -> dict:
    """run 디렉터리 기준 `report_rel`(run 페이지면 None)에서 본 상대 링크.

    reports는 run 페이지 리포트 목록(`{label, href}`, href는 run 디렉터리 기준)이다. 돌려주는 dict:
    `home`, `sut`(suts/<sut>/index.html), `run`, `reports`(`[{label, href, current}]`), 표시용 `sutName`·`runId`.
    """
    depth = report_rel.count("/") if report_rel else 0
    up = "../" * depth
    return {
        "home": f"{up}{_RUN_TO_ROOT}index.html",
        "sut": f"{up}{_RUN_TO_SUT}",
        "run": f"{up}index.html",
        "reports": [{"label": report["label"], "href": f"{up}{report['href']}", "current": report["href"] == report_rel}
                    for report in reports],
        "sutName": sut_name,
        "runId": run_id,
    }


def render(links: dict, current_label: str) -> str:
    """`<nav class="tdnav" aria-label="리포트 이동">…</nav>` 한 덩어리(스크립트 없음, 인라인 `<style>` 하나)."""
    sut_text = escape(links.get("sutName") or "과제")
    run_title = f' title="run {escape(links["runId"])}"' if links.get("runId") else ""
    crumbs = (
        f'<a class="tdnav-home" href="{escape(links["home"])}">test-dashboard</a>'
        f'<span class="tdnav-sep" aria-hidden="true">›</span>'
        f'<a class="tdnav-sut" href="{escape(links["sut"])}">{sut_text}</a>'
        f'<span class="tdnav-sep" aria-hidden="true">›</span>'
        f'<a class="tdnav-run" href="{escape(links["run"])}"{run_title}>run</a>'
        f'<span class="tdnav-sep" aria-hidden="true">›</span>'
        f'<span class="tdnav-here">{escape(current_label)}</span>'
    )
    items = "".join(
        f'<li><a class="tdnav-item" href="{escape(report["href"])}"{_CURRENT if report["current"] else ""}>'
        f'{escape(report["label"])}</a></li>'
        for report in links.get("reports", []))
    menu = f'<ul class="tdnav-menu">{items}</ul>' if items else ""
    return (f'<nav class="tdnav" aria-label="리포트 이동"><style>{_STYLE}</style>'
            f'<div class="tdnav-in"><span class="tdnav-crumbs">{crumbs}</span>{menu}</div></nav>')


def inject(html_path: Path, nav_html: str) -> bool:
    """처음 나오는 `<body ...>`(대소문자 무시) 바로 뒤에 nav_html을 넣는다. 없으면 파일을 그대로 두고 False."""
    html_path = Path(html_path)
    text = html_path.read_text(encoding="utf-8", errors="surrogateescape")
    match = _BODY_OPEN.search(text)
    if match is None:
        return False
    html_path.write_text(text[:match.end()] + nav_html + text[match.end():], encoding="utf-8", errors="surrogateescape")
    return True
