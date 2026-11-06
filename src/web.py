"""Web 界面：浏览器里使用短视频脚本 Agent。

仅使用 Python 标准库（http.server），不新增依赖：
    python -m src.web            # 默认 http://127.0.0.1:8000
    python -m src.web --port 9000

页面表单 → POST /api/run → run_agent（与 CLI 同一入口）→ 返回状态/脚本/Trace。
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:  # python-dotenv 为可选依赖：Mock 离线模式零依赖可跑
    from dotenv import load_dotenv as _load_dotenv_safe
except ImportError:
    def _load_dotenv_safe() -> bool:
        return False

from .agent import run_agent
from .model import MockModelClient, QwenClient

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>短视频脚本 Agent</title>
<style>
  :root {
    --bg: #f4f6f9;
    --surface: #ffffff;
    --surface-soft: #fafbfc;
    --border: #e5e8ee;
    --border-strong: #d5dae2;
    --text: #15181e;
    --muted: #6b7280;
    --brand: #2563eb;
    --brand-dark: #1d4ed8;
    --brand-soft: #eff4ff;
    --ok: #059669;
    --ok-soft: #ecfdf5;
    --warn: #b45309;
    --warn-soft: #fffbeb;
    --err: #dc2626;
    --err-soft: #fef2f2;
    --radius: 14px;
    --shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.04);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  /* ---------- 顶栏 ---------- */
  .topbar {
    background: rgba(255,255,255,.86);
    backdrop-filter: saturate(160%) blur(10px);
    border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 20;
  }
  .topbar-inner {
    max-width: 1180px; margin: 0 auto; padding: 14px 24px;
    display: flex; align-items: center; gap: 12px;
  }
  .logo {
    width: 34px; height: 34px; border-radius: 10px; flex: none;
    background: var(--brand); display: grid; place-items: center;
    box-shadow: 0 4px 12px rgba(37,99,235,.25);
  }
  .logo svg { width: 16px; height: 16px; }
  .brand-name { font-size: 15px; font-weight: 700; letter-spacing: .2px; }
  .brand-sub { font-size: 12px; color: var(--muted); margin-top: 1px; }
  .topbar-spacer { flex: 1; }
  .pill {
    font-size: 12px; color: var(--muted); border: 1px solid var(--border);
    padding: 4px 10px; border-radius: 99px; background: var(--surface);
  }

  /* ---------- 布局 ---------- */
  .layout {
    max-width: 1180px; margin: 0 auto; padding: 24px 24px 56px;
    display: grid; grid-template-columns: 396px minmax(0, 1fr); gap: 20px;
    align-items: start;
  }
  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; padding: 16px 14px 40px; }
    .topbar-inner { padding: 12px 16px; }
  }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); box-shadow: var(--shadow);
  }
  .card-head {
    padding: 16px 20px 0; display: flex; align-items: center; gap: 8px;
  }
  .card-title { font-size: 14px; font-weight: 700; }
  .card-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .card-body { padding: 16px 20px 20px; }

  /* ---------- 表单 ---------- */
  .field { margin-bottom: 14px; }
  .field:last-of-type { margin-bottom: 0; }
  .label {
    display: flex; align-items: center; gap: 5px;
    font-size: 12px; font-weight: 600; color: #4b5563; margin-bottom: 6px;
  }
  .req { color: var(--err); font-weight: 700; }
  input[type="text"], input[type="number"], select {
    width: 100%; height: 40px; padding: 0 12px;
    border: 1px solid var(--border-strong); border-radius: 9px;
    background: var(--surface); color: var(--text);
    font-size: 14px; font-family: inherit; outline: none;
    transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
  }
  input:hover, select:hover { border-color: #b9c1cd; }
  input:focus, select:focus {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgba(37,99,235,.13);
  }
  select {
    appearance: none; cursor: pointer;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 12px center;
    padding-right: 32px;
  }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .chips { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .chip {
    border: 1px solid var(--border-strong); background: var(--surface-soft);
    color: #4b5563; border-radius: 7px; padding: 3px 10px; font-size: 12px;
    cursor: pointer; font-family: inherit;
    transition: all .15s ease;
  }
  .chip:hover { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }

  .switches { display: flex; flex-direction: column; gap: 9px; margin: 18px 0 16px; }
  .switch {
    display: flex; align-items: center; gap: 9px; font-size: 13px;
    color: #4b5563; cursor: pointer; user-select: none;
  }
  .switch input { appearance: none; width: 34px; height: 19px; border-radius: 99px;
    background: #d7dce4; position: relative; cursor: pointer; flex: none;
    transition: background .18s ease; margin: 0; }
  .switch input::after {
    content: ""; position: absolute; top: 2px; left: 2px; width: 15px; height: 15px;
    border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.2);
    transition: transform .18s ease;
  }
  .switch input:checked { background: var(--brand); }
  .switch input:checked::after { transform: translateX(15px); }

  .submit {
    width: 100%; height: 42px; border: 0; border-radius: 10px;
    background: var(--brand); color: #fff; font-size: 14px; font-weight: 600;
    font-family: inherit; cursor: pointer; display: flex; align-items: center;
    justify-content: center; gap: 8px; letter-spacing: .2px;
    transition: background .16s ease, transform .08s ease, box-shadow .16s ease;
    box-shadow: 0 4px 12px rgba(37,99,235,.22);
  }
  .submit:hover { background: var(--brand-dark); }
  .submit:active { transform: translateY(1px); }
  .submit:disabled { background: #9db8f5; cursor: not-allowed; box-shadow: none; }
  .spinner {
    width: 15px; height: 15px; border-radius: 50%;
    border: 2px solid rgba(255,255,255,.4); border-top-color: #fff;
    animation: spin .7s linear infinite; display: none;
  }
  .submit.loading .spinner { display: block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .hint { font-size: 12px; color: var(--muted); margin-top: 10px; text-align: center; }

  /* ---------- 结果 ---------- */
  .empty {
    border: 1px dashed var(--border-strong); border-radius: var(--radius);
    background: var(--surface); padding: 56px 24px; text-align: center;
    color: var(--muted); box-shadow: var(--shadow);
  }
  .empty-icon {
    width: 48px; height: 48px; margin: 0 auto 14px; border-radius: 14px;
    background: var(--brand-soft); display: grid; place-items: center; color: var(--brand);
  }
  .empty-title { font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 4px; }

  .result-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 700; padding: 4px 11px; border-radius: 99px;
    letter-spacing: .3px;
  }
  .badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; }
  .badge.completed { background: var(--ok-soft); color: var(--ok); }
  .badge.completed::before { background: var(--ok); }
  .badge.unfinished { background: var(--warn-soft); color: var(--warn); }
  .badge.unfinished::before { background: #f59e0b; }
  .badge.failed { background: var(--err-soft); color: var(--err); }
  .badge.failed::before { background: var(--err); }
  .badge.needs_info { background: var(--brand-soft); color: var(--brand-dark); }
  .badge.needs_info::before { background: var(--brand); }

  .title-line {
    font-size: 19px; font-weight: 700; letter-spacing: -.2px;
    margin: 14px 0 4px; line-height: 1.35;
  }
  .meta-line { font-size: 12px; color: var(--muted); }

  .metrics {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 16px 0 14px;
  }
  .metric {
    background: var(--surface-soft); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 12px;
  }
  .metric-k { font-size: 11px; color: var(--muted); letter-spacing: .3px; }
  .metric-v { font-size: 18px; font-weight: 700; margin-top: 2px; }
  .metric-v small { font-size: 11px; font-weight: 500; color: var(--muted); margin-left: 2px; }

  .checks { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .check {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; padding: 5px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface-soft);
  }
  .check.ok { background: var(--ok-soft); border-color: #bbf7d0; color: var(--ok); }
  .check.bad { background: var(--err-soft); border-color: #fecaca; color: var(--err); }
  .check .dot { width: 7px; height: 7px; border-radius: 50%; background: #9ca3af; }
  .check.ok .dot { background: var(--ok); }
  .check.bad .dot { background: var(--err); }

  .section-label {
    font-size: 12px; font-weight: 700; color: #374151;
    letter-spacing: .4px; margin: 0 0 10px; display: flex; align-items: center; gap: 8px;
  }
  .section-label::after {
    content: ""; flex: 1; height: 1px; background: var(--border);
  }

  .shot {
    border: 1px solid var(--border); border-radius: 11px;
    background: var(--surface-soft); padding: 12px 14px; margin-bottom: 9px;
    display: grid; grid-template-columns: 30px 1fr; gap: 12px;
    transition: border-color .16s ease, box-shadow .16s ease;
  }
  .shot:hover { border-color: #cfd7e3; box-shadow: 0 2px 8px rgba(16,24,40,.05); }
  .shot-idx {
    width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center;
    background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 700;
  }
  .shot-visual { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  .shot-narration { font-size: 14px; line-height: 1.6; }
  .shot-foot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 9px; }
  .tag {
    font-size: 11px; padding: 2px 7px; border-radius: 6px;
    background: #eef2ff; color: #3730a3; font-family: Consolas, monospace;
  }
  .tag.time { background: #f3f4f6; color: #4b5563; }
  .fact { font-size: 11px; color: #8b93a1; margin-top: 6px; line-height: 1.5; }

  .note-box {
    font-size: 12px; color: #4b5563; background: var(--surface-soft);
    border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-top: 14px;
  }
  .note-box b { color: var(--text); font-weight: 600; }

  .reason {
    border-radius: 11px; padding: 14px 16px; margin-top: 14px; font-size: 13px;
  }
  .reason.warn { background: var(--warn-soft); border: 1px solid #fde68a; }
  .reason.err { background: var(--err-soft); border: 1px solid #fecaca; }
  .reason.info { background: var(--brand-soft); border: 1px solid #bfdbfe; }
  .reason-title { font-weight: 700; margin-bottom: 5px; }
  .reason code {
    font-family: Consolas, monospace; background: rgba(0,0,0,.05);
    padding: 1px 5px; border-radius: 4px; font-size: 12px;
  }

  /* ---------- Trace 时间轴 ---------- */
  .trace { position: relative; padding-left: 22px; }
  .trace::before {
    content: ""; position: absolute; left: 5px; top: 6px; bottom: 6px;
    width: 1px; background: var(--border-strong);
  }
  .trace-item { position: relative; padding-bottom: 14px; }
  .trace-item:last-child { padding-bottom: 0; }
  .trace-item::before {
    content: ""; position: absolute; left: -21px; top: 6px;
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--brand); box-shadow: 0 0 0 3px #fff;
  }
  .trace-item.err::before { background: var(--err); }
  .trace-item.end::before { background: var(--ok); }
  .trace-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .trace-step {
    font-size: 10px; font-weight: 700; color: var(--muted);
    background: var(--surface-soft); border: 1px solid var(--border);
    border-radius: 5px; padding: 1px 6px;
  }
  .trace-action {
    font-family: Consolas, "Courier New", monospace; font-size: 12.5px;
    font-weight: 700; color: #1f2937;
  }
  .trace-result { font-size: 12.5px; color: #4b5563; margin-top: 3px; word-break: break-word; }
  .trace-item.err .trace-result { color: var(--err); }
  .trace-why {
    font-size: 11.5px; color: #8b93a1; margin-top: 4px;
    border-left: 2px solid var(--border); padding-left: 8px;
  }

  pre {
    background: var(--surface-soft); border: 1px solid var(--border);
    padding: 12px; border-radius: 9px; font-size: 12px; overflow-x: auto;
    font-family: Consolas, monospace; margin: 0; color: #374151;
  }
  .muted { color: var(--muted); }
  .hidden { display: none !important; }

  .fade-in { animation: fadeIn .28s ease both; }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .fade-in { animation: none; }
    .spinner { animation-duration: 1.4s; }
  }
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round">
        <path d="M5 4.5v15M5 12h5M10 4.5v15"/>
        <path d="M15 8.5l6 3.5-6 3.5z"/>
      </svg>
    </div>
    <div>
      <div class="brand-name">短视频脚本 Agent</div>
      <div class="brand-sub">ReAct 循环 · 模型自主决策 · 事实可追溯</div>
    </div>
    <div class="topbar-spacer"></div>
    <div class="pill">草稿模式 · 不发布</div>
  </div>
</header>

<main class="layout">
  <section class="card">
    <div class="card-head">
      <div>
        <div class="card-title">创作参数</div>
        <div class="card-desc">Agent 将检索素材、估算时长并校验品牌规则</div>
      </div>
    </div>
    <div class="card-body">
      <div class="field">
        <div class="label">主题 <span class="req">*</span></div>
        <input id="topic" type="text" value="便携榨汁杯" placeholder="例如：便携榨汁杯">
      </div>

      <div class="field">
        <div class="label">目标时长（秒）<span class="req">*</span></div>
        <input id="duration" type="number" value="60" min="1" placeholder="留空可演示信息不足">
        <div class="chips">
          <button class="chip" type="button" data-dur="15">15s</button>
          <button class="chip" type="button" data-dur="30">30s</button>
          <button class="chip" type="button" data-dur="60">60s</button>
          <button class="chip" type="button" data-dur="90">90s</button>
        </div>
      </div>

      <div class="two">
        <div class="field">
          <div class="label">受众</div>
          <input id="audience" type="text" value="上班族">
        </div>
        <div class="field">
          <div class="label">风格</div>
          <input id="style" type="text" value="活泼">
        </div>
      </div>

      <div class="field">
        <div class="label">平台</div>
        <select id="platform">
          <option value="douyin">抖音（≤60s）</option>
          <option value="kuaishou">快手（≤60s）</option>
          <option value="xiaohongshu">小红书（≤90s）</option>
        </select>
      </div>

      <div class="switches">
        <label class="switch"><input id="mock" type="checkbox"> 离线 Mock 模式（不消耗调用额度）</label>
        <label class="switch"><input id="fail" type="checkbox"> 注入检索工具失败（演示 A4）</label>
      </div>

      <button class="submit" id="go">
        <span class="spinner"></span>
        <span id="go-text">生成脚本</span>
      </button>
      <div id="hint" class="hint hidden">模型决策中，真实模式约 10~60 秒…</div>
    </div>
  </section>

  <section>
    <div id="empty" class="empty">
      <div class="empty-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 5h16M4 12h10M4 19h13"/>
        </svg>
      </div>
      <div class="empty-title">等待生成</div>
      <div>填写左侧参数后点击「生成脚本」，这里将展示分镜、时长与执行轨迹</div>
    </div>

    <div id="result" class="hidden">
      <div class="card fade-in">
        <div class="card-body" id="out"></div>
      </div>
      <div class="card fade-in" style="margin-top:16px">
        <div class="card-head">
          <div>
            <div class="card-title">执行 Trace</div>
            <div class="card-desc">每步动作、工具返回与模型决策依据</div>
          </div>
        </div>
        <div class="card-body">
          <div id="steps" class="trace"></div>
        </div>
      </div>
    </div>
  </section>
</main>

<script>
const $ = id => document.getElementById(id);

const STATUS = { completed: "已完成", unfinished: "未完成", failed: "失败", needs_info: "待补充" };
const FIELD = { topic: "主题", duration: "目标时长" };
const TERMINAL = ["submit_script", "declare_unfinished", "report_failure", "request_info"];

document.querySelectorAll(".chip[data-dur]").forEach(b => {
  b.addEventListener("click", () => { $("duration").value = b.dataset.dur; });
});

$("go").addEventListener("click", async () => {
  const topic = $("topic").value.trim();
  if (!topic) { showError("请先填写主题"); $("topic").focus(); return; }
  const body = {
    topic,
    duration: $("duration").value ? Number($("duration").value) : null,
    audience: $("audience").value.trim(),
    platform: $("platform").value,
    style: $("style").value.trim(),
    mock: $("mock").checked,
    fail_inject: $("fail").checked ? ["search_materials"] : []
  };
  setLoading(true);
  try {
    const r = await fetch("/api/run", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    render(await r.json());
  } catch (e) {
    showError("请求失败：" + (e && e.message ? e.message : e));
  } finally {
    setLoading(false);
  }
});

function setLoading(on) {
  const btn = $("go");
  btn.disabled = on;
  btn.classList.toggle("loading", on);
  $("go-text").textContent = on ? "生成中…" : "生成脚本";
  $("hint").classList.toggle("hidden", !on);
}

function esc(s) { return String(s ?? "").replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function showResult() {
  $("empty").classList.add("hidden");
  $("result").classList.remove("hidden");
}

function showError(msg) {
  showResult();
  $("steps").innerHTML = "";
  $("out").innerHTML =
    `<div class="result-head"><span class="badge failed">请求异常</span></div>
     <div class="reason err"><div class="reason-title">未能取得结果</div>${esc(msg)}</div>`;
}

function render(data) {
  showResult();
  const o = data.output || {};
  $("out").innerHTML = data.status === "completed" ? viewCompleted(o) : viewOther(data.status, o);
  $("steps").innerHTML = viewTrace(data.steps || []);
  $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------- 完成态：指标 + 检查 + 分镜卡片 ---------- */
function viewCompleted(o) {
  const ck = o.checks || {};
  const dur = ck.duration || {};
  const rl = ck.rules || {};
  const within = dur.within_limit === true;
  const pass = rl.passed === true;

  const shots = (o.shots || []).map(s => {
    const tags = (s.material_ids || []).map(m => `<span class="tag">${esc(m)}</span>`).join("");
    const facts = (s.facts_from_materials || []).join(" / ");
    return `<div class="shot">
      <div class="shot-idx">${esc(s.idx)}</div>
      <div>
        <div class="shot-visual">${esc(s.visual)}</div>
        <div class="shot-narration">${esc(s.narration)}</div>
        <div class="shot-foot">
          <span class="tag time">${esc(s.seconds)}s</span>
          ${tags || `<span class="tag time" style="color:#9ca3af">无素材引用</span>`}
        </div>
        ${facts ? `<div class="fact">依据：${esc(facts)}</div>` : ""}
      </div>
    </div>`;
  }).join("");

  const violation = (rl.violations || []).length
    ? `<div class="note-box" style="border-color:#fecaca;color:#b91c1c">
        违规项：${esc((rl.violations || []).join("；"))}</div>` : "";

  return `<div class="result-head">
      <span class="badge completed">已完成</span>
      <span class="meta-line">${esc(o.note)}</span>
    </div>
    <div class="title-line">${esc(o.title)}</div>
    <div class="meta-line">素材来源：${esc((o.material_ids || []).join("、")) || "无"}</div>

    <div class="metrics">
      <div class="metric"><div class="metric-k">预计总时长</div>
        <div class="metric-v">${esc(o.total_seconds)}<small>秒</small></div></div>
      <div class="metric"><div class="metric-k">目标时长</div>
        <div class="metric-v">${esc(o.target_seconds)}<small>秒</small></div></div>
      <div class="metric"><div class="metric-k">剩余余量</div>
        <div class="metric-v">${esc(o.remaining_seconds)}<small>秒</small></div></div>
    </div>

    <div class="checks">
      <span class="check ${within ? "ok" : "bad"}"><span class="dot"></span>
        时长检查 ${within ? "达标" : "超限"}</span>
      <span class="check ${pass ? "ok" : "bad"}"><span class="dot"></span>
        规则检查 ${pass ? "通过" : "未通过"} · ${esc(rl.checked_shots)} 个分镜</span>
      <span class="check"><span class="dot"></span>共 ${esc((o.shots || []).length)} 个分镜</span>
    </div>

    <div class="section-label">分镜脚本</div>
    ${shots}
    ${violation}
    ${o.risk_notes ? `<div class="note-box"><b>风险说明：</b>${esc(o.risk_notes)}</div>` : ""}`;
}

/* ---------- 未完成 / 失败 / 待补充 ---------- */
function viewOther(status, o) {
  const cls = status === "failed" ? "err" : status === "unfinished" ? "warn" : "info";
  const label = STATUS[status] || status;
  let detail;
  if (status === "needs_info") {
    detail = `需要补充：<b>${(o.missing_fields || []).map(f => FIELD[f] || f).join("、")}</b>`;
  } else {
    detail = `<code>${esc(o.reason || "unknown")}</code>`;
    if (o.detail) detail += `<div class="muted" style="margin-top:6px">${esc(o.detail)}</div>`;
  }
  return `<div class="result-head"><span class="badge ${esc(status)}">${esc(label)}</span>
      <span class="meta-line">未产出可提交脚本</span></div>
    <div class="reason ${cls}">
      <div class="reason-title">${status === "failed" ? "任务失败" : status === "needs_info" ? "信息不足" : "任务未完成"}</div>
      ${detail}
    </div>
    <div class="section-label" style="margin-top:16px">返回数据</div>
    <pre>${esc(JSON.stringify(o, null, 2))}</pre>`;
}

/* ---------- Trace 时间轴 ---------- */
function viewTrace(steps) {
  if (!steps.length) return `<div class="muted">无步骤记录</div>`;
  return steps.map(s => {
    const err = (s.result_summary || "").startsWith("ERROR");
    const end = TERMINAL.includes(s.action);
    const cls = err ? "err" : (end ? "end" : "");
    return `<div class="trace-item ${cls}">
      <div class="trace-head">
        <span class="trace-step">${String(s.step).padStart(2, "0")}</span>
        <span class="trace-action">${esc(s.action)}</span>
      </div>
      <div class="trace-result">${esc(s.result_summary)}</div>
      ${s.rationale ? `<div class="trace-why">决策依据：${esc(s.rationale)}</div>` : ""}
    </div>`;
  }).join("");
}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
            task = {
                "topic": req.get("topic"),
                "audience": req.get("audience", ""),
                "platform": req.get("platform", "douyin"),
                "duration": req.get("duration"),
                "style": req.get("style", ""),
            }
            client = MockModelClient(task) if req.get("mock") else QwenClient()
            result = run_agent(task, client, fail_inject=set(req.get("fail_inject", [])))
            payload = {
                "status": result["status"],
                "output": result["output"],
                "steps": result["trace"]["steps"],
            }
            self._json(200, payload)
        except Exception as e:  # 边界：把异常也作为可见状态返回页面
            self._json(500, {"status": "failed", "output": {"reason": "server_error",
                             "detail": str(e)}, "steps": []})

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # 静音默认访问日志
        pass


def main() -> None:
    _load_dotenv_safe()
    p = argparse.ArgumentParser(description="短视频脚本 Agent Web 界面")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"短视频脚本 Agent Web 界面: http://{args.host}:{args.port}")
    print("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
