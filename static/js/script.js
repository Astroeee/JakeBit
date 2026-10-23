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

// Show the "times per week" box only when the frequency is Weekly
function syncWeeklyTarget(form) {
  const frequency = form.querySelector('select[name="frequency"]');
  const box = form.querySelector("[data-weekly-target]");
  if (frequency && box) box.hidden = frequency.value !== "weekly";
}
document.addEventListener("change", (event) => {
  if (event.target.name === "frequency" && event.target.form) syncWeeklyTarget(event.target.form);
});
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form").forEach(syncWeeklyTarget);
});

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