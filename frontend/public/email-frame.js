(() => {
  "use strict";

  const root = document.getElementById("email-content");
  if (!root) return;

  const sendHeight = () => {
    const height = Math.max(
      document.body?.scrollHeight ?? 0,
      document.documentElement?.scrollHeight ?? 0,
    );
    parent.postMessage({ type: "mailcue:email-height", height }, "*");
  };

  const observeImages = () => {
    document.querySelectorAll("img").forEach((image) => {
      image.addEventListener("load", sendHeight, { once: true });
      image.addEventListener("error", sendHeight, { once: true });
    });
  };

  window.addEventListener("message", (event) => {
    if (event.source !== parent || event.data?.type !== "mailcue:render-email") {
      return;
    }

    const foreground = event.data.isDark ? "#e5e7eb" : "#1f2937";
    const background = event.data.isDark ? "#1f2937" : "#ffffff";
    document.documentElement.style.setProperty("--email-fg", foreground);
    document.documentElement.style.setProperty("--email-bg", background);
    root.innerHTML = typeof event.data.html === "string" ? event.data.html : "";
    observeImages();
    sendHeight();
  });

  new ResizeObserver(sendHeight).observe(document.documentElement);
})();
