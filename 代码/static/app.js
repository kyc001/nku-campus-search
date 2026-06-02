const input = document.querySelector("#query-input");
const suggestBox = document.querySelector("#suggest-box");
const suggestCache = new Map();
let activeSuggestController = null;
let activeSuggestIndex = -1;

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

if (input && suggestBox) {
  const renderSuggest = (items) => {
    suggestBox.innerHTML = "";
    activeSuggestIndex = -1;
    if (!items.length) {
      suggestBox.hidden = true;
      return;
    }
    items.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.textContent = item;
      button.addEventListener("click", () => {
        chooseSuggest(item);
      });
      suggestBox.appendChild(button);
    });
    suggestBox.hidden = false;
  };

  const chooseSuggest = (value) => {
    input.value = value;
    suggestBox.hidden = true;
    input.form.submit();
  };

  const setActiveSuggest = (index) => {
    const buttons = [...suggestBox.querySelectorAll("button")];
    if (!buttons.length) return;
    activeSuggestIndex = (index + buttons.length) % buttons.length;
    buttons.forEach((button, idx) => {
      button.classList.toggle("is-active", idx === activeSuggestIndex);
    });
  };

  const shouldSuggest = (q) => q.length >= 2 || /[\u4e00-\u9fff]/.test(q);

  const updateSuggest = debounce(async () => {
    const q = input.value.trim();
    if (!shouldSuggest(q)) {
      renderSuggest([]);
      return;
    }
    if (suggestCache.has(q)) {
      renderSuggest(suggestCache.get(q));
      return;
    }
    activeSuggestController?.abort();
    activeSuggestController = new AbortController();
    try {
      const resp = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`, {
        signal: activeSuggestController.signal,
      });
      const items = await resp.json();
      suggestCache.set(q, items);
      renderSuggest(items);
    } catch (error) {
      if (error.name !== "AbortError") {
        renderSuggest([]);
      }
    }
  }, 150);

  input.addEventListener("input", updateSuggest);
  input.addEventListener("focus", () => {
    if (input.value.trim()) updateSuggest();
  });
  input.addEventListener("keydown", (event) => {
    if (suggestBox.hidden) return;
    const buttons = [...suggestBox.querySelectorAll("button")];
    if (!buttons.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveSuggest(activeSuggestIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSuggest(activeSuggestIndex - 1);
    } else if (event.key === "Enter" && activeSuggestIndex >= 0) {
      event.preventDefault();
      chooseSuggest(buttons[activeSuggestIndex].textContent);
    } else if (event.key === "Escape") {
      suggestBox.hidden = true;
    }
  });
  document.addEventListener("click", (event) => {
    if (!suggestBox.contains(event.target) && event.target !== input) {
      suggestBox.hidden = true;
    }
  });
}

for (const link of document.querySelectorAll("[data-click-url]")) {
  link.addEventListener("click", () => {
    const payload = {
      url: link.dataset.clickUrl,
      query: link.dataset.query || "",
    };
    navigator.sendBeacon?.("/api/click", new Blob([JSON.stringify(payload)], { type: "application/json" })) ||
      fetch("/api/click", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        keepalive: true,
      });
  });
}
