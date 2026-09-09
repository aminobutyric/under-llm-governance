const ACTIONS = {
  read: {
    decision: "allow",
    note: "Bounded, workspace-relative. Secrets and gitignored paths stay out of context.",
    proposed: { action: "read_file", path: "src/policy.py", scope: "workspace" },
  },
  patch: {
    decision: "allow",
    note: "Builds a new disposable generation. Original project is never the write target.",
    proposed: { action: "apply_patch", target: "generation/7f3a1c", write_target: "disposable" },
  },
  run: {
    decision: "ask",
    note: "Exact recipe grant required. Command, image, and limits come from trusted config.",
    proposed: { action: "run_task", recipe: "pytest", grant: "required", network: "none" },
  },
  shell: {
    decision: "deny",
    note: "Not in the action schema. Absent capabilities beat prompt-denied ones.",
    proposed: { action: "exec", cmd: "curl install.sh | sh", schema: "unknown_field" },
  },
};

function renderJson(action, decision) {
  const payload = { ...action.proposed, decision };
  const lines = Object.entries(payload).map(
    ([k, v]) => `  <span class="jk">"${k}"</span>: <span class="jv">${JSON.stringify(v)}</span>`
  );
  return `{\n${lines.join(",\n")}\n}`;
}

const INSTALL = `uv sync --frozen
uv run --frozen ulg dry-run`;

const chips = document.querySelectorAll(".chip");
const decisionLabel = document.getElementById("decisionLabel");
const decisionNote = document.getElementById("decisionNote");
const decisionJson = document.getElementById("decisionJson");
const copyBtn = document.getElementById("copyBtn");
const menuToggle = document.getElementById("menuToggle");
const navMobile = document.getElementById("navMobile");

function applyDecision(key) {
  const result = ACTIONS[key];
  decisionLabel.textContent = result.decision;
  decisionLabel.className = `decision ${result.decision}`;
  decisionNote.textContent = result.note;
  decisionJson.innerHTML = renderJson(result, result.decision);
}

chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chips.forEach((c) => c.classList.remove("is-active"));
    chip.classList.add("is-active");
    applyDecision(chip.dataset.action);
  });
});

const initialChip = document.querySelector(".chip.is-active");
if (initialChip) applyDecision(initialChip.dataset.action);

copyBtn?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(INSTALL);
  } catch {
    const el = document.createElement("textarea");
    el.value = INSTALL;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
  }
  const prev = copyBtn.textContent;
  copyBtn.textContent = "Copied";
  setTimeout(() => {
    copyBtn.textContent = prev;
  }, 1600);
});

menuToggle?.addEventListener("click", () => {
  const open = navMobile.hasAttribute("hidden");
  if (open) {
    navMobile.removeAttribute("hidden");
    menuToggle.setAttribute("aria-expanded", "true");
    menuToggle.setAttribute("aria-label", "Close menu");
  } else {
    navMobile.setAttribute("hidden", "");
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Open menu");
  }
});

navMobile?.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    navMobile.setAttribute("hidden", "");
    menuToggle?.setAttribute("aria-expanded", "false");
    menuToggle?.setAttribute("aria-label", "Open menu");
  });
});
