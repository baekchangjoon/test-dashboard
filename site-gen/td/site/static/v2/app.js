// test-dashboard 새 디자인(v2) 스크립트. 서버가 HTML을 먼저 그리고, 이 스크립트는 페이지에 있는 요소만 보고 덧입힌다.
// 스크립트가 꺼져도 모든 내용이 보인다(예: 단계 설명은 전부 펼쳐진 채로 남는다).
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // --- 단계 띠: 단계를 누르면 그 단계의 설명만 보인다 ------------------------------------------
  function setupStageStrip(strip) {
    var detail = document.getElementById("stage-detail");
    if (!detail) return;
    var buttons = Array.prototype.slice.call(strip.querySelectorAll("button[data-stage]"));
    function select(stageId) {
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", String(button.dataset.stage === stageId));
      });
      Array.prototype.forEach.call(detail.querySelectorAll("[data-detail]"), function (item) {
        item.classList.toggle("on", item.dataset.detail === stageId);
      });
    }
    buttons.forEach(function (button, position) {
      button.addEventListener("click", function () { select(button.dataset.stage); });
      button.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        var next = buttons[(position + step + buttons.length) % buttons.length];
        next.focus();
        select(next.dataset.stage);
      });
    });
    var pressed = strip.querySelector('button[aria-pressed="true"]') || buttons[0];
    if (pressed) select(pressed.dataset.stage);
  }

  // --- 게시 결과(S13): publish-log를 읽어 보여 준다(없으면 "게시 결과 없음" 유지) ---------------------
  var STATUS_CLASS = { passed: "s-good", degraded: "s-warn", failed: "s-crit" };

  function updateS13(log) {
    if (!log.status) return;
    var button = document.querySelector('#stage-strip button[data-stage="S13"]');
    if (button) {
      button.dataset.status = log.status;
      button.classList.remove("s-good", "s-warn", "s-crit", "s-none");
      button.classList.add(STATUS_CLASS[log.status] || "s-none");
    }
    var item = document.querySelector('#stage-detail [data-detail="S13"]');
    if (!item) return;
    var badge = item.querySelector(".st");
    if (badge) {
      badge.textContent = log.status;
      badge.classList.remove("s-good", "s-warn", "s-crit", "s-none");
      badge.classList.add(STATUS_CLASS[log.status] || "s-none");
    }
    var reason = item.querySelector(".stage-reason");
    if (reason) reason.textContent = log.reason || "";
  }

  function setupPublishResult(box) {
    if (!box.dataset.url || !window.fetch) return;
    fetch(box.dataset.url, { cache: "no-cache" }).then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }).then(function (log) {
      box.textContent = "";
      var list = document.createElement("ul");
      function item(text) { var li = document.createElement("li"); li.textContent = text; list.appendChild(li); }
      item("상태: " + (log.status || "알 수 없음"));
      if (log.reason) item("사유: " + log.reason);
      var hosts = log.hosts || {};
      Object.keys(hosts).sort().forEach(function (name) {
        var host = hosts[name];
        item(name + ": " + (host && typeof host === "object" ? (host.status || JSON.stringify(host)) : String(host)));
      });
      box.appendChild(list);
      updateS13(log);
    }).catch(function () { /* 게시 결과 없음 유지 */ });
  }

  // --- 첫 화면: 상태 거르기, 이름 검색, 열 정렬, 행 펼침 ------------------------------------------------
  // 서버가 그린 표의 행을 숨기거나 순서만 바꾼다. 상세 행은 서버가 넣어 둔 <template data-detail-for>를 옮겨 붙인다.
  function setupHome(table) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr.proj"));
    var filterButtons = Array.prototype.slice.call(document.querySelectorAll("button[data-filter]"));
    var sortButtons = Array.prototype.slice.call(table.querySelectorAll("th button[data-sort]"));
    var search = document.getElementById("proj-search");
    var noMatch = document.getElementById("no-match");
    var templates = Array.prototype.slice.call(document.querySelectorAll("template[data-detail-for]"));
    var state = { filter: "all", query: "", sortKey: "status", sortDir: 1 };

    function openRow() {
      for (var i = 0; i < rows.length; i++) if (rows[i].getAttribute("aria-expanded") === "true") return rows[i];
      return null;
    }
    function closeDetail() {
      var detail = tbody.querySelector("tr.proj-detail");
      if (detail) detail.parentNode.removeChild(detail);
      rows.forEach(function (row) { row.setAttribute("aria-expanded", "false"); });
    }
    function openDetail(row) {
      var template = null;
      templates.forEach(function (item) { if (item.dataset.detailFor === row.dataset.name) template = item; });
      if (!template) return;
      var fragment = document.importNode(template.content, true);
      tbody.insertBefore(fragment, row.nextSibling);
      row.setAttribute("aria-expanded", "true");
    }
    function toggle(row) {
      var wasOpen = row.getAttribute("aria-expanded") === "true";
      closeDetail();
      if (!wasOpen) openDetail(row);
    }

    function applyFilter() {
      var query = state.query.toLowerCase();
      var visible = 0;
      rows.forEach(function (row) {
        var shown = (state.filter === "all" || row.dataset.status === state.filter) &&
          row.dataset.name.toLowerCase().indexOf(query) >= 0;
        row.hidden = !shown;
        if (shown) visible += 1;
      });
      var open = openRow();
      if (open && open.hidden) closeDetail();
      if (noMatch) noMatch.hidden = visible > 0;
    }

    function sortValue(row, key) {
      var cell = row.querySelector('td[data-col="' + key + '"]');
      return cell ? cell.getAttribute("data-sort-value") || "" : "";
    }
    function plainCompare(left, right) { return left < right ? -1 : left > right ? 1 : 0; }
    function compareRows(a, b) {
      var left = sortValue(a, state.sortKey), right = sortValue(b, state.sortKey);
      var byName = plainCompare(a.dataset.name.toLowerCase(), b.dataset.name.toLowerCase());
      if (left === "" || right === "") {     // 값이 없는 행은 방향과 무관하게 뒤
        if (left === "" && right === "") return byName;
        return left === "" ? 1 : -1;
      }
      var leftNumber = Number(left), rightNumber = Number(right);
      var order = isFinite(leftNumber) && isFinite(rightNumber) ? plainCompare(leftNumber, rightNumber) : plainCompare(left, right);
      return order ? order * state.sortDir : byName;
    }
    function applySort() {
      var open = openRow();
      var detail = tbody.querySelector("tr.proj-detail");
      rows.sort(compareRows);
      rows.forEach(function (row) { tbody.appendChild(row); });
      if (open && detail) tbody.insertBefore(detail, open.nextSibling);
      Array.prototype.forEach.call(table.querySelectorAll("thead th"), function (th) {
        if (th.dataset.col === state.sortKey) th.setAttribute("aria-sort", state.sortDir > 0 ? "ascending" : "descending");
        else th.removeAttribute("aria-sort");
      });
    }

    filterButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        state.filter = button.dataset.filter;
        filterButtons.forEach(function (other) { other.setAttribute("aria-pressed", String(other === button)); });
        applyFilter();
      });
    });
    if (search) search.addEventListener("input", function () { state.query = search.value; applyFilter(); });
    sortButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        if (state.sortKey === button.dataset.sort) state.sortDir = -state.sortDir;
        else { state.sortKey = button.dataset.sort; state.sortDir = 1; }
        applySort();
      });
    });
    tbody.addEventListener("click", function (event) {
      var close = event.target.closest("button.detail-close");
      if (close) {
        var open = openRow();
        closeDetail();
        if (open) open.focus();
        return;
      }
      var link = event.target.closest("a");
      if (link && !link.classList.contains("proj-link")) return;      // 상세의 "과제 페이지 열기" 등은 그대로 이동
      if (link && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
      var row = event.target.closest("tr.proj");
      if (!row) return;
      if (link) event.preventDefault();     // 스크립트가 있으면 이름을 눌러도 펼친다(상세에 과제 페이지 링크가 있다)
      toggle(row);
    });
    tbody.addEventListener("keydown", function (event) {
      var row = event.target;
      if (!row.classList || !row.classList.contains("proj")) return;
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle(row);
    });
  }

  var projectsTable = document.getElementById("projects");
  if (projectsTable) setupHome(projectsTable);

  var strip = document.getElementById("stage-strip");
  if (strip) setupStageStrip(strip);
  var publishBox = document.getElementById("publish-result");
  if (publishBox) setupPublishResult(publishBox);
})();
