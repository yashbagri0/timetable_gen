/* app.js — SPA logic. Vanilla, no framework. */
(function () {
  "use strict";

  // ============================================================
  // Constants
  // ============================================================
  const RANK_OPTIONS    = ["Assistant", "Associate", "Professor"];
  const SUBJECT_TYPES   = ["DSC", "DSE", "GE", "SEC", "VAC", "AEC"];
  const TIME_LABELS     = ["None", "Morning", "Afternoon", "Evening"];
  const DAY_OPTIONS     = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const TEACHING_MODES  = [
    { id: "normal", label: "Normal" },
    { id: "co",     label: "Co-teaching" },
    { id: "split",  label: "Split" },
  ];
  const BUILTIN_DEPARTMENTS = [
    "Computer Science", "Mathematics", "Physics", "Chemistry",
    "Biology", "Electronics", "Economics", "English", "Hindi",
    "History", "Political Science", "Commerce",
  ];
  const ADD_NEW = "__add_new__";

  // ============================================================
  // State
  // ============================================================
  let userData   = null;
  // Generate-page state (declared up here so persist() and the gate function
  // can both reference these without temporal-dead-zone gotchas).
  let excelBuilt = false;
  let solving    = false;

  // ============================================================
  // Sidebar navigation
  // ============================================================
  function showSection(name) {
    document.querySelectorAll(".nav-item").forEach((b) =>
      b.classList.toggle("active", b.dataset.section === name));
    document.querySelectorAll(".section").forEach((p) =>
      p.classList.toggle("active", p.id === name));
    if (name === "dashboard")   refreshDashboard();
    if (name === "preferences") renderPreferences();   // teacher list may have changed
    if (name === "subjects")    renderSubjects();      // teacher list may have changed
    if (name === "generate")    refreshGenerateGate();
    if (name === "results")     loadResults();
  }
  document.querySelectorAll(".nav-item").forEach((btn) =>
    btn.addEventListener("click", () => showSection(btn.dataset.section)));
  const dashGo = document.getElementById("dash-go");
  if (dashGo) dashGo.addEventListener("click", () => showSection("generate"));

  // ============================================================
  // Save-status flash
  // ============================================================
  let statusTimer = null;
  function flashStatus(msg, ok = true) {
    const el = document.getElementById("save-status");
    el.textContent = msg;
    el.style.color = ok ? "var(--good)" : "var(--bad)";
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => (el.textContent = ""), 2200);
  }

  // ============================================================
  // Settings form binding (Configuration page)
  // ============================================================
  function getNested(o, path) {
    return path.split(".").reduce((c, k) => (c == null ? undefined : c[k]), o);
  }
  function setNested(o, path, value) {
    const keys = path.split(".");
    let c = o;
    for (let i = 0; i < keys.length - 1; i++) {
      c[keys[i]] = c[keys[i]] || {};
      c = c[keys[i]];
    }
    c[keys[keys.length - 1]] = value;
  }
  function fillSettingsForm(data) {
    const form = document.getElementById("settings-form");
    form.querySelectorAll("input, select").forEach((el) => {
      const v = getNested(data, el.name);
      if (v === undefined || v === null) return;
      if (el.type === "checkbox") el.checked = !!v;
      else el.value = v;
    });
  }
  function readSettingsForm() {
    const form = document.getElementById("settings-form");
    form.querySelectorAll("input, select").forEach((el) => {
      let v;
      if (el.type === "checkbox")    v = el.checked;
      else if (el.type === "number") v = el.value === "" ? null : Number(el.value);
      else                           v = el.value;
      setNested(userData, el.name, v);
    });
  }

  // ============================================================
  // Domain helpers
  // ============================================================
  function deriveInitials(fullName) {
    if (!fullName) return "";
    // Strip honorifics and split on whitespace.
    const HONORIFICS = /^(Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Prof\.?)$/i;
    const parts = String(fullName).trim().split(/\s+/).filter((w) => !HONORIFICS.test(w));
    if (parts.length === 0) return "";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return parts.map((p) => p[0]).join("").toUpperCase().slice(0, 4);
  }
  function getAllDepartments() {
    const set = new Set(BUILTIN_DEPARTMENTS);
    (userData.teachers  || []).forEach((t) => t.department && set.add(t.department));
    (userData.subjects  || []).forEach((s) => s.department && set.add(s.department));
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }
  function getTeacherFullNames() {
    return (userData.teachers || [])
      .map((t) => (t.full_name || "").trim())
      .filter(Boolean);
  }
  function getCapForRank(rankRaw) {
    const r = String(rankRaw || "").toLowerCase();
    return (userData.rank_caps && userData.rank_caps[r]) ||
           ({ assistant: 14, associate: 14, professor: 16 })[r] || 14;
  }

  // ============================================================
  // Subject schema: legacy ⇄ rich migration
  // ============================================================
  function ensureSubjectShape(s) {
    // Idempotent: only fill richer fields if they're missing.
    if (s.teaching_mode) return s;

    const teacher = String(s.teacher || "").trim();
    const hours   = String(s.hours   || "").trim();

    if (teacher.includes("|") && hours.includes("|")) {
      const tparts = teacher.split("|").map((t) => t.trim());
      const hparts = hours.split("|").map((h) => h.trim());
      s.teaching_mode  = "split";
      s.teachers_list  = [];
      s.lectures = 0; s.tutorials = 0; s.practicals = 0;
      s.split_entries  = tparts.map((t, i) => {
        const [le, tu, pr] = (hparts[i] || "0,0,0").split(",")
          .map((x) => Number(String(x).trim()) || 0);
        return { teacher: t, lectures: le, tutorials: tu, practicals: pr };
      });
    } else if (teacher.includes(",")) {
      const list = teacher.split(",").map((t) => t.trim()).filter(Boolean);
      const [le, tu, pr] = (hours || "0,0,0").split(",")
        .map((x) => Number(String(x).trim()) || 0);
      s.teaching_mode  = "co";
      s.teachers_list  = list;
      s.lectures = le; s.tutorials = tu; s.practicals = pr;
      s.split_entries  = [];
    } else {
      const [le, tu, pr] = (hours || "0,0,0").split(",")
        .map((x) => Number(String(x).trim()) || 0);
      s.teaching_mode  = "normal";
      s.teachers_list  = teacher ? [teacher] : [];
      s.lectures = le; s.tutorials = tu; s.practicals = pr;
      s.split_entries  = [];
    }
    return s;
  }
  function syncLegacy(s) {
    if (s.teaching_mode === "split") {
      const valid = (s.split_entries || []).filter((e) => (e.teacher || "").trim());
      s.teacher = valid.map((e) => e.teacher.trim()).join(" | ");
      s.hours   = valid.map((e) =>
        `${+e.lectures || 0},${+e.tutorials || 0},${+e.practicals || 0}`
      ).join(" | ");
    } else if (s.teaching_mode === "co") {
      s.teacher = (s.teachers_list || []).filter(Boolean).join(", ");
      s.hours   = `${+s.lectures || 0},${+s.tutorials || 0},${+s.practicals || 0}`;
    } else {
      s.teacher = ((s.teachers_list || [])[0] || "").trim();
      s.hours   = `${+s.lectures || 0},${+s.tutorials || 0},${+s.practicals || 0}`;
    }
  }

  // ============================================================
  // Cell builders
  // ============================================================
  function inputCell(value, onChange, opts = {}) {
    const td = document.createElement("td");
    const inp = document.createElement("input");
    inp.value = value == null ? "" : value;
    if (opts.placeholder) inp.placeholder = opts.placeholder;
    if (opts.type)        inp.type        = opts.type;
    inp.addEventListener("input", () => onChange(inp.value));
    td.appendChild(inp);
    return { td, input: inp };
  }
  function numberCell(value, onChange, { min = 0, max = 9, width = 40 } = {}) {
    const td = document.createElement("td");
    const inp = document.createElement("input");
    inp.type = "number"; inp.min = min; inp.max = max;
    inp.value = value == null ? 0 : value;
    inp.style.width = width + "px";
    inp.addEventListener("input", () => onChange(Number(inp.value) || 0));
    td.appendChild(inp);
    return td;
  }
  function selectCell(value, options, onChange) {
    const td = document.createElement("td");
    const sel = document.createElement("select");
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt; o.textContent = opt; sel.appendChild(o);
    }
    sel.value = value == null ? "" : value;
    sel.addEventListener("change", () => onChange(sel.value));
    td.appendChild(sel);
    return { td, select: sel };
  }
  function deleteCell(onClick) {
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "del-btn"; btn.title = "Delete row"; btn.textContent = "✕";
    btn.addEventListener("click", onClick);
    td.appendChild(btn);
    return td;
  }

  // ---------- Department combo (select with "Add new…") -------------------
  function departmentCellInline(value, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "dept-cell";
    const sel = document.createElement("select");
    const options = getAllDepartments();
    if (value && !options.includes(value)) options.push(value);
    options.sort((a, b) => a.localeCompare(b));
    sel.appendChild(opt("",       "—"));
    for (const d of options) sel.appendChild(opt(d, d));
    sel.appendChild(opt(ADD_NEW, "+ Add new…"));
    sel.value = value || "";

    const inp = document.createElement("input");
    inp.type = "text"; inp.placeholder = "New department";
    inp.style.display = "none";

    sel.addEventListener("change", () => {
      if (sel.value === ADD_NEW) {
        sel.style.display = "none";
        inp.style.display = "";
        inp.value = "";
        inp.focus();
      } else {
        onChange(sel.value);
      }
    });
    inp.addEventListener("blur", () => commitNew());
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); commitNew(); } });
    function commitNew() {
      const v = inp.value.trim();
      sel.style.display = ""; inp.style.display = "none";
      if (v) onChange(v);
      else   sel.value = value || "";
    }

    wrap.appendChild(sel); wrap.appendChild(inp);
    return wrap;
  }
  function departmentCell(value, onChange) {
    const td = document.createElement("td");
    td.appendChild(departmentCellInline(value, onChange));
    return td;
  }

  // ---------- Single teacher select (only existing teachers) --------------
  function teacherSelectInline(value, onChange) {
    const sel = document.createElement("select");
    sel.appendChild(opt("", "— pick teacher —"));
    for (const name of getTeacherFullNames()) sel.appendChild(opt(name, name));
    if (value && !getTeacherFullNames().includes(value)) sel.appendChild(opt(value, value + " (missing)"));
    sel.value = value || "";
    sel.addEventListener("change", () => onChange(sel.value));
    return sel;
  }

  // ---------- Multi-teacher chips (Co-teaching) ---------------------------
  function teacherChipsInline(selectedList, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "chips";
    selectedList.forEach((name, i) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      const txt = document.createElement("span");
      txt.textContent = name;
      const x = document.createElement("button");
      x.className = "chip-x"; x.type = "button"; x.textContent = "×";
      x.title = "Remove";
      x.addEventListener("click", () => {
        const next = [...selectedList]; next.splice(i, 1); onChange(next);
      });
      chip.appendChild(txt); chip.appendChild(x);
      wrap.appendChild(chip);
    });
    const remaining = getTeacherFullNames().filter((t) => !selectedList.includes(t));
    if (remaining.length) {
      const sel = document.createElement("select");
      sel.appendChild(opt("", "+ Add teacher"));
      for (const t of remaining) sel.appendChild(opt(t, t));
      sel.addEventListener("change", () => {
        if (sel.value) onChange([...selectedList, sel.value]);
      });
      wrap.appendChild(sel);
    }
    return wrap;
  }

  // ---------- Hours triple (Le / Tu / Pr) ---------------------------------
  function hoursTripleInline(le, tu, pr, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "hours-triple";
    wrap.appendChild(triple("Le", le, (v) => onChange("lectures",   v)));
    wrap.appendChild(triple("Tu", tu, (v) => onChange("tutorials",  v)));
    wrap.appendChild(triple("Pr", pr, (v) => onChange("practicals", v)));
    return wrap;
    function triple(label, val, cb) {
      const g = document.createElement("div"); g.className = "h-group";
      const lab = document.createElement("span"); lab.className = "h-label"; lab.textContent = label;
      const inp = document.createElement("input");
      inp.type = "number"; inp.min = 0; inp.max = 9; inp.value = val == null ? 0 : val;
      inp.addEventListener("input", () => cb(Number(inp.value) || 0));
      g.appendChild(inp); g.appendChild(lab);
      return g;
    }
  }

  // ---------- Mode toggle for subjects ------------------------------------
  function modeToggleInline(current, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "mode-toggle";
    for (const m of TEACHING_MODES) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = m.label;
      if (m.id === current) b.classList.add("active");
      b.addEventListener("click", () => onChange(m.id));
      wrap.appendChild(b);
    }
    return wrap;
  }

  // ---------- Days-of-week checkbox row -----------------------------------
  function daysRowInline(selected, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "days-row";
    for (const d of DAY_OPTIONS) {
      const lab = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = (selected || []).map(String).map((x) => x.slice(0, 3)).includes(d);
      cb.addEventListener("change", () => {
        const cur = new Set((selected || []));
        if (cb.checked) cur.add(d); else cur.delete(d);
        onChange(Array.from(cur));
      });
      const txt = document.createElement("span"); txt.textContent = d;
      lab.appendChild(cb); lab.appendChild(txt);
      wrap.appendChild(lab);
    }
    return wrap;
  }

  function opt(value, label) {
    const o = document.createElement("option");
    o.value = value; o.textContent = label;
    return o;
  }

  // ============================================================
  // Renders — Teachers
  // ============================================================
  function renderTeachers() {
    const tbody = document.querySelector("#teachers-table tbody");
    tbody.innerHTML = "";
    (userData.teachers || []).forEach((t, idx) => {
      const tr = document.createElement("tr");

      // Initials get auto-derived when full_name changes (only if user hasn't
      // manually edited the initials box; we mirror the auto value into a
      // private flag and stop overwriting after manual edits).
      const fnCell = inputCell(t.full_name, (v) => {
        t.full_name = v;
        if (!t._initials_manual) {
          t.initials = deriveInitials(v);
          initInput.value = t.initials;
        }
      });
      tr.appendChild(fnCell.td);

      const initialsCell = inputCell(t.initials || "", (v) => {
        t._initials_manual = true;
        t.initials = v.toUpperCase();
        initInput.value = t.initials;
      });
      const initInput = initialsCell.input;
      initInput.style.textTransform = "uppercase";
      tr.appendChild(initialsCell.td);

      // Rank (with cap badge)
      const rankTd = document.createElement("td");
      const rankWrap = document.createElement("div");
      rankWrap.className = "rank-cell";
      const rankSel = document.createElement("select");
      for (const r of RANK_OPTIONS) rankSel.appendChild(opt(r, r));
      rankSel.value = t.rank || "Assistant";
      const badge = document.createElement("span");
      badge.className = "cap-badge";
      const repaintBadge = () => {
        const cap = getCapForRank(rankSel.value);
        badge.textContent = `→ ${cap}h`;
      };
      repaintBadge();
      rankSel.addEventListener("change", () => {
        t.rank = rankSel.value; repaintBadge();
      });
      rankWrap.appendChild(rankSel); rankWrap.appendChild(badge);
      rankTd.appendChild(rankWrap);
      tr.appendChild(rankTd);

      // Department
      tr.appendChild(departmentCell(t.department || "", (v) => (t.department = v)));

      // Delete (also nukes orphan preferences referencing this teacher)
      tr.appendChild(deleteCell(() => {
        const removedName = (t.full_name || "").trim();
        userData.teachers.splice(idx, 1);
        if (removedName) {
          userData.preferences = (userData.preferences || []).filter(
            (p) => (p.full_name || "").trim() !== removedName
          );
        }
        renderTeachers(); renderPreferences(); renderSubjects(); renderDashboard();
        refreshGenerateGate();
      }));

      tbody.appendChild(tr);
    });
  }
  document.getElementById("add-teacher").addEventListener("click", () => {
    userData.teachers.push({ full_name: "", initials: "", rank: "Assistant", department: "" });
    renderTeachers();
    renderDashboard();
    refreshGenerateGate();
  });

  // ============================================================
  // Renders — Subjects
  // ============================================================
  function renderSubjects() {
    const tbody = document.querySelector("#subjects-table tbody");
    tbody.innerHTML = "";

    (userData.subjects || []).forEach((s, idx) => {
      ensureSubjectShape(s);

      const tr = document.createElement("tr");
      tr.appendChild(inputCell(s.course,   (v) => (s.course = v)).td);
      tr.appendChild(inputCell(s.semester, (v) => (s.semester = v ? Number(v) : null), { type: "number" }).td);
      tr.appendChild(inputCell(s.subject,  (v) => (s.subject = v)).td);
      tr.appendChild(inputCell(s.section,  (v) => (s.section = v.toUpperCase())).td);

      // Mode + Teacher(s) combined into one cell — looks cleaner than two.
      const modeTd = document.createElement("td");
      const modeWrap = document.createElement("div");
      modeWrap.style.display = "flex"; modeWrap.style.flexDirection = "column"; modeWrap.style.gap = "6px";
      const toggle = modeToggleInline(s.teaching_mode, (m) => {
        s.teaching_mode = m;
        if (m === "split" && (!s.split_entries || s.split_entries.length < 2)) {
          s.split_entries = [
            { teacher: (s.teachers_list || [])[0] || "", lectures: s.lectures || 0, tutorials: s.tutorials || 0, practicals: 0 },
            { teacher: "",                                lectures: 0, tutorials: 0, practicals: s.practicals || 0 },
          ];
        }
        if (m === "co" && (!s.teachers_list || s.teachers_list.length === 0)) {
          s.teachers_list = [];
        }
        if (m === "normal" && s.teachers_list.length > 1) {
          s.teachers_list = [s.teachers_list[0]];
        }
        syncLegacy(s); renderSubjects(); refreshGenerateGate();
      });
      modeWrap.appendChild(toggle);

      // Teachers picker (mode-aware)
      const tWrap = document.createElement("div");
      function rebuildTeachers() {
        tWrap.innerHTML = "";
        if (s.teaching_mode === "normal") {
          const sel = teacherSelectInline((s.teachers_list || [])[0] || "", (v) => {
            s.teachers_list = v ? [v] : [];
            syncLegacy(s); refreshGenerateGate();
          });
          tWrap.appendChild(sel);
        } else if (s.teaching_mode === "co") {
          tWrap.appendChild(teacherChipsInline(s.teachers_list || [], (next) => {
            s.teachers_list = next; syncLegacy(s); rebuildTeachers(); refreshGenerateGate();
          }));
        } else { // split
          const split = document.createElement("div");
          split.className = "split-rows";
          (s.split_entries || []).forEach((e, i) => {
            const row = document.createElement("div"); row.className = "split-row";
            row.appendChild(teacherSelectInline(e.teacher || "", (v) => {
              e.teacher = v; syncLegacy(s); refreshGenerateGate();
            }));
            row.appendChild(hoursTripleInline(e.lectures || 0, e.tutorials || 0, e.practicals || 0,
              (field, val) => { e[field] = val; syncLegacy(s); refreshGenerateGate(); }));
            split.appendChild(row);
          });
          tWrap.appendChild(split);
        }
      }
      rebuildTeachers();
      modeWrap.appendChild(tWrap);
      modeTd.appendChild(modeWrap);
      tr.appendChild(modeTd);

      // Hours triple — only for normal/co (split has its own per-entry inputs)
      const hoursTd = document.createElement("td");
      if (s.teaching_mode !== "split") {
        hoursTd.appendChild(hoursTripleInline(s.lectures || 0, s.tutorials || 0, s.practicals || 0,
          (field, val) => { s[field] = val; syncLegacy(s); refreshGenerateGate(); }));
      } else {
        const hint = document.createElement("span");
        hint.className = "muted";
        hint.textContent = "per teacher (above)";
        hoursTd.appendChild(hint);
      }
      tr.appendChild(hoursTd);

      // Department
      tr.appendChild(departmentCell(s.department || "", (v) => (s.department = v)));

      // Subject Type
      tr.appendChild(selectCell(s.subject_type || "DSC", SUBJECT_TYPES, (v) => {
        s.subject_type = v;
      }).td);

      // Has Lab
      const labTd = document.createElement("td");
      const labCb = document.createElement("input");
      labCb.type = "checkbox"; labCb.checked = !!s.has_lab;
      labCb.addEventListener("change", () => (s.has_lab = labCb.checked));
      labTd.appendChild(labCb);
      tr.appendChild(labTd);

      // Notes
      tr.appendChild(inputCell(s.notes, (v) => (s.notes = v)).td);

      // Delete
      tr.appendChild(deleteCell(() => {
        userData.subjects.splice(idx, 1);
        renderSubjects(); renderDashboard(); refreshGenerateGate();
      }));

      tbody.appendChild(tr);
    });
  }
  document.getElementById("add-subject").addEventListener("click", () => {
    const newSubj = {
      course: "", semester: null, subject: "", section: "",
      department: (getAllDepartments()[0] || "Computer Science"),
      subject_type: "DSC", has_lab: true, notes: "",
      teaching_mode: "normal",
      teachers_list: [], split_entries: [],
      lectures: 3, tutorials: 0, practicals: 2,
      teacher: "", hours: "3,0,2",
    };
    syncLegacy(newSubj);
    userData.subjects.push(newSubj);
    renderSubjects(); renderDashboard(); refreshGenerateGate();
  });

  // ============================================================
  // Renders — Preferences (own section)
  // ============================================================
  function renderPreferences() {
    const tbody = document.querySelector("#preferences-table tbody");
    tbody.innerHTML = "";

    // Auto-cleanup: drop prefs referencing teachers no longer in the list.
    const valid = new Set(getTeacherFullNames());
    if ((userData.preferences || []).some((p) => p.full_name && !valid.has(p.full_name))) {
      userData.preferences = (userData.preferences || []).filter(
        (p) => !p.full_name || valid.has(p.full_name)
      );
    }

    (userData.preferences || []).forEach((p, idx) => {
      const tr = document.createElement("tr");

      // Teacher dropdown
      const tTd = document.createElement("td");
      tTd.appendChild(teacherSelectInline(p.full_name || "", (v) => (p.full_name = v)));
      tr.appendChild(tTd);

      // Off Days checkboxes
      const dTd = document.createElement("td");
      // Stored values may be full names ("Monday") or short ("Mon") — normalize to short.
      const normShort = (Array.isArray(p.off_days) ? p.off_days : (p.off_days ? String(p.off_days).split(",") : []))
        .map((d) => String(d).trim().slice(0, 3))
        .map((d) => d.charAt(0).toUpperCase() + d.slice(1).toLowerCase())
        .filter((d) => DAY_OPTIONS.includes(d));
      dTd.appendChild(daysRowInline(normShort, (next) => (p.off_days = next)));
      tr.appendChild(dTd);

      // Preferred / Avoid time selects (None maps to "")
      const norm = (v) => (v && TIME_LABELS.includes(v) ? v : (v ? v : "None"));
      const prefSel = selectCell(norm(p.preferred_time), TIME_LABELS, (v) =>
        (p.preferred_time = v === "None" ? "" : v));
      tr.appendChild(prefSel.td);
      const avoidSel = selectCell(norm(p.avoid_time), TIME_LABELS, (v) =>
        (p.avoid_time = v === "None" ? "" : v));
      tr.appendChild(avoidSel.td);

      // Delete
      tr.appendChild(deleteCell(() => {
        userData.preferences.splice(idx, 1);
        renderPreferences();
      }));

      tbody.appendChild(tr);
    });
  }
  document.getElementById("add-preference").addEventListener("click", () => {
    userData.preferences.push({
      full_name: "", off_days: [], preferred_time: "", avoid_time: "",
    });
    renderPreferences();
  });

  // ============================================================
  // Save buttons
  // ============================================================
  async function persist(label) {
    try {
      // Always sync legacy fields on subjects right before sending.
      (userData.subjects || []).forEach(syncLegacy);
      await api.saveConfig(userData);
      flashStatus(`✅ ${label} saved`, true);
      // Any save invalidates the previously-built Excel: the user must
      // re-build before running the solver against fresh data.
      if (excelBuilt) {
        excelBuilt = false;
        const bs = document.getElementById("build-status");
        if (bs) {
          bs.textContent = "config changed — rebuild required";
          bs.className = "stage-status muted";
        }
      }
      updateTopbar();
      renderDashboard();
      refreshGenerateGate();
    } catch (e) {
      flashStatus(`❌ ${e.message}`, false);
    }
  }
  document.getElementById("save-settings").addEventListener("click", () => {
    readSettingsForm(); persist("Settings");
  });
  document.getElementById("save-teachers").addEventListener("click",     () => persist("Teachers"));
  document.getElementById("save-subjects").addEventListener("click",     () => persist("Subjects"));
  document.getElementById("save-preferences").addEventListener("click",  () => persist("Preferences"));

  // ============================================================
  // Pre-flight validation + button gating
  // ============================================================
  function validateGenerate() {
    const teachers = userData.teachers || [];
    const subjects = userData.subjects || [];
    const checks = [];

    checks.push({
      ok: teachers.length > 0,
      label: "At least one teacher",
      detail: teachers.length === 0 ? "add teachers on the Teachers tab" : `${teachers.length} on file`,
    });

    checks.push({
      ok: subjects.length > 0,
      label: "At least one subject",
      detail: subjects.length === 0 ? "add subjects on the Subjects tab" : `${subjects.length} on file`,
    });

    const validTeachers = new Set(getTeacherFullNames());
    function teachersOf(s) {
      ensureSubjectShape(s);
      if (s.teaching_mode === "split") {
        return (s.split_entries || []).map((e) => (e.teacher || "").trim());
      }
      return (s.teachers_list || []).map((t) => (t || "").trim());
    }
    const noTeacher = subjects.filter((s) => {
      const ts = teachersOf(s).filter(Boolean);
      // Fail if no teacher selected, OR any selected teacher doesn't exist
      // in the Teachers list (orphan reference left after a delete).
      return ts.length === 0 || ts.some((t) => !validTeachers.has(t));
    });
    checks.push({
      ok: subjects.length > 0 && noTeacher.length === 0,
      label: "Every subject has a valid teacher",
      detail: noTeacher.length === 0
        ? "all subjects assigned"
        : `${noTeacher.length} unassigned/orphaned: ${noTeacher.slice(0, 3).map((s) => s.subject || "(unnamed)").join(", ")}${noTeacher.length > 3 ? "…" : ""}`,
    });

    const zeroHours = subjects.filter((s) => {
      ensureSubjectShape(s);
      if (s.teaching_mode === "split") {
        const total = (s.split_entries || []).reduce(
          (sum, e) => sum + (+e.lectures || 0) + (+e.tutorials || 0) + (+e.practicals || 0),
          0
        );
        return total === 0;
      }
      return (+s.lectures || 0) + (+s.tutorials || 0) + (+s.practicals || 0) === 0;
    });
    checks.push({
      ok: subjects.length > 0 && zeroHours.length === 0,
      label: "Every subject has at least one hour",
      detail: zeroHours.length === 0
        ? "no zero-hour subjects"
        : `${zeroHours.length} with all-zero hours: ${zeroHours.slice(0, 3).map((s) => s.subject || "(unnamed)").join(", ")}${zeroHours.length > 3 ? "…" : ""}`,
    });

    return checks;
  }

  // Generate-stage state lives at the top of the IIFE; excelBuilt is
  // invalidated on any persist() so the solver never runs against stale Excel.
  function refreshGenerateGate() {
    const checks   = validateGenerate();
    const list     = document.getElementById("checklist-items");
    const buildBtn = document.getElementById("build-excel-btn");
    const runBtn   = document.getElementById("run-solver-btn");
    const dashBtn  = document.getElementById("dash-go");

    if (list) {
      list.innerHTML = "";
      for (const c of checks) {
        const li = document.createElement("li");
        li.className = c.ok ? "ok" : "bad";
        const mark = document.createElement("span");
        mark.className = "cl-mark"; mark.textContent = c.ok ? "✅" : "❌";
        const lbl = document.createElement("span"); lbl.textContent = c.label;
        const det = document.createElement("span");
        det.className = "cl-detail"; det.textContent = c.detail ? `— ${c.detail}` : "";
        li.appendChild(mark); li.appendChild(lbl); li.appendChild(det);
        list.appendChild(li);
      }
    }

    const failing = checks.filter((c) => !c.ok);
    const blocked = failing.length > 0;
    const failTooltip = "Cannot generate yet:\n• " + failing.map((c) => c.label).join("\n• ");
    const okTooltip   = "All pre-flight checks pass.";

    if (buildBtn) {
      const disable = blocked || solving;
      buildBtn.disabled = disable;
      buildBtn.title = blocked ? failTooltip
        : (solving ? "Solver is running…"
                   : "Build inputs/generated_input.xlsx from your saved data.");
    }
    if (runBtn) {
      const disable = blocked || solving || !excelBuilt;
      runBtn.disabled = disable;
      runBtn.title = blocked ? failTooltip
        : (solving ? "Solver is already running…"
                   : (!excelBuilt ? "Build the Excel input first." : okTooltip));
    }
    if (dashBtn) {
      dashBtn.disabled = blocked;
      dashBtn.title = blocked ? failTooltip
                              : "Go to the Generate page to run the solver.";
    }
  }

  // ============================================================
  // Generate page — Build Excel + Run Solver, with live step progress
  // ============================================================
  function classifyLine(line) {
    if (line.startsWith("❌"))                       return "err";
    if (line.startsWith("⚠️") || /WARN/i.test(line)) return "warn";
    if (line.startsWith("✅"))                       return "ok";
    if (line.startsWith("📋"))                       return "step";
    return "";
  }
  function appendLog(line) {
    const log = document.getElementById("run-log");
    const span = document.createElement("span");
    const cls = classifyLine(line);
    if (cls) span.className = cls;
    span.textContent = line + "\n";
    log.appendChild(span);
    log.scrollTop = log.scrollHeight;
  }

  // ---- Step progress bar -------------------------------------------------
  // Each pipeline step is identified by a "STEP <N>:" line printed by
  // _run_pipeline in api.py. When STEP N starts, steps 1..N-1 are completed
  // and step N becomes active.
  const STEP_DEFS = [
    { id: "load",        n: 1 },
    { id: "feasibility", n: 2 },
    { id: "build",       n: 3 },
    { id: "solve",       n: 4 },
    { id: "outputs",     n: 5 },
  ];
  const progressState = {};

  function resetProgress() {
    for (const s of STEP_DEFS) progressState[s.id] = "pending";
    repaintProgress();
  }
  function repaintProgress() {
    STEP_DEFS.forEach((s, i) => {
      const el = document.querySelector(`.progress-step[data-step="${s.id}"]`);
      if (!el) return;
      el.classList.remove("active", "done", "fail");
      const icon = el.querySelector(".step-icon");
      const state = progressState[s.id];
      if (state === "active")    { el.classList.add("active"); icon.textContent = String(s.n); }
      else if (state === "done") { el.classList.add("done");   icon.textContent = "✓"; }
      else if (state === "fail") { el.classList.add("fail");   icon.textContent = "✗"; }
      else                       { icon.textContent = String(s.n); }
    });
    // Connector lines: turn green when the step on their LEFT is done.
    const links = document.querySelectorAll(".progress-link");
    links.forEach((link, i) => {
      const prev = STEP_DEFS[i].id;
      link.classList.toggle("done", progressState[prev] === "done");
    });
  }
  function progressOnLine(line) {
    const m = line.match(/STEP (\d)\s*:/);
    if (m) {
      const n = Number(m[1]);
      STEP_DEFS.forEach((s) => {
        if (s.n <  n) progressState[s.id] = "done";
        if (s.n === n) progressState[s.id] = "active";
        if (s.n >  n) progressState[s.id] = "pending";
      });
      repaintProgress();
      return;
    }
    if (/^✅ DONE\b/.test(line)) {
      STEP_DEFS.forEach((s) => (progressState[s.id] = "done"));
      repaintProgress();
    }
  }
  function markActiveStepFailed() {
    const active = STEP_DEFS.find((s) => progressState[s.id] === "active");
    if (active) progressState[active.id] = "fail";
    repaintProgress();
  }

  // ---- Error / success / banner helpers ---------------------------------
  function showError(message) {
    const box = document.getElementById("error-alert");
    document.getElementById("error-text").textContent = message || "(no error message captured)";
    box.classList.remove("hidden");
  }
  function hideError() { document.getElementById("error-alert").classList.add("hidden"); }
  function showSuccess() { document.getElementById("success-banner").classList.remove("hidden"); }
  function hideSuccess() { document.getElementById("success-banner").classList.add("hidden"); }
  function showDownloads() { document.getElementById("run-downloads").classList.remove("hidden"); }
  function hideDownloads() { document.getElementById("run-downloads").classList.add("hidden"); }

  // ---- Build Excel handler ----------------------------------------------
  async function onBuildExcel() {
    const status = document.getElementById("build-status");
    excelBuilt = false;
    refreshGenerateGate();
    status.textContent = "building…"; status.className = "stage-status muted";
    try {
      readSettingsForm();
      (userData.subjects || []).forEach(syncLegacy);
      await api.saveConfig(userData);
      await api.generateExcel();
      excelBuilt = true;
      const tN = (userData.teachers || []).length;
      const sN = (userData.subjects || []).length;
      status.textContent = `✅ Built — ${tN} teachers, ${sN} subjects`;
      status.className = "stage-status ok";
    } catch (e) {
      excelBuilt = false;
      status.textContent = `❌ ${e.message}`;
      status.className = "stage-status err";
    }
    refreshGenerateGate();
  }

  // ---- Run Solver handler -----------------------------------------------
  async function onRunSolver() {
    const log = document.getElementById("run-log");
    const status = document.getElementById("solver-status");

    log.textContent = "";
    hideError(); hideSuccess(); hideDownloads();
    resetProgress();

    solving = true;
    refreshGenerateGate();
    status.textContent = "running…"; status.className = "stage-status muted";

    let sawError = false;
    let errorBuffer = [];

    await api.solve({
      onMessage: (line) => {
        appendLog(line);
        progressOnLine(line);
        if (line.startsWith("❌")) {
          sawError = true;
          // Capture the message for the error alert. Strip the leading icon
          // and "ERROR:" prefix so the alert text reads cleanly.
          const msg = line.replace(/^❌\s*(ERROR:\s*)?/, "");
          errorBuffer.push(msg);
        }
      },
      onDone: () => {
        solving = false;
        if (sawError) {
          markActiveStepFailed();
          status.textContent = "❌ failed"; status.className = "stage-status err";
          showError(errorBuffer.join("\n"));
        } else {
          status.textContent = "✅ done"; status.className = "stage-status ok";
          showSuccess();
          showDownloads();
          refreshDashboard();
          const activeNav = document.querySelector(".nav-item.active");
          if (activeNav && activeNav.dataset.section === "results") loadResults();
        }
        refreshGenerateGate();
      },
      onError: (e) => {
        solving = false;
        markActiveStepFailed();
        status.textContent = "transport error"; status.className = "stage-status err";
        appendLog("❌ " + e.message);
        showError(e.message);
        refreshGenerateGate();
      },
    });
  }

  document.getElementById("build-excel-btn").addEventListener("click", onBuildExcel);
  document.getElementById("run-solver-btn") .addEventListener("click", onRunSolver);
  document.getElementById("view-results-btn").addEventListener("click", () => showSection("results"));

  document.getElementById("dl-zip").href   = api.downloadZipUrl();
  document.getElementById("dl-excel").href = api.downloadExcelUrl();

  // ============================================================
  // Results viewer — tabs (Teacher / Room / Course), picker, grid, popover
  // ============================================================
  const resultsState = { data: null, tab: "teacher", pick: null };

  function escape(s) {
    return String(s).replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));
  }

  async function loadResults() {
    const empty   = document.getElementById("results-empty");
    const content = document.getElementById("results-content");
    try {
      const sol = await api.getResults();
      if (!sol || !sol.master_schedule) {
        empty.classList.remove("hidden");
        content.classList.add("hidden");
        resultsState.data = null;
        return;
      }
      resultsState.data = sol;
      empty.classList.add("hidden");
      content.classList.remove("hidden");
      populatePicker();
      renderTimetable();
      renderPreferenceSummary();
    } catch {
      empty.classList.remove("hidden");
      content.classList.add("hidden");
      resultsState.data = null;
    }
  }

  // Sub-tab switching
  document.querySelectorAll(".result-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      resultsState.tab = btn.dataset.rtab;
      document.querySelectorAll(".result-tab").forEach((b) =>
        b.classList.toggle("active", b === btn));
      populatePicker();
      renderTimetable();
    });
  });

  // "Go to Generate" CTA on the empty state
  const resultsGoBtn = document.getElementById("results-go-generate");
  if (resultsGoBtn) resultsGoBtn.addEventListener("click", () => showSection("generate"));

  // Picker change
  document.getElementById("results-picker").addEventListener("change", (e) => {
    resultsState.pick = e.target.value;
    renderTimetable();
  });

  // ---- Entity extraction (per tab) --------------------------------------
  function entitiesForTab(tab) {
    if (!resultsState.data) return [];
    const set = new Set();
    for (const d in resultsState.data.master_schedule) {
      const day = resultsState.data.master_schedule[d];
      for (const s in day) {
        for (const c of day[s]) {
          if (tab === "teacher") {
            for (const t of (c.teachers_list || [])) if (t) set.add(t);
          } else if (tab === "room") {
            String(c.room || "").split(",")
              .map((r) => r.trim()).filter((r) => r && !r.endsWith("-TBD"))
              .forEach((r) => set.add(r));
          } else if (tab === "course") {
            if (c.course_semester) set.add(c.course_semester);
          }
        }
      }
    }
    return Array.from(set).sort();
  }

  function populatePicker() {
    const sel = document.getElementById("results-picker");
    sel.innerHTML = "";
    const ents = entitiesForTab(resultsState.tab);
    if (ents.length === 0) {
      sel.appendChild(opt("", "(none scheduled)"));
      resultsState.pick = null;
      sel.disabled = true;
    } else {
      sel.disabled = false;
      // Preserve previous selection if still valid
      const previous = resultsState.pick;
      for (const e of ents) sel.appendChild(opt(e, e));
      resultsState.pick = ents.includes(previous) ? previous : ents[0];
      sel.value = resultsState.pick;
    }

    // Update meta line: "Showing 1 of 14 teachers"
    const meta = document.getElementById("results-meta");
    const labelMap = { teacher: "teachers", room: "rooms", course: "courses" };
    meta.textContent = ents.length
      ? `${ents.length} ${labelMap[resultsState.tab]} scheduled`
      : "";
  }

  // ---- Filter a class entry against the current (tab, pick) -------------
  function classMatches(c, tab, pick) {
    if (!pick) return false;
    if (tab === "teacher") return (c.teachers_list || []).includes(pick);
    if (tab === "room")    return String(c.room || "").split(",")
                                  .map((r) => r.trim()).includes(pick);
    if (tab === "course")  return c.course_semester === pick;
    return false;
  }

  // ---- Cell content per tab ---------------------------------------------
  function cellLines(c, tab) {
    const lines = [`<span class="subj">${escape(c.subject || "?")}</span>`];
    let meta = "";
    if (tab === "teacher") {
      // Teacher fixed → show course-semester + room
      meta = [c.course_semester, c.room].filter(Boolean).join(" · ");
    } else if (tab === "room") {
      // Room fixed → show teacher + course-semester
      meta = [c.teacher, c.course_semester].filter(Boolean).join(" · ");
    } else { // course
      // Course fixed → show teacher + room
      meta = [c.teacher, c.room].filter(Boolean).join(" · ");
    }
    if (meta) lines.push(`<span class="meta">${escape(meta)}</span>`);
    return lines.join("");
  }

  // ---- Render the grid for the current (tab, pick) ----------------------
  function renderTimetable() {
    const grid = document.getElementById("results-grid");
    if (!resultsState.data) { grid.innerHTML = ""; return; }
    const days  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const slots = resultsState.data.slots || [];

    const tbl = document.createElement("table");
    tbl.className = "results-grid";
    let html = "<thead><tr><th>Day</th>";
    for (const s of slots) html += `<th>${s}</th>`;
    html += "</tr></thead><tbody>";
    tbl.innerHTML = html;
    const tbody = tbl.querySelector("tbody");

    for (const d of days) {
      const tr = document.createElement("tr");
      const dayTd = document.createElement("td");
      dayTd.className = "day"; dayTd.textContent = d;
      tr.appendChild(dayTd);

      for (const s of slots) {
        const td = document.createElement("td");
        const allClasses = (resultsState.data.master_schedule[d] || {})[s] || [];
        const matching = allClasses.filter((c) =>
          classMatches(c, resultsState.tab, resultsState.pick));
        if (matching.length) {
          const c = matching[0];
          const cls = c.type === "Practical" ? "PRAC" : (c.subject_type || "");
          if (cls) td.classList.add("cell-" + cls);
          td.classList.add("has-class");
          let inner = cellLines(c, resultsState.tab);
          if (matching.length > 1) inner += `<span class="meta">+${matching.length - 1} more</span>`;
          td.innerHTML = inner;
          td.addEventListener("click", (ev) => {
            ev.stopPropagation();
            showCellPopover(td, matching);
          });
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    grid.innerHTML = "";
    grid.appendChild(tbl);
  }

  // ---- Click popover ----------------------------------------------------
  function closePopover() {
    const old = document.getElementById("cell-popover");
    if (old) old.remove();
    document.removeEventListener("keydown", onPopEsc);
    document.removeEventListener("click", onPopOutside, true);
  }
  function onPopEsc(e) { if (e.key === "Escape") closePopover(); }
  function onPopOutside(e) {
    const pop = document.getElementById("cell-popover");
    if (pop && !pop.contains(e.target)) closePopover();
  }
  function showCellPopover(anchor, classes) {
    closePopover();
    if (!classes.length) return;
    const pop = document.createElement("div");
    pop.className = "cell-popover";
    pop.id = "cell-popover";

    const closeBtn = document.createElement("button");
    closeBtn.className = "pop-close"; closeBtn.type = "button"; closeBtn.textContent = "×";
    closeBtn.addEventListener("click", closePopover);
    pop.appendChild(closeBtn);

    classes.forEach((c, i) => {
      if (i > 0) pop.appendChild(document.createElement("hr"));
      const block = document.createElement("div");
      block.innerHTML = `
        <h4>${escape(c.subject || "?")}</h4>
        <div class="row"><span class="label">Teacher:</span> ${escape(c.teacher || "—")}</div>
        <div class="row"><span class="label">Room:</span> ${escape(c.room || "—")}</div>
        <div class="row"><span class="label">Section:</span> ${escape(c.section || "—")}</div>
        <div class="row"><span class="label">Type:</span> ${escape(c.type || "?")}${c.subject_type ? ` <span class="muted">(${escape(c.subject_type)})</span>` : ""}</div>
        <div class="row"><span class="label">Course:</span> ${escape(c.course_semester || "—")}</div>
      `;
      pop.appendChild(block);
    });

    document.body.appendChild(pop);
    // Position: prefer below the cell; flip up if it would overflow the viewport.
    const r  = anchor.getBoundingClientRect();
    const pr = pop.getBoundingClientRect();
    let top  = r.bottom + 6;
    let left = Math.max(8, r.left + r.width / 2 - pr.width / 2);
    if (top + pr.height > window.innerHeight - 8) top = Math.max(8, r.top - pr.height - 6);
    if (left + pr.width > window.innerWidth - 8) left = window.innerWidth - pr.width - 8;
    pop.style.top  = top  + "px";
    pop.style.left = left + "px";

    // Defer outside-click + ESC binding to the next tick so this very click
    // doesn't immediately close the popover.
    setTimeout(() => {
      document.addEventListener("click", onPopOutside, true);
      document.addEventListener("keydown", onPopEsc);
    }, 0);
  }

  // ---- Preference summary table ----------------------------------------
  function satBadgeHTML(value) {
    if (value === null || value === undefined) {
      return `<span class="sat-badge none">—</span>`;
    }
    const v = Number(value);
    let cls = "low";
    if (v >= 80) cls = "high";
    else if (v >= 50) cls = "mid";
    return `<span class="sat-badge ${cls}">${v.toFixed(0)}%</span>`;
  }
  function renderPreferenceSummary() {
    const tbody = document.querySelector("#results-prefs-table tbody");
    tbody.innerHTML = "";
    const report = (resultsState.data && resultsState.data.teacher_report) || [];
    if (report.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="6" class="muted" style="text-align:center;padding:14px;">
        No teacher data — re-run the solver after adding teachers.</td>`;
      tbody.appendChild(tr);
      return;
    }
    for (const row of report) {
      const tr = document.createElement("tr");
      const violationText = row.violations || (row.has_preferences ? "—" : "(no preferences set)");
      tr.innerHTML = `
        <td>${escape(row.teacher)}${row.initials ? ` <span class="muted">(${escape(row.initials)})</span>` : ""}</td>
        <td>${escape(row.rank)}</td>
        <td>${row.scheduled_hours}h</td>
        <td>${row.cap}h</td>
        <td>${satBadgeHTML(row.satisfaction)}</td>
        <td><span class="muted">${escape(violationText)}</span></td>
      `;
      tbody.appendChild(tr);
    }
  }

  // Wire the Results-tab download buttons through api.js so a remote BASE_URL
  // change still works.
  document.getElementById("dl-zip-results").href   = api.downloadZipUrl();
  document.getElementById("dl-excel-results").href = api.downloadExcelUrl();

  // ============================================================
  // Top-bar college chip + dashboard cards
  // ============================================================
  function updateTopbar() {
    const chip = document.getElementById("college-name");
    if (!chip) return;
    const name = (userData.college && userData.college.name) || "Unconfigured college";
    chip.textContent = name;
    chip.title = name;
  }
  function formatLastGenerated(iso) {
    if (!iso) return { value: "Never", sub: "no run on record" };
    const d = new Date(iso);
    if (isNaN(d.getTime())) return { value: iso, sub: "" };
    const ago = humanizeAgo(d);
    const value = d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
    const time  = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return { value, sub: `${time} (${ago})` };
  }
  function humanizeAgo(date) {
    const sec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (sec < 60)        return "just now";
    if (sec < 3600)      return `${Math.floor(sec / 60)} min ago`;
    if (sec < 86400)     return `${Math.floor(sec / 3600)} h ago`;
    if (sec < 7 * 86400) return `${Math.floor(sec / 86400)} d ago`;
    return date.toLocaleDateString();
  }
  function renderDashboard() {
    const tCount = (userData.teachers || []).length;
    const sCount = (userData.subjects || []).length;
    document.getElementById("card-teachers").textContent = tCount;
    document.getElementById("card-teachers-sub").textContent =
      tCount === 0 ? "no teachers yet" : (tCount === 1 ? "1 teacher" : `${tCount} teachers`);
    document.getElementById("card-subjects").textContent = sCount;
    document.getElementById("card-subjects-sub").textContent =
      sCount === 0 ? "no subjects yet" : (sCount === 1 ? "1 subject" : `${sCount} entries`);
    const last = formatLastGenerated(userData.last_generated_at);
    document.getElementById("card-last").textContent = last.value;
    document.getElementById("card-last-sub").textContent = last.sub || "";
  }
  async function refreshDashboard() {
    try {
      const fresh = await api.getConfig();
      userData.last_generated_at = fresh.last_generated_at;
    } catch (_) { /* keep stale value */ }
    renderDashboard();
  }

  // ============================================================
  // Init
  // ============================================================
  (async function init() {
    try {
      userData = await api.getConfig();
    } catch (e) {
      flashStatus("❌ couldn't load config", false);
      console.error(e);
      return;
    }
    // Backfill richer subject shape from any legacy data.
    (userData.subjects || []).forEach(ensureSubjectShape);

    fillSettingsForm(userData);
    renderTeachers();
    renderSubjects();
    renderPreferences();
    updateTopbar();
    renderDashboard();
    refreshGenerateGate();
  })();
})();
