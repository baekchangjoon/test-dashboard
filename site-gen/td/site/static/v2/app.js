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

  // --- 과제 페이지: 탭(WAI-ARIA 탭 규약) ------------------------------------------------------------
  // 서버는 모든 구역을 보이게 그린다. 여기서 선택된 구역만 남기고(hidden), 고른 탭을 주소의 # 부분에 남긴다.
  function setupTabs(tablist) {
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));
    if (!tabs.length) return;
    function panelOf(tab) { return document.getElementById(tab.getAttribute("aria-controls")); }
    function tabFor(id) {
      if (id.indexOf("panel-") === 0) id = id.slice(6);
      for (var i = 0; i < tabs.length; i++) if (tabs[i].dataset.tab === id) return tabs[i];
      return null;
    }
    function hashId() {
      try { return decodeURIComponent(location.hash.slice(1)); } catch (error) { return ""; }
    }
    function select(tab, options) {
      tabs.forEach(function (other) {
        var on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
        var panel = panelOf(other);
        if (panel) panel.hidden = !on;
      });
      if (options.focus) tab.focus();
      if (options.hash && window.history && history.replaceState) history.replaceState(null, "", "#" + tab.dataset.tab);
    }
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () { select(tab, { hash: true }); });
    });
    tablist.addEventListener("keydown", function (event) {
      var position = tabs.indexOf(event.target);
      if (position < 0) return;
      var next = null;
      if (event.key === "ArrowRight") next = tabs[(position + 1) % tabs.length];
      else if (event.key === "ArrowLeft") next = tabs[(position - 1 + tabs.length) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs[tabs.length - 1];
      if (!next) return;
      event.preventDefault();
      select(next, { focus: true, hash: true });
    });
    // 구역 안의 "다른 탭으로" 링크(href="#panel-<id>", data-tab-link)
    document.addEventListener("click", function (event) {
      var link = event.target.closest ? event.target.closest("a[data-tab-link]") : null;
      if (!link) return;
      var tab = tabFor(link.dataset.tabLink);
      if (!tab) return;
      event.preventDefault();
      select(tab, { focus: true, hash: true });
      tablist.scrollIntoView({ block: "nearest" });
    });
    window.addEventListener("hashchange", function () {
      var tab = tabFor(hashId());
      if (tab) select(tab, {});
    });
    var initial = tabFor(hashId());      // 모르는 #이나 # 없음은 첫 탭
    select(initial || tabs[0], { hash: !!initial && hashId() !== initial.dataset.tab });
  }

  // --- 과제 페이지: 추이 차트의 툴팁과 같은 run 강조 -------------------------------------------------
  // 점(.pt)에 마우스를 올리거나 초점을 주면 툴팁에 식별자·시각·값을 쓰고, 모든 차트와 표에서 data-id가 같은 점·행을 강조한다.
  function setupTrend(tip) {
    var points = Array.prototype.slice.call(document.querySelectorAll("figure.trend .pt"));
    var rows = Array.prototype.slice.call(document.querySelectorAll("#trend-table tr[data-id]"));
    if (!points.length) return;
    function highlight(id) {
      points.forEach(function (point) { point.classList.toggle("hl", id !== null && point.dataset.id === id); });
      rows.forEach(function (row) { row.classList.toggle("hl", id !== null && row.dataset.id === id); });
    }
    function line(text, bold) {
      var element = document.createElement(bold ? "b" : "span");
      element.textContent = text;
      tip.appendChild(element);
      if (!bold) tip.appendChild(document.createElement("br"));
    }
    function dateText(id) {
      return /^\d{8}$/.test(id) ? id.slice(0, 4) + "-" + id.slice(4, 6) + "-" + id.slice(6, 8) : id;
    }
    function show(point) {
      var figure = point.closest("figure");
      var caption = figure ? figure.querySelector("figcaption") : null;
      tip.textContent = "";
      line((caption ? caption.textContent + " " : "") + (point.dataset.value || ""), true);
      line(dateText(point.dataset.id || ""));
      if (point.dataset.at) line(point.dataset.at.replace("T", " ").replace("Z", " UTC"));
      tip.hidden = false;
      var box = point.getBoundingClientRect();
      var left = Math.min(box.left + box.width / 2 + 10, window.innerWidth - tip.offsetWidth - 8);
      var top = box.top - tip.offsetHeight - 8;
      tip.style.left = Math.max(8, left) + "px";
      tip.style.top = (top < 8 ? box.bottom + 8 : top) + "px";
      highlight(point.dataset.id || null);
    }
    function hide() {
      tip.hidden = true;
      highlight(null);
    }
    points.forEach(function (point) {
      point.addEventListener("mouseenter", function () { show(point); });
      point.addEventListener("focus", function () { show(point); });
      point.addEventListener("mouseleave", hide);
      point.addEventListener("blur", hide);
    });
  }

  var projectsTable = document.getElementById("projects");
  if (projectsTable) setupHome(projectsTable);
  var tablist = document.getElementById("tabs");
  if (tablist && tablist.getAttribute("role") === "tablist") setupTabs(tablist);
  var trendTip = document.getElementById("trend-tip");
  if (trendTip) setupTrend(trendTip);

  var strip = document.getElementById("stage-strip");
  if (strip) setupStageStrip(strip);
  var publishBox = document.getElementById("publish-result");
  if (publishBox) setupPublishResult(publishBox);
})();
