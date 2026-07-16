/* CareerStatic 儀表板前端邏輯（繁體中文 UI，使用 Chart.js） */
(function () {
  "use strict";

  const state = {
    date: null,
    page: 1,
    pageSize: 20,
    query: "",
    totalJobs: 0,
    charts: {},
  };

  const PALETTE = [
    "#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#14b8a6", "#f97316", "#64748b", "#ec4899",
  ];

  const $ = (id) => document.getElementById(id);

  async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      const error = new Error(body.detail || `HTTP ${resp.status}`);
      error.status = resp.status;
      throw error;
    }
    return resp.json();
  }

  function showToast(message) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => toast.classList.add("hidden"), 4000);
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function ratioLabel(item, total) {
    const pct = total ? ((item.count / total) * 100).toFixed(1) : "0.0";
    return `${item.count.toLocaleString()} 筆（${pct}%）`;
  }

  function makeBarChart(key, canvasId, items, color) {
    destroyChart(key);
    const total = state.totalJobs;
    state.charts[key] = new Chart($(canvasId), {
      type: "bar",
      data: {
        labels: items.map((it) => {
          const delta = it.rank_delta;
          if (delta != null && delta >= 2) return `${it.name} ↑${delta}`;
          return it.name;
        }),
        datasets: [{
          data: items.map((it) => it.count),
          backgroundColor: color,
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ratioLabel(items[ctx.dataIndex], total),
            },
          },
        },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } },
        },
      },
    });
  }

  function makeDoughnutChart(key, canvasId, items) {
    destroyChart(key);
    const total = state.totalJobs;
    state.charts[key] = new Chart($(canvasId), {
      type: "doughnut",
      data: {
        labels: items.map((it) => it.name),
        datasets: [{
          data: items.map((it) => it.count),
          backgroundColor: items.map((_, i) => PALETTE[i % PALETTE.length]),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right" },
          tooltip: {
            callbacks: {
              label: (ctx) => `${items[ctx.dataIndex].name}：${ratioLabel(items[ctx.dataIndex], total)}`,
            },
          },
        },
      },
    });
  }

  function makeTrendChart(trend) {
    destroyChart("trend");
    state.charts.trend = new Chart($("chart-trend"), {
      type: "line",
      data: {
        labels: trend.dates,
        datasets: [
          {
            label: "總職缺數",
            data: trend.total_jobs,
            borderColor: "#4f46e5",
            backgroundColor: "rgba(79, 70, 229, 0.12)",
            fill: true,
            tension: 0.25,
          },
          {
            label: "新增職缺",
            data: trend.new_jobs,
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.12)",
            fill: true,
            tension: 0.25,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }

  async function loadSummary() {
    const data = await fetchJSON(`/api/summary?date=${state.date}`);
    state.totalJobs = data.total_jobs;

    $("stat-total").textContent = data.total_jobs.toLocaleString();
    $("stat-new").textContent = data.new_jobs.toLocaleString();
    $("stat-coverage").textContent = `${(data.detail_coverage * 100).toFixed(1)}%`;
    $("stat-date").textContent = data.date;
    $("summary-text").textContent = data.summary_text || "（本日無總結文字）";

    const categories = data.categories || {};
    makeBarChart("specialty", "chart-specialty", (categories.specialty || []).slice(0, 15), "#4f46e5");
    makeBarChart("keyword", "chart-keyword", (categories.tech_keyword || []).slice(0, 15), "#0ea5e9");
    makeBarChart("skill", "chart-skill", (categories.skill || []).slice(0, 10), "#10b981");
    makeDoughnutChart("edu", "chart-edu", (categories.education || []).slice(0, 6));
    makeDoughnutChart("exp", "chart-exp", (categories.experience || []).slice(0, 8));
  }

  async function loadTrend() {
    const trend = await fetchJSON("/api/trend?days=30");
    makeTrendChart(trend);
  }

  async function loadJobs() {
    const params = new URLSearchParams({
      date: state.date,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    if (state.query) params.set("q", state.query);
    const data = await fetchJSON(`/api/jobs?${params}`);

    const tbody = $("jobs-table").querySelector("tbody");
    tbody.innerHTML = "";
    for (const job of data.items) {
      const tr = document.createElement("tr");

      const nameTd = document.createElement("td");
      const link = document.createElement("a");
      link.href = job.job_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = job.job_name;
      nameTd.appendChild(link);

      const custTd = document.createElement("td");
      custTd.textContent = job.cust_name;
      const areaTd = document.createElement("td");
      areaTd.textContent = job.area_desc;
      const salaryTd = document.createElement("td");
      salaryTd.textContent = job.salary_text;

      const kwTd = document.createElement("td");
      for (const kw of job.tech_keywords) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = kw;
        kwTd.appendChild(tag);
      }

      tr.append(nameTd, custTd, areaTd, salaryTd, kwTd);
      tbody.appendChild(tr);
    }

    const lastPage = Math.max(1, Math.ceil(data.total / state.pageSize));
    $("page-info").textContent = `第 ${state.page} / ${lastPage} 頁（共 ${data.total.toLocaleString()} 筆）`;
    $("prev-page").disabled = state.page <= 1;
    $("next-page").disabled = state.page >= lastPage;
  }

  async function loadAll() {
    try {
      await loadSummary();
      await Promise.all([loadTrend(), loadJobs()]);
    } catch (err) {
      showToast(`載入失敗：${err.message}`);
    }
  }

  async function triggerCrawl() {
    const btn = $("crawl-btn");
    btn.disabled = true;
    try {
      await fetchJSON("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      showToast("已開始更新資料，完成後重新整理頁面即可看到最新統計。");
    } catch (err) {
      if (err.status === 409) {
        showToast("已有爬取進行中，請稍後再試。");
      } else {
        showToast(`觸發失敗：${err.message}`);
      }
    } finally {
      setTimeout(() => { btn.disabled = false; }, 3000);
    }
  }

  function bindEvents() {
    $("date-select").addEventListener("change", (event) => {
      state.date = event.target.value;
      state.page = 1;
      loadAll();
    });
    $("crawl-btn").addEventListener("click", triggerCrawl);
    $("prev-page").addEventListener("click", () => {
      if (state.page > 1) { state.page -= 1; loadJobs(); }
    });
    $("next-page").addEventListener("click", () => {
      state.page += 1;
      loadJobs();
    });
    let searchTimer = null;
    $("job-search").addEventListener("input", (event) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.query = event.target.value.trim();
        state.page = 1;
        loadJobs();
      }, 350);
    });
  }

  async function init() {
    bindEvents();
    let dates = [];
    try {
      ({ dates } = await fetchJSON("/api/dates"));
    } catch (err) {
      showToast(`載入日期失敗：${err.message}`);
    }
    if (!dates.length) {
      $("empty-state").classList.remove("hidden");
      return;
    }
    const select = $("date-select");
    select.innerHTML = "";
    for (const date of dates) {
      const option = document.createElement("option");
      option.value = date;
      option.textContent = date;
      select.appendChild(option);
    }
    state.date = dates[0];
    $("dashboard-body").classList.remove("hidden");
    await loadAll();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
