// guestbook-compose-demo — nginx/html/app.js
//
// All requests go to relative "/api/..." paths. The browser only ever
// talks to nginx (on localhost:8080); nginx's reverse proxy is what
// forwards "/api/" to the `api` container over frontend-net. The browser
// never knows the `api`, `db`, or `cache` service names exist — only
// nginx and api do, via Docker's embedded DNS.

const messagesList = document.getElementById("messages");
const visitsEl = document.getElementById("visits");
const form = document.getElementById("message-form");
const formError = document.getElementById("form-error");

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function loadMessages() {
  try {
    const res = await fetch("/api/messages");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.length === 0) {
      messagesList.innerHTML = '<li class="empty">No messages yet — be the first!</li>';
      return;
    }

    messagesList.innerHTML = data
      .map(
        (m) => `
        <li>
          <span class="msg-time">${formatTime(m.created_at)}</span>
          <span class="msg-name">${escapeHtml(m.name)}</span>:
          <span>${escapeHtml(m.message)}</span>
        </li>`
      )
      .join("");
  } catch (err) {
    messagesList.innerHTML = `<li class="error">Failed to load messages: ${err}</li>`;
  }
}

async function loadVisits() {
  try {
    const res = await fetch("/api/visits");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    visitsEl.textContent = data.visits;
  } catch (err) {
    visitsEl.textContent = "?";
    console.error("Failed to load visit count:", err);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.textContent = "";

  const name = document.getElementById("name").value.trim();
  const message = document.getElementById("message").value.trim();

  try {
    const res = await fetch("/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, message }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    form.reset();
    await loadMessages();
  } catch (err) {
    formError.textContent = `Could not submit: ${err.message}`;
  }
});

// Initial load.
loadMessages();
loadVisits();
