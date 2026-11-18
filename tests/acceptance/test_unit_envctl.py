"""envctl 단위 테스트: 스냅샷 파싱, 귀속(owned/foreign), compose 라벨 검사, ps 파싱."""
from td import envctl

LABEL = "td-20261119-000000Z-abcdef0-manual-12345678"


def snap(containers=None, networks=None, volumes=None):
    return envctl.DockerSnap(containers=containers or {}, networks=networks or {}, volumes=volumes or {})


def test_parse_listing_extracts_compose_project():
    text = "abc123\tcom.docker.compose.project=td-x-s01,test-run=td-x\ndef456\t\n"
    assert envctl.parse_listing(text) == {"abc123": "td-x-s01", "def456": None}


def test_diff_attributes_by_td_prefix():
    before = snap(containers={"old": None}, networks={"bridge": None})
    after = snap(containers={"old": None, "mine": "td-run1-s01-blackbox", "tst": "td-test-ab12-x", "other": "somebody"},
                 networks={"n1": "td-run1-s01-blackbox", "bridge": None},
                 volumes={"v1": "other-proj"})
    leak = envctl.diff(before, after)
    assert leak.owned == ["container:mine", "container:tst", "network:n1"]
    assert leak.foreign == ["container:other", "volume:v1"]


def test_diff_ignores_resources_that_existed_before_and_removed_ones():
    before = snap(containers={"a": "td-x", "b": None})
    after = snap(containers={"a": "td-x"})
    leak = envctl.diff(before, after)
    assert leak.owned == [] and leak.foreign == []


def test_unlabeled_resources_reports_each_kind():
    config = {"services": {"sut": {"labels": {"test-run": LABEL}}, "db": {}},
              "networks": {"default": {"labels": {"test-run": "other"}}},
              "volumes": {"tmp": {"labels": {"test-run": LABEL}}}}
    assert envctl.unlabeled_resources(config, LABEL) == ["service:db", "network:default"]


def test_unlabeled_resources_requires_explicit_network_and_volume():
    config = {"services": {"sut": {"labels": {"test-run": LABEL}}}}
    missing = envctl.unlabeled_resources(config, LABEL)
    assert "network:default" in missing and any(m.startswith("volume:") for m in missing)


def test_parse_gradle_daemons_uses_pid_and_start_time():
    ps = ("  101 Thu Nov 19 10:00:00 2026 /jdk/bin/java -Xmx1g org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.14\n"
          "  102 Thu Nov 19 10:00:01 2026 /usr/bin/vim notes.txt\n")
    assert envctl.parse_gradle_daemons(ps) == [(101, "Thu Nov 19 10:00:00 2026")]


def test_failure_reason_keeps_tail_pointer_and_budget():
    log = "\n".join(f"line {n} " + "가" * 40 for n in range(200))
    reason = envctl.failure_reason("SUT 컨테이너가 종료됐다", log, "S01/blackbox/sut.log")
    assert len(reason) <= 1400
    assert reason.endswith("(full log: S01/blackbox/sut.log)")
    assert reason.splitlines()[-2] == "line 199 " + "가" * 40  # 마지막 로그 줄이 포인터 바로 앞에 온다
    assert "line 0 " not in reason  # 최근 50줄만


def test_failure_reason_short_log_is_whole_and_empty_log_is_marked():
    reason = envctl.failure_reason("실패", "a\nb\n", "x/sut.log")
    assert reason == "실패. 로그 마지막:\na\nb\n(full log: x/sut.log)"
    assert "(로그 없음)" in envctl.failure_reason("실패", "", "x/sut.log")


def test_cap_chars_is_character_safe():
    assert envctl.cap_chars("한" * 10, 4) == "한한한…"
    assert envctl.cap_chars("abc", 4) == "abc"
