// Shared giscus comments include for all books on this site.
//
// PLACEHOLDERS: data-repo-id and data-category-id below must be filled in
// from https://giscus.app after enabling Discussions on richardkiss/plans
// and installing the giscus GitHub App (see README.md at the repo root).
// Until then, this script detects the placeholders and does nothing, so
// comments never block a deploy.
(function () {
  var config = {
    repo: "richardkiss/plans",
    repoId: "PLACEHOLDER_REPO_ID",
    category: "Announcements",
    categoryId: "PLACEHOLDER_CATEGORY_ID",
  };

  if (config.repoId.indexOf("PLACEHOLDER") === 0 || config.categoryId.indexOf("PLACEHOLDER") === 0) {
    return; // not configured yet — no-op
  }

  function mount() {
    var content = document.querySelector("main") || document.querySelector(".content");
    if (!content) return;

    var container = document.createElement("div");
    container.id = "giscus-comments";
    container.style.marginTop = "3em";
    content.appendChild(container);

    var script = document.createElement("script");
    script.src = "https://giscus.app/client.js";
    script.setAttribute("data-repo", config.repo);
    script.setAttribute("data-repo-id", config.repoId);
    script.setAttribute("data-category", config.category);
    script.setAttribute("data-category-id", config.categoryId);
    script.setAttribute("data-mapping", "pathname");
    script.setAttribute("data-strict", "0");
    script.setAttribute("data-reactions-enabled", "1");
    script.setAttribute("data-emit-metadata", "0");
    script.setAttribute("data-input-position", "bottom");
    script.setAttribute("data-theme", "preferred_color_scheme");
    script.setAttribute("data-lang", "en");
    script.crossOrigin = "anonymous";
    script.async = true;
    container.appendChild(script);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
