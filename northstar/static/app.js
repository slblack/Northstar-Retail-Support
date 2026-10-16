/* Northstar Retail Support — client script (plain JavaScript, no external dependencies).
 * All user, model and retrieved text is rendered with textContent, never innerHTML.
 * No secrets are ever stored in localStorage, sessionStorage or URLs. */
(function () {
  "use strict";

  const CSRF = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  const SUGGESTIONS = JSON.parse(document.getElementById("suggestions-data").textContent);
  const byId = (id) => document.getElementById(id);

  const STAGE_NAMES = {
    customer: "Customer", input: "Input shield", knowledge: "Store knowledge",
    context: "Context shield", model: "Model", output: "Output shield",
  };

  // ------------------------------------------------------------------ helpers
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null) continue;
        if (k === "text") node.textContent = String(v);
        else if (k === "className") node.className = v;
        else node.setAttribute(k, String(v));
      }
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function fmtMs(ms) {
    if (ms === null || ms === undefined) return "—";
    return ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms + " ms";
  }
  function fmtNum(n) { return (n === null || n === undefined) ? "—" : Number(n).toLocaleString("en-GB"); }

  async function api(path, body) {
    const opts = {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-CSRF-Token": CSRF, "Accept": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(path, opts);
    } catch (e) {
      return { ok: false, error: { message: "The local app could not be reached. Is it still running?" } };
    }
    let data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!data) return { ok: false, error: { message: "Unexpected response from the local app (HTTP " + resp.status + ")." } };
    return data;
  }

  // ------------------------------------------------------------------ config summary
  let currentConfig = null;
  function renderConfigSummary(cfg) {
    currentConfig = cfg;
    const o = cfg.openai_configured ? "OpenAI key configured" : "OpenAI key not configured";
    const a = cfg.ai_defense_configured ? "AI Defense key configured" : "AI Defense key not configured";
    byId("conn-summary").textContent = o + " · " + a + " · region " + cfg.ai_defense_region.toUpperCase();
  }
  async function loadConfig() {
    const res = await api("/api/config");
    if (res.ok) renderConfigSummary(res.config);
    else byId("conn-summary").textContent = "Configuration unavailable";
    return res;
  }

  // ------------------------------------------------------------------ composer
  const form = byId("compose-form");
  const question = byId("question");
  const select = byId("suggestion");
  const note = byId("scenario-note");
  const chip = byId("label-chip");
  const sendBtn = byId("send-btn");
  const clearBtn = byId("clear-btn");
  const status = byId("run-status");
  const maxChars = parseInt(question.getAttribute("maxlength"), 10);
  let selected = null;
  let running = false;

  function updateCount() {
    byId("char-count").textContent = question.value.length + " / " + maxChars + " characters";
  }
  function exactMatch() {
    const text = question.value.trim();
    return SUGGESTIONS.find((s) => s.message === text) || null;
  }
  function updateLabelChip() {
    const match = exactMatch();
    if (match) {
      chip.hidden = false;
      chip.dataset.expected = match.expected;
      chip.textContent = "Evaluation annotation: expected " + match.expected;
    } else if (selected) {
      chip.hidden = false;
      chip.dataset.expected = "";
      chip.textContent = "Edited — unlabelled (won’t be scored unless it exactly matches a defined case)";
    } else {
      chip.hidden = true;
    }
  }
  function renderNote(s) {
    clear(note);
    if (!s) {
      note.appendChild(el("p", { className: "note-empty", text: "Choose a suggested question to see its scenario, or type your own. Free-text messages are not scored unless they exactly match a defined evaluation case." }));
      return;
    }
    note.appendChild(el("p", {}, [el("span", { className: "cat", text: s.category }), " — " + s.title]));
    note.appendChild(el("p", { text: s.reason }));
    note.appendChild(el("p", { className: "muted", text: "Expected action “" + s.expected + "” is an evaluation annotation only; your live AI Defense policy decides." }));
  }

  select.addEventListener("change", () => {
    selected = SUGGESTIONS.find((s) => s.id === select.value) || null;
    if (selected) question.value = selected.message;
    renderNote(selected);
    updateCount();
    updateLabelChip();
  });
  question.addEventListener("input", () => { updateCount(); updateLabelChip(); });
  clearBtn.addEventListener("click", () => {
    if (running) return;
    question.value = "";
    select.value = "";
    selected = null;
    renderNote(null);
    updateCount();
    updateLabelChip();
    status.textContent = "";
    status.classList.remove("is-error");
    question.focus();
  });

  // ------------------------------------------------------------------ path rendering
  function stageText(st) {
    const t = st.duration_ms !== null && st.duration_ms !== undefined ? " · " + fmtMs(st.duration_ms) : "";
    switch (st.status) {
      case "ok": return "Done" + t;
      case "allow": return "Allowed" + t;
      case "block": return "Blocked" + t;
      case "error": return "Unavailable" + t;
      case "not_run": return "Not run";
      default: return "Waiting";
    }
  }

  function resetPath(pathId, state, badge, message) {
    const card = byId("path-" + pathId);
    card.querySelectorAll(".stage").forEach((li) => {
      li.dataset.status = "idle";
      li.querySelector(".stage-state").textContent = state === "running" ? "Pending" : "Waiting";
    });
    const outcome = card.querySelector(".outcome");
    outcome.dataset.state = state;
    outcome.querySelector(".outcome-badge").textContent = badge;
    const answer = outcome.querySelector(".answer");
    clear(answer);
    answer.appendChild(el("p", { className: "muted", text: message }));
    outcome.querySelector(".refusal-note").hidden = true;
    card.querySelectorAll(".stats dd").forEach((dd) => { dd.textContent = "—"; });
  }

  function outcomeCopy(path, res) {
    const stageName = res.blocked_stage ? STAGE_NAMES[res.blocked_stage] : "";
    if (res.status === "answered") return { badge: res.incomplete ? "Answered (truncated)" : "Answered", text: res.answer };
    if (res.status === "blocked") {
      let text;
      if (res.blocked_stage === "output") {
        text = "AI Defense blocked the generated response at the Output shield. The model did produce a response, but it has been withheld and is not shown anywhere.";
      } else {
        text = "AI Defense blocked this request at the " + stageName + ". The model was not called on this path.";
      }
      return { badge: "Blocked — " + stageName, text: text };
    }
    if (res.status === "inspection_unavailable") {
      const msg = res.error && res.error.message ? res.error.message : "Inspection did not return a usable decision.";
      const stage = res.error && res.error.stage ? STAGE_NAMES[res.error.stage] + ": " : "";
      return { badge: "Inspection unavailable", text: stage + msg + " The protected path fails closed: no answer is released and nothing falls back to the unprotected path." };
    }
    const msg = res.error && res.error.message ? res.error.message : "The request could not be completed.";
    return { badge: "Error", text: msg };
  }

  function renderPath(pathId, res, run) {
    const card = byId("path-" + pathId);
    const byStage = {};
    (res.stages || []).forEach((st) => { byStage[st.id] = st; });
    card.querySelectorAll(".stage").forEach((li) => {
      const st = byStage[li.dataset.stage];
      li.dataset.status = st ? st.status : "not_run";
      li.querySelector(".stage-state").textContent = st ? stageText(st) : "Not run";
    });

    const outcome = card.querySelector(".outcome");
    outcome.dataset.state = res.status;
    const copy = outcomeCopy(pathId, res);
    outcome.querySelector(".outcome-badge").textContent = copy.badge;
    const answer = outcome.querySelector(".answer");
    clear(answer);
    answer.appendChild(document.createTextNode(copy.text || ""));
    outcome.querySelector(".refusal-note").hidden = !(res.status === "answered" && res.refusal_heuristic);

    const u = res.usage || {};
    const t = res.timings || {};
    const set = (k, v) => { card.querySelector('[data-stat="' + k + '"]').textContent = v; };
    set("in", fmtNum(u.input));
    set("out", fmtNum(u.output));
    set("total", fmtNum(u.total));
    set("gen", fmtMs(t.generation_ms));
    set("insp", pathId === "baseline" ? "None" : fmtMs(t.inspection_ms));
    set("time", fmtMs(t.total_ms));

    renderTrace(card.querySelector(".trace"), pathId, res, run);
  }

  function renderTrace(container, pathId, res, run) {
    clear(container);
    const facts = el("table", {}, [
      el("tbody", {}, [
        row("Run ID", el("code", { text: run.run_id })),
        row("Model", el("code", { text: res.model })),
        row("Model called", res.model_called ? "Yes" : "No"),
        row("AI Defense inspection calls", String(res.inspection_calls)),
        row("Input SHA-256", el("code", { text: res.input_digest })),
      ]),
    ]);
    container.appendChild(el("h3", { text: "Run facts" }));
    container.appendChild(facts);

    container.appendChild(el("h3", { text: "Retrieved store knowledge" + (run.retrieval.fallback ? " (fallback: no keyword match)" : "") }));
    if (pathId === "protected" && res.status === "blocked" && res.blocked_stage === "input") {
      container.appendChild(el("p", { className: "muted", text: "Retrieved once for the run, but not used on this path because the input shield blocked first." }));
    }
    run.retrieval.articles.forEach((a) => {
      container.appendChild(el("div", { className: "art" }, [
        el("strong", { text: a.title }), " ",
        el("code", { text: a.id + " · score " + a.score }),
        el("p", { text: a.text }),
        el("p", { className: "muted", text: "Source: " + a.source + " — supplied to the model as data, not instructions." }),
      ]));
    });

    container.appendChild(el("h3", { text: "Stage trace" }));
    const tbody = el("tbody");
    (res.stages || []).forEach((st) => {
      const details = [];
      if (st.note) details.push(el("div", { text: st.note }));
      if (st.detail) details.push(el("div", { text: st.detail }));
      const ins = st.inspection;
      if (ins) {
        if (ins.action) details.push(el("div", {}, ["Provider action: ", el("code", { text: ins.action })]));
        if (ins.error) details.push(el("div", { text: "Error: " + ins.error.message }));
        if (ins.classifications && ins.classifications.length) details.push(el("div", {}, ["Classifications: ", el("code", { text: ins.classifications.join(", ") })]));
        if (ins.rules && ins.rules.length) {
          const names = ins.rules.map((r) => [r.rule_name, r.classification].filter(Boolean).join(" / ")).filter(Boolean);
          if (names.length) details.push(el("div", {}, ["Rules: ", el("code", { text: names.join("; ") })]));
        }
        if (ins.severity) details.push(el("div", {}, ["Severity: ", el("code", { text: ins.severity })]));
        if (ins.attack_technique && ins.attack_technique !== "NONE_ATTACK_TECHNIQUE") details.push(el("div", {}, ["Technique: ", el("code", { text: ins.attack_technique })]));
        if (typeof ins.is_safe === "boolean") details.push(el("div", { className: "muted", text: "is_safe: " + ins.is_safe + " (informational; enforcement uses the action)" }));
        if (ins.event_id) details.push(el("div", {}, ["Event: ", el("code", { text: ins.event_id })]));
        details.push(el("div", {}, ["Transaction: ", el("code", { text: ins.client_transaction_id_sent })]));
      }
      tbody.appendChild(el("tr", {}, [
        el("td", { text: st.label }),
        el("td", {}, [el("span", { className: "pill " + st.status, text: stageText(st) })]),
        el("td", {}, details),
      ]));
    });
    container.appendChild(el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Stage" }), el("th", { text: "Outcome" }), el("th", { text: "Details" })])]),
      tbody,
    ]));
    if (pathId === "baseline") {
      container.appendChild(el("p", { className: "muted", text: "No AI Defense calls are made on this path. The model’s own safety behaviour still applies." }));
    }
  }
  function row(label, value) {
    return el("tr", {}, [el("th", { text: label }), el("td", {}, [typeof value === "string" ? document.createTextNode(value) : value])]);
  }

  // ------------------------------------------------------------------ metrics
  const metrics = { scored: 0, match: 0, false_positive: 0, miss: 0, unscored: 0 };
  function recordScore(score) {
    if (score && score.scored) {
      metrics.scored += 1;
      metrics[score.outcome] += 1;
    } else {
      metrics.unscored += 1;
    }
    byId("m-scored").textContent = metrics.scored;
    byId("m-match").textContent = metrics.match;
    byId("m-fp").textContent = metrics.false_positive;
    byId("m-miss").textContent = metrics.miss;
    byId("m-unscored").textContent = metrics.unscored;
  }
  function scoreSentence(score, label) {
    if (!label) return "Unlabelled question — not scored.";
    if (!score.scored) return "Not scored: " + (score.reason === "provider_error" ? "a provider error or unavailable inspection occurred." : "unlabelled.");
    const words = { match: "Match", false_positive: "False positive", miss: "Miss" };
    return words[score.outcome] + " — expected " + score.expected + ", AI Defense outcome " + score.actual + " (" + label.case_id + ").";
  }

  // ------------------------------------------------------------------ submit
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (running) return;
    const text = question.value.trim();
    if (!text) {
      status.textContent = "Enter a customer message first.";
      status.classList.add("is-error");
      question.focus();
      return;
    }
    if (text.length > maxChars) {
      status.textContent = "The message must be at most " + maxChars + " characters.";
      status.classList.add("is-error");
      return;
    }
    running = true;
    sendBtn.disabled = true;
    clearBtn.disabled = true;
    select.disabled = true;
    question.setAttribute("aria-busy", "true");
    status.classList.remove("is-error");
    status.textContent = "Running both paths… this usually takes a few seconds.";
    resetPath("baseline", "running", "Running…", "Waiting for the model…");
    resetPath("protected", "running", "Running…", "Waiting for AI Defense and the model…");

    const res = await api("/api/compare", { question: text });
    running = false;
    sendBtn.disabled = false;
    clearBtn.disabled = false;
    select.disabled = false;
    question.removeAttribute("aria-busy");

    if (!res.ok) {
      status.textContent = (res.error && res.error.message) || "The comparison could not be run.";
      status.classList.add("is-error");
      resetPath("baseline", "idle", "No result", "No result for this attempt.");
      resetPath("protected", "idle", "No result", "No result for this attempt.");
      return;
    }
    const run = res.run;
    renderPath("baseline", run.baseline, run);
    renderPath("protected", run.protected, run);
    byId("run-meta").hidden = false;
    byId("run-id").textContent = run.run_id;
    byId("run-model").textContent = run.model;
    byId("run-digest").textContent = run.input_digest;
    const dm = byId("digest-match");
    dm.textContent = run.digests_match ? "✓ identical on both paths" : "✗ mismatch";
    dm.classList.toggle("bad", !run.digests_match);
    recordScore(run.score);
    status.textContent = "Done in " + fmtMs(run.total_ms) + ". " + scoreSentence(run.score, run.label);
  });

  // ------------------------------------------------------------------ setup dialog
  const dialog = byId("setup-dialog");
  const openBtn = byId("open-setup");
  const setupForm = byId("setup-form");
  const keyFields = [byId("openai-key"), byId("aid-key")];
  let opener = null;

  function setKeyStatus(id, configured) {
    const node = byId(id);
    node.textContent = configured ? "Configured — enter a new key to replace it" : "Not configured";
    node.classList.toggle("configured", !!configured);
  }
  function placeholders(cfg) {
    byId("openai-key").placeholder = cfg.openai_configured ? "•••••••••••• (saved)" : "sk-…";
    byId("aid-key").placeholder = cfg.ai_defense_configured ? "•••••••••••• (saved)" : "Paste inspection API key";
  }
  function fillSetup(cfg) {
    setKeyStatus("openai-key-status", cfg.openai_configured);
    setKeyStatus("aid-key-status", cfg.ai_defense_configured);
    placeholders(cfg);
    byId("openai-model").value = cfg.openai_model;
    byId("aid-region").value = cfg.ai_defense_region;
    byId("aid-conn").value = cfg.ai_defense_connection_name || "";
  }
  function wipeSecrets() { keyFields.forEach((f) => { f.value = ""; }); }
  function resetMessages() {
    ["verify-openai-result", "verify-aid-result", "save-status"].forEach((id) => {
      const n = byId(id); n.textContent = ""; n.className = n.className.split(" ")[0];
    });
  }

  openBtn.addEventListener("click", async () => {
    opener = document.activeElement;
    wipeSecrets();
    resetMessages();
    byId("save-status").textContent = "Loading settings…";
    dialog.showModal();
    const res = await loadConfig();
    if (res.ok) {
      fillSetup(res.config);
      byId("save-status").textContent = "";
    } else {
      byId("save-status").textContent = (res.error && res.error.message) || "Could not load settings.";
      byId("save-status").className = "save-status bad";
    }
    byId("openai-key").focus();
  });

  function closeDialog() {
    wipeSecrets();
    if (dialog.open) dialog.close();
  }
  dialog.addEventListener("close", () => {
    wipeSecrets();
    resetMessages();
    if (opener && typeof opener.focus === "function") opener.focus();
  });
  dialog.addEventListener("cancel", () => { wipeSecrets(); }); // Escape key
  byId("setup-close").addEventListener("click", closeDialog);
  byId("setup-cancel").addEventListener("click", closeDialog);

  function showVerify(nodeId, result) {
    const node = byId(nodeId);
    node.textContent = result.message;
    let cls = "bad";
    if (result.ok) cls = "ok";
    else if (result.outcome === "authenticated_no_policy_decision" || result.outcome === "model_unavailable") cls = "warn";
    node.className = "verify-result " + cls;
  }
  async function runVerify(btn, nodeId, path, body) {
    btn.disabled = true;
    const node = byId(nodeId);
    node.className = "verify-result";
    node.textContent = "Verifying…";
    const res = await api(path, body);
    btn.disabled = false;
    if (res.ok) showVerify(nodeId, res.result);
    else showVerify(nodeId, { ok: false, outcome: "error", message: (res.error && res.error.message) || "Verification failed." });
  }
  byId("verify-openai").addEventListener("click", (e) => {
    runVerify(e.currentTarget, "verify-openai-result", "/api/verify/openai", {
      api_key: byId("openai-key").value, model: byId("openai-model").value,
    });
  });
  byId("verify-aid").addEventListener("click", (e) => {
    runVerify(e.currentTarget, "verify-aid-result", "/api/verify/ai-defense", {
      api_key: byId("aid-key").value, region: byId("aid-region").value,
    });
  });

  setupForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const saveBtn = byId("setup-save");
    const out = byId("save-status");
    saveBtn.disabled = true;
    out.className = "save-status";
    out.textContent = "Saving…";
    const body = {
      openai_model: byId("openai-model").value,
      ai_defense_region: byId("aid-region").value,
      ai_defense_connection_name: byId("aid-conn").value,
    };
    if (byId("openai-key").value.trim()) body.openai_api_key = byId("openai-key").value;
    if (byId("aid-key").value.trim()) body.ai_defense_api_key = byId("aid-key").value;
    const res = await api("/api/config", body);
    saveBtn.disabled = false;
    wipeSecrets();
    if (res.ok) {
      fillSetup(res.config);
      renderConfigSummary(res.config);
      out.className = "save-status ok";
      out.textContent = "Settings saved. They apply to the next comparison.";
    } else {
      out.className = "save-status bad";
      out.textContent = (res.error && res.error.message) || "Settings could not be saved.";
    }
  });

  // ------------------------------------------------------------------ init
  updateCount();
  loadConfig();
})();
