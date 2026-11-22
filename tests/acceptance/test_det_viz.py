"""det 조합 시각화 E2E 수용 테스트(REQ-201~204, 207, 208, 210, 211, 213).

실제 det run(work/det-viz-session.json이 가리키는 run)의 산출물을 본다. 세션 파일이 없으면 skip이 아니라 fail이다(conftest).
기능이 없는 동안은 실패(red)가 정상이며, 실제 pipeline run 뒤에 green이 된다. 테스트를 약화하거나 우회하지 않는다.

집계 재계산(REQ-208)은 `td.detgen.results`·`td.detviz`를 쓰지 않고 이 파일 안에서 설계 §5.4 식으로 독립 구현한다.
"""
import hashlib
import json
import re
import sys
import urllib.request
from itertools import combinations
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import DET_VIZ_SESSION_FILE  # noqa: E402

from td import redact, scenarios  # noqa: E402
from td.site import pages  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "site-gen" / "td" / "schemas"
RESERVATION = "POST /api/reservations"
CLASS_ID = re.compile(r"^c[0-9a-f]{12}$")
# REQ-202: POST /api/reservations 필드별 클래스 수(valid 포함)의 고정 기대값
RESERVATION_CLASS_COUNTS = {"petName": 4, "roomNumber": 4, "animalCount": 3, "checkInDate": 3, "nights": 3,
                            "ownerEmail": 3, "priceTier": 3, "promoCode": 3, "depositAmount": 2, "loyaltyPoints": 2}
OUT_OF_MODEL = {"auth": 16, "no-data": 8, "empty-body": 1, "filter-empty": 2}

pytestmark = pytest.mark.det_viz_e2e


# --- 세션·산출물 읽기 ---------------------------------------------------------------------------------------------
def _session() -> dict:
    return json.loads(DET_VIZ_SESSION_FILE.read_text(encoding="utf-8"))


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return _read_json(SCHEMAS / name)


def _run_dir() -> Path:
    return Path(_session()["runDir"])


def _generation_dir() -> Path:
    """S06 bdd-gen.json의 det generation 항목(`dir`)."""
    records = [g for g in _read_json(_run_dir() / "S06" / "bdd-gen.json")["generations"] if g["arm"] == "det"]
    assert len(records) == 1, f"det generation이 정확히 1개여야 한다: {[g['genId'] for g in records]}"
    assert records[0]["status"] == "passed", records[0]
    gen_dir = Path(records[0]["dir"])
    assert (gen_dir / "_COMPLETE").is_file() and (gen_dir / "cases.json").is_file(), gen_dir
    return gen_dir


def _factors() -> dict:
    return _read_json(_generation_dir() / "factors.json")


def _cases() -> dict:
    return _read_json(_generation_dir() / "cases.json")


def _viz_path() -> Path:
    return _run_dir() / "S12" / "compare" / "det-viz.json"


def _viz() -> dict:
    return _read_json(_viz_path())


def _field_classes(factors: dict) -> dict[str, dict[str, list[dict]]]:
    """엔드포인트 라벨 → 필드 문자열 → 클래스 목록(목록 순서 유지)."""
    return {endpoint["endpoint"]: {field["field"]: field["classes"] for field in endpoint["fields"]}
            for endpoint in factors["endpoints"]}


def _valid_id(endpoint: str, field: str) -> str:
    return "c" + hashlib.sha256(json.dumps([endpoint, field, ["valid"]], ensure_ascii=False).encode()).hexdigest()[:12]


# --- REQ-201 ----------------------------------------------------------------------------------------------------
def test_req201_factors_real():
    """REQ-201: 실제 run의 factors.json이 스키마를 통과하고 엔드포인트 17, 케이스 80, 생성 불가 50, id 유일·형식 일치."""
    factors = _factors()
    jsonschema.validate(factors, _schema("factors.schema.json"))
    assert len(factors["endpoints"]) == 17
    assert sum(1 for endpoint in factors["endpoints"] if endpoint["fields"] == []) == 6
    assert len(factors["cases"]) == 80
    assert [item["index"] for item in factors["unresolved"]] == list(range(50))
    assert all(item["source"] for item in factors["unresolved"])

    seen: set[str] = set()
    for endpoint in factors["endpoints"]:
        for field in endpoint["fields"]:
            classes = field["classes"]
            assert classes[0]["kind"] == "valid", (endpoint["endpoint"], field["field"])
            assert sum(1 for klass in classes if klass["kind"] == "valid") == 1
            assert classes[0]["id"] == _valid_id(endpoint["endpoint"], field["field"])
            rest = [klass["id"] for klass in classes[1:]]
            assert rest == sorted(rest), "valid 다음 클래스는 id 순이어야 한다"
            for klass in classes:
                assert CLASS_ID.match(klass["id"]), klass["id"]
                assert klass["id"] not in seen, f"클래스 id 중복: {klass['id']}"
                seen.add(klass["id"])


# --- REQ-202 ----------------------------------------------------------------------------------------------------
def test_req202_class_counts_real():
    """REQ-202: POST /api/reservations 고정 기대값(곱 46,656, 쌍 403)과 universe 모수 일치."""
    factors = _factors()
    by_endpoint = _field_classes(factors)
    reservation = {field.split(".", 1)[1]: len(classes) for field, classes in by_endpoint[RESERVATION].items()}
    assert reservation == RESERVATION_CLASS_COUNTS

    counts = list(RESERVATION_CLASS_COUNTS.values())
    product = 1
    for count in counts:
        product *= count
    pair_total = sum(a * b for a, b in combinations(counts, 2))
    assert product == 46656 and pair_total == 403
    theoretical = {item["endpoint"]: item for item in _cases()["universe"]["theoretical"]["factors"]}
    assert theoretical[RESERVATION]["product"] == product

    compared = 0
    for label, item in theoretical.items():
        if "fields" not in item:  # concurrency-race 항목은 대상이 아니다
            continue
        compared += 1
        actual = {field: len(classes) for field, classes in by_endpoint[label].items()}
        assert actual == item["fields"], label
    assert compared >= 1


# --- REQ-203 ----------------------------------------------------------------------------------------------------
def _digests(root: Path) -> dict[str, str]:
    """cases.json, features/**, glue/** 의 상대경로 → sha256."""
    files = [root / "cases.json"]
    for sub in ("features", "glue"):
        files += [path for path in (root / sub).rglob("*") if path.is_file()]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def test_req203_cases_unchanged():
    """REQ-203: 새 generation의 cases.json·features·glue가 기준 스냅샷과 바이트 단위로 같다."""
    previous = Path(_session()["previousCasesDir"])
    assert previous.is_dir(), previous
    current = _digests(_generation_dir())
    baseline = _digests(previous)
    assert sorted(current) == sorted(baseline)
    assert current == baseline


# --- REQ-204 ----------------------------------------------------------------------------------------------------
def test_req204_cells_real():
    """REQ-204: 칸 참조 무결성, cellConflicts 0, 키 집합 일치, unresolved 대응."""
    factors, cases = _factors(), _cases()
    by_endpoint = _field_classes(factors)
    valid_ids = {endpoint: {field: {klass["id"] for klass in classes} for field, classes in fields.items()}
                 for endpoint, fields in by_endpoint.items()}

    def assert_cells(endpoint: str, cells: dict, where: str):
        for field, class_id in cells.items():
            assert class_id in valid_ids[endpoint].get(field, set()), f"{where}: {field} -> {class_id} 매달린 참조"

    assert set(factors["cases"]) == {case["id"] for case in cases["cases"]}
    for case in cases["cases"]:
        entry = factors["cases"][case["id"]]
        assert_cells(case["endpoint"], entry["cells"], case["id"])
        assert entry["cellConflicts"] == [], case["id"]

    assert len(factors["unresolved"]) == len(cases["unresolved"])
    for index, (item, source) in enumerate(zip(factors["unresolved"], cases["unresolved"])):
        assert item["index"] == index
        assert item["rule"] == source["rule"], index
        assert item["reason"] == source["reason"], index
        assert_cells(source["endpoint"], item["cells"], f"unresolved[{index}]")
        if item["draftKey"] is None:
            assert item["cells"] == {}, index


# --- REQ-207 ----------------------------------------------------------------------------------------------------
def test_req207_page_and_links():
    """REQ-207: det.html·det-viz.json 생성, 게시 미러와 링크, 게시 URL 200."""
    session = _session()
    run_dir, published = _run_dir(), Path(session["publishedDir"])
    compare_dir = run_dir / "S12" / "compare"
    assert (compare_dir / "det.html").is_file()
    viz = _viz()
    jsonschema.validate(viz, _schema("det-viz.schema.json"))
    case_ids = {case["id"] for case in _cases()["cases"]}
    assert len(case_ids) == 80 and set(viz["caseResults"]) == case_ids

    compare = _read_json(compare_dir / "compare.json")
    assert compare["deterministic"]["viz"]["status"] == "ok"

    assert (published / "compare" / "det.html").is_file()
    assert "compare/det.html" in (published / "index.html").read_text(encoding="utf-8")
    assert re.search(r"""href\s*=\s*["'][^"']*det\.html""", (published / "compare" / "compare.html").read_text(encoding="utf-8"))
    url = session["publishedUrl"].rstrip("/") + "/compare/det.html"
    assert url.startswith("https://"), url
    with urllib.request.urlopen(url, timeout=30) as response:
        assert response.status == 200


# --- REQ-208: 독립 재계산 ---------------------------------------------------------------------------------------
_CASE_TAG = re.compile(r"@case:(\S+)")
_CASE_STEP = re.compile(r'^\s*(?:Given|And|\*)\s+the case "([^"]+)"\s*$')
_SCENARIO = re.compile(r"^\s*Scenario( Outline)?\s*:")


def _case_by_line(feature_text: str) -> dict[int, str]:
    """Scenario 줄 번호 → 케이스 id(바로 위 태그의 `@case:` 우선, 없으면 다음 step의 `the case "<id>"`)."""
    lines = feature_text.splitlines()
    found: dict[int, str] = {}
    for index, line in enumerate(lines):
        if not _SCENARIO.match(line):
            continue
        case_id = None
        above = index - 1
        while above >= 0 and lines[above].strip().startswith("@"):
            match = _CASE_TAG.search(lines[above])
            if match:
                case_id = match.group(1)
            above -= 1
        if case_id is None:
            below = index + 1
            while below < len(lines) and not lines[below].strip():
                below += 1
            match = _CASE_STEP.match(lines[below]) if below < len(lines) else None
            case_id = match.group(1) if match else None
        if case_id is not None:
            found[index + 1] = case_id
    return found


def _independent_statuses(gen_dir: Path, s07_dir: Path) -> dict[str, str]:
    """케이스 id → passed|failed|notRun. td.scenarios의 pickle 매핑과 scenario-results.json만 쓴다."""
    by_test: dict[str, str] = {}
    for line in scenarios.parse_results_file(s07_dir / "scenario-results.json"):
        if isinstance(line, dict) and isinstance(line.get("testId"), str):
            by_test[line["testId"]] = line.get("status")
    ident = scenarios.GenIdent.from_gen_id(gen_dir.name)
    case_lines = {relative: _case_by_line((gen_dir / relative).read_text(encoding="utf-8"))
                  for relative in scenarios.feature_files(gen_dir)}
    raw: dict[str, str] = {}
    for ref in scenarios.pickle_refs(gen_dir, ident):
        case_id = case_lines.get(ref.feature, {}).get(ref.line)
        if case_id is not None and ref.test_id in by_test:
            raw[case_id] = by_test[ref.test_id]
    return {case["id"]: raw.get(case["id"]) if raw.get(case["id"]) in ("passed", "failed") else "notRun"
            for case in _cases()["cases"]}


def _recount(factors: dict, cases: dict, status: dict[str, str]) -> dict:
    """설계 §5.4 집계 정의를 그대로 구현한다. inModel 케이스만 세고, 칸에 없는 필드는 valid로 해석한다."""
    endpoint_of = {case["id"]: case["endpoint"] for case in cases["cases"]}
    by_endpoint = _field_classes(factors)
    in_model = {case_id: entry for case_id, entry in factors["cases"].items() if entry["inModel"]}
    result: dict = {"byEndpoint": {}}
    for label, fields in by_endpoint.items():
        valid_of = {field: classes[0]["id"] for field, classes in fields.items()}
        resolved = {case_id: {field: entry["cells"].get(field, valid_of[field]) for field in fields}
                    for case_id, entry in in_model.items() if endpoint_of[case_id] == label}
        slots = [(item, cases["unresolved"][item["index"]]) for item in factors["unresolved"]]
        slots = [item for item, source in slots if source["endpoint"] == label]

        class_out: dict = {}
        for field, classes in fields.items():
            for klass in classes:
                members = sorted(case_id for case_id, cell in resolved.items() if cell[field] == klass["id"])
                statuses = [status[case_id] for case_id in members]
                hit = sorted((item["index"], item["reason"]) for item in slots if item["cells"].get(field) == klass["id"])
                if "passed" in statuses:
                    state = "covered-pass"
                elif "failed" in statuses:
                    state = "covered-fail"
                elif members:
                    state = "covered-notrun"
                elif hit:
                    state = "unresolved"
                else:
                    state = "empty"
                boundary = sum(1 for case_id in resolved if klass["id"] in in_model[case_id]["boundaries"])
                class_out[klass["id"]] = {"state": state, "cases": members, "boundaryCases": boundary, "unresolved": hit}

        names = list(fields)
        matrix = {}
        total = covered = 0
        for a, b in combinations(names, 2):
            counts = [[sum(1 for cell in resolved.values() if cell[a] == ca["id"] and cell[b] == cb["id"])
                       for cb in fields[b]] for ca in fields[a]]
            matrix[(a, b)] = counts
            total += len(fields[a]) * len(fields[b])
            covered += sum(1 for row in counts for count in row if count >= 1)
        result["byEndpoint"][label] = {"classes": class_out, "pairs": {"total": total, "covered": covered, "matrix": matrix}}

    all_classes = [info for endpoint in result["byEndpoint"].values() for info in endpoint["classes"].values()]
    out_of_model: dict[str, int] = {}
    for entry in factors["cases"].values():
        if not entry["inModel"]:
            out_of_model[entry["outReason"]] = out_of_model.get(entry["outReason"], 0) + 1
    result["summary"] = {
        "endpoints": len(by_endpoint),
        "fields": sum(len(fields) for fields in by_endpoint.values()),
        "classes": len(all_classes),
        "classesCovered": sum(1 for info in all_classes if info["state"].startswith("covered-")),
        "pairsCovered": sum(e["pairs"]["covered"] for e in result["byEndpoint"].values()),
        "pairsTotal": sum(e["pairs"]["total"] for e in result["byEndpoint"].values()),
        "outOfModel": out_of_model,
        "inModel": len(in_model),
    }
    return result


def test_req208_recount():
    """REQ-208: det-viz.json aggregates가 테스트 안의 독립 재계산과 모두 같다."""
    gen_dir = _generation_dir()
    factors, cases, viz = _factors(), _cases(), _viz()
    status = _independent_statuses(gen_dir, _run_dir() / "S07" / gen_dir.name)
    expected = _recount(factors, cases, status)
    aggregates = viz["aggregates"]

    assert viz["caseResults"].keys() == status.keys()
    for case_id, result in viz["caseResults"].items():
        assert result["status"] == status[case_id], case_id

    assert set(aggregates["byEndpoint"]) == set(expected["byEndpoint"])
    for label, want in expected["byEndpoint"].items():
        got = aggregates["byEndpoint"][label]
        assert set(got["classes"]) == set(want["classes"]), label
        for class_id, want_class in want["classes"].items():
            got_class = got["classes"][class_id]
            assert got_class["state"] == want_class["state"], (label, class_id)
            assert sorted(got_class["cases"]) == want_class["cases"], (label, class_id)
            assert got_class["boundaryCases"] == want_class["boundaryCases"], (label, class_id)
            assert sorted((u["index"], u["reason"]) for u in got_class["unresolved"]) == want_class["unresolved"], (label, class_id)
        assert got["pairs"]["total"] == want["pairs"]["total"], label
        assert got["pairs"]["covered"] == want["pairs"]["covered"], label
        got_matrix = {(row["a"], row["b"]): row["counts"] for row in got["pairs"]["matrix"]}
        assert got_matrix == want["pairs"]["matrix"], label
    assert aggregates["byEndpoint"][RESERVATION]["pairs"]["total"] == 403

    summary, want_summary = aggregates["summary"], expected["summary"]
    for key in ("endpoints", "fields", "classes", "classesCovered", "pairsCovered", "pairsTotal"):
        assert summary[key] == want_summary[key], key
    assert summary["outOfModel"] == want_summary["outOfModel"] == OUT_OF_MODEL
    assert want_summary["inModel"] == 53
    assert (summary["endpoints"], summary["fields"], summary["classes"], summary["pairsTotal"]) == (17, 26, 55, 434)


# --- REQ-210 ----------------------------------------------------------------------------------------------------
def test_req210_no_leaks():
    """REQ-210: 게시 사본의 det.html·det-viz.json에 홈 경로·로컬 경로·식별자·ARN이 없다."""
    published = Path(_session()["publishedDir"])
    for name in ("det.html", "det-viz.json"):
        path = published / "compare" / name
        assert path.is_file(), path
        assert redact.find_leaks(path.read_text(encoding="utf-8")) == [], name
    pages.check_no_home(published)


# --- REQ-211 ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def viz_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def _open_det_page(browser, html_path: Path, **context_kwargs):
    """file:/data: 이외 요청은 막고 시도된 외부 요청과 콘솔·페이지 오류를 모은다(test_ontology의 패턴)."""
    context = browser.new_context(**context_kwargs)
    blocked, console_errors, page_errors = [], [], []

    def guard(route):
        if route.request.url.startswith(("file:", "data:")):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()
    context.route("**/*", guard)
    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.goto(html_path.as_uri())
    page.wait_for_function("window.__td_ready === true", timeout=30000)
    return context, page, blocked, console_errors, page_errors


def _node_count(page) -> int:
    return int(page.locator("[data-node-count]").first.get_attribute("data-node-count"))


def test_req211_browser(viz_browser):
    """REQ-211: 네트워크 차단 상태에서 렌더·선택·펼침·테마·390px 동작."""
    html_path = _run_dir() / "S12" / "compare" / "det.html"
    assert html_path.is_file(), html_path
    viz = _viz()
    factors = viz["factors"]
    class_total = sum(len(field["classes"]) for endpoint in factors["endpoints"] for field in endpoint["fields"])
    matrix_total = sum(len(entry["pairs"]["matrix"]) for entry in viz["aggregates"]["byEndpoint"].values())
    assert class_total == 55 and matrix_total > 0

    context, page, blocked, console_errors, page_errors = _open_det_page(viz_browser, html_path)
    try:
        # 데이터와 화면의 일치: 격자 칸 수, 히트맵 행렬 수
        assert page.locator("[data-class-id]").count() == class_total
        assert page.locator("[data-pair]").count() == matrix_total

        # 엔드포인트 선택 변경 → 그래프 노드 집합이 바뀐다(케이스 수가 가장 많은/적은 엔드포인트로 비교)
        case_count = {endpoint["endpoint"]: 0 for endpoint in factors["endpoints"]}
        for result in viz["caseResults"].values():
            case_count[result["endpoint"]] += 1
        busiest = max(case_count, key=lambda label: (case_count[label], label))
        quietest = min(case_count, key=lambda label: (case_count[label], label))
        select = page.locator("select").first
        select.select_option(value=busiest)
        busy_nodes = _node_count(page)
        assert busy_nodes >= case_count[busiest]
        select.select_option(value=quietest)
        quiet_nodes = _node_count(page)
        assert quiet_nodes != busy_nodes and quiet_nodes >= case_count[quietest]
        select.select_option(value=busiest)

        # 케이스 노드 선택 → 패널에 조건식 원문·기대·관측
        case_id = None
        condition = None
        for candidate, entry in factors["cases"].items():
            result = viz["caseResults"][candidate]
            if result["endpoint"] != busiest or result["status"] not in ("passed", "failed") or result["observed"] is None:
                continue
            for address in _case_sources(candidate):
                source = factors["sources"].get(address, {})
                if source.get("condition"):
                    case_id, condition = candidate, source["condition"]
                    break
            if case_id:
                break
        assert case_id, "조건식 원문이 있는 실행된 케이스를 찾지 못했다"
        page.evaluate("id => window.__detviz.select(id)", case_id)
        panel_text = page.locator("#panel").text_content()
        assert condition in panel_text
        assert str(viz["caseResults"][case_id]["expectStrict"]) in panel_text
        assert str(viz["caseResults"][case_id]["observed"]) in panel_text

        # 히트맵 details 펼침
        details = page.locator("details:has([data-pair])").first
        details.locator("summary").first.click()
        assert details.evaluate("element => element.open") is True
        assert details.locator("[data-pair]").first.is_visible()

        assert blocked == [] and console_errors == [] and page_errors == []
    finally:
        context.close()

    # 라이트·다크, 390px 폭에서 페이지 가로 스크롤이 없다
    for scheme in ("light", "dark"):
        context, page, blocked, console_errors, page_errors = _open_det_page(
            viz_browser, html_path, color_scheme=scheme, viewport={"width": 390, "height": 800})
        try:
            page.emulate_media(color_scheme=scheme)
            widths = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            assert widths[0] <= widths[1], (scheme, widths)
            assert blocked == [] and console_errors == [] and page_errors == []
        finally:
            context.close()


def _case_sources(case_id: str) -> list[str]:
    """cases.json 케이스의 출처 주소(`~` 제거)."""
    for case in _cases()["cases"]:
        if case["id"] == case_id:
            return [address.rstrip("~") for address in case["sources"]]
    return []


# --- REQ-213 ----------------------------------------------------------------------------------------------------
def test_req213_passed_matches_summary():
    """REQ-213: caseResults의 passed 수 == compare.json deterministic.summary.passStrict.passed."""
    viz = _viz()
    passed = sum(1 for result in viz["caseResults"].values() if result["status"] == "passed")
    compare = _read_json(_run_dir() / "S12" / "compare" / "compare.json")
    assert passed == compare["deterministic"]["summary"]["passStrict"]["passed"]
