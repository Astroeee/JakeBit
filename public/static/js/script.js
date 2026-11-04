// Live preview on the Settings page: the look changes instantly when you pick an option.
// Nothing is saved until you press "Save settings".
document.addEventListener("change", (event) => {
  const input = event.target;
  const keys = ["theme", "bg", "card", "fur"];
  if (input.type === "radio" && keys.includes(input.name)) {
    document.body.dataset[input.name] = input.value;
    if (input.name === "theme") {
      document.body.dataset.mode = input.dataset.mode;  // "light" or "dark"
    }
  }
});

function syncWeeklyTarget(form) {
  const frequency = form.querySelector('select[name="frequency"]');
  if (!frequency) return;
  const weekly = form.querySelector("[data-weekly-target]");
  const days = form.querySelector("[data-custom-days]");
  if (weekly) weekly.hidden = frequency.value !== "weekly";
  if (days) days.hidden = frequency.value !== "custom";
}

// CSRF protection: the server hands every page a secret token (in a <meta> tag).
// We add it to each POST form, and the server rejects any form without it.
document.addEventListener("DOMContentLoaded", () => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  document.querySelectorAll('form[method="post"]').forEach((form) => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = meta.content;
    form.appendChild(input);
  });
});


// Profile editor: move a widget row up or down
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-move]");
  if (!button) return;
  const row = button.closest(".widget-row");
  const other = button.dataset.move === "up" ? row.previousElementSibling : row.nextElementSibling;
  if (!other) return;
  if (button.dataset.move === "up") other.before(row); else other.after(row);
});

// Greeting follows the visitor's own clock, and the top search box filters what is on the page
document.addEventListener("DOMContentLoaded", () => {
  const greeting = document.querySelector("[data-greeting]");
  if (greeting) {
    const hour = new Date().getHours();
    const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
    greeting.textContent = `Good ${part}, ${greeting.dataset.name}`;
  }
  const search = document.getElementById("site-search");
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      document.querySelectorAll("[data-search]").forEach((el) => { el.hidden = q !== "" && !el.dataset.search.includes(q); });
    });
  }
});

// Emoji logo picker: show the chosen emoji on the button and close the list
document.addEventListener("change", (event) => {
  const radio = event.target.closest(".emoji-picker input[type=radio]");
  if (!radio) return;
  const picker = radio.closest(".emoji-picker");
  picker.querySelector("[data-emoji-preview]").textContent = radio.value || "✨";
  picker.open = false;
});
