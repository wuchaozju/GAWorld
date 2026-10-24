
var gwURL = globalThis.GAWorldURL ? globalThis.GAWorldURL.url : function (value) { return value; };
var gwHTML = globalThis.GAWorldURL ? globalThis.GAWorldURL.html : function (value) { return value; };
/* GAWorld: an illustrated field guide, entirely local and independent of simulation. */
(function () {
  "use strict";
  var legacyView = window.location.hash.slice(1);
  var legacyViews = [
    "dashboard",
    "simviz",
    "city",
    "analytics",
    "studio",
    "organizations",
    "population",
    "play",
    "survey",
    "collaboration",
    "games",
    "external",
    "admin",
    "settings",
    "docs",
    "worlds",
  ];
  if (legacyViews.includes(legacyView)) {
    window.location.replace(
      gwURL("/console" + window.location.search + window.location.hash),
    );
    return;
  }
  var entries = Array.from(document.querySelectorAll("[data-en]")).map(
    function (el) {
      return { el: el, zh: el.innerHTML, en: el.dataset.en };
    },
  );
  var language = "zh",
    scene = 0,
    persona = "family",
    network = "family";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var motionOverride = null;
  try {
    language = localStorage.getItem("gaworld-language") === "en" ? "en" : "zh";
    var savedMotion = localStorage.getItem("gaworld.landing.motion");
    if (savedMotion === "paused" || savedMotion === "running")
      motionOverride = savedMotion;
  } catch (_) {}
  var text = {
    zh: {
      scenes: [
        [
          "01 / CITY",
          "城市是舞台，居民是故事。",
          "/console#city",
          "进入城市功能",
        ],
        [
          "02 / CONNECTIONS",
          "生活相遇，关系由此生长。",
          "/console#survey",
          "进入群体采访",
        ],
        [
          "03 / POSSIBILITIES",
          "同一个起点，展开两种可能。",
          "/console#worlds",
          "进入平行世界",
        ],
      ],
      persona: {
        family: "当家庭需要照顾，今天的计划也会重新排序。",
        work: "过去的工作经历，会进入下一次职业选择的考量。",
        change: "面对突发变化，记忆与性格影响如何理解眼前的处境。",
      },
      network: {
        family: "共同生活，让一次选择牵动不止一个人。",
        work: "工作中的协作，让信息与行动沿同事关系展开。",
        community: "弱联系连接不同生活圈，让消息走出熟人之间。",
      },
      pause: "暂停动画",
      play: "播放动画",
      title: "GAWorld · 从一个人，到整个世界",
    },
    en: {
      scenes: [
        [
          "01 / CITY",
          "A stage for individual lives.",
          "/console#city",
          "Open cities",
        ],
        [
          "02 / CONNECTIONS",
          "Lives intersect. Connections emerge.",
          "/console#survey",
          "Open group interviews",
        ],
        [
          "03 / POSSIBILITIES",
          "One baseline. Different possibilities.",
          "/console#worlds",
          "Open parallel worlds",
        ],
      ],
      persona: {
        family: "When family needs care, today's plans may have to change.",
        work: "Past experiences at work inform the next career decision.",
        change:
          "Memory and personality shape how an unexpected change is understood.",
      },
      network: {
        family: "Shared lives mean a choice can affect more than one person.",
        work: "Collaboration carries information and action through workplace ties.",
        community:
          "Weaker ties connect different circles and let news travel further.",
      },
      pause: "Pause animation",
      play: "Play animation",
      title: "GAWorld · From a person to a whole world",
    },
  };
  var tabs = Array.from(document.querySelectorAll("[data-scene]"));
  var canvas = document.getElementById("world-canvas");
  var viewport = document.getElementById("world-panel");
  var context = null;
  try {
    context = canvas.getContext("2d");
  } catch (_) {}
  var frame = null,
    previousTime = null,
    elapsed = 0,
    heroVisible = true;
  var width = 800,
    height = 530,
    pixelRatio = 1;
  function running() {
    return motionOverride ? motionOverride === "running" : !reduce.matches;
  }
  function updateDynamicText() {
    var copy = text[language],
      item = copy.scenes[scene];
    document.getElementById("scene-tag").textContent = item[0];
    document.getElementById("scene-title").textContent = item[1];
    var link = document.getElementById("scene-link");
    link.href = gwURL(item[2]);
    link.setAttribute("aria-label", item[3]);
    viewport.setAttribute("aria-labelledby", "tab-" + scene);
    tabs.forEach(function (tab, i) {
      tab.setAttribute("aria-selected", String(i === scene));
      tab.tabIndex = i === scene ? 0 : -1;
    });
    document.getElementById("persona-insight").textContent =
      copy.persona[persona];
    document.getElementById("network-caption").textContent =
      copy.network[network];
    document.getElementById("motion-label").textContent = running()
      ? copy.pause
      : copy.play;
  }
  function setLanguage() {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    entries.forEach(function (entry) {
      entry.el.innerHTML = gwHTML(language === "zh" ? entry.zh : entry.en);
    });
    var button = document.getElementById("language");
    button.textContent = language === "zh" ? "EN" : "中文";
    button.setAttribute(
      "aria-label",
      language === "zh" ? "Switch to English" : "切换为中文",
    );
    [
      ["#main-nav", "主导航", "Main navigation"],
      [".scene-nav", "示意视角", "Illustration views"],
      [".persona-switch", "人物决策情境", "Decision contexts"],
      [".network-switch", "关系类型", "Types of connection"],
    ].forEach(function (labels) {
      document
        .querySelector(labels[0])
        .setAttribute("aria-label", labels[language === "zh" ? 1 : 2]);
    });
    document.title = text[language].title;
    updateDynamicText();
  }
  document.getElementById("language").addEventListener("click", function () {
    language = language === "zh" ? "en" : "zh";
    try {
      localStorage.setItem("gaworld-language", language);
    } catch (_) {}
    setLanguage();
  });
  function chooseScene(index) {
    scene = index;
    updateDynamicText();
    draw();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      chooseScene(index);
    });
    tab.addEventListener("keydown", function (event) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      chooseScene(
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? 2
            : (scene + (event.key === "ArrowRight" ? 1 : 2)) % 3,
      );
      tabs[scene].focus();
    });
  });
  document.querySelectorAll("[data-persona]").forEach(function (button) {
    button.addEventListener("click", function () {
      persona = button.dataset.persona;
      document.querySelectorAll("[data-persona]").forEach(function (other) {
        other.setAttribute("aria-pressed", String(other === button));
      });
      updateDynamicText();
    });
  });
  document.querySelectorAll("[data-network]").forEach(function (button) {
    button.addEventListener("click", function () {
      network = button.dataset.network;
      document.getElementById("social-network").dataset.layer = network;
      document.querySelectorAll("[data-network]").forEach(function (other) {
        other.setAttribute("aria-pressed", String(other === button));
      });
      updateDynamicText();
    });
  });
  var slider = document.getElementById("intervention-level");
  function updateBranch() {
    var value = Number(slider.value),
      y = 130 + value * 2.1;
    document.getElementById("intervention-value").textContent = String(value);
    document
      .getElementById("intervention-curve")
      .setAttribute("d", "M240 210C350 210 410 " + y + " 620 " + y);
    document
      .getElementById("world-b")
      .setAttribute("transform", "translate(620 " + y + ")");
  }
  slider.addEventListener("input", updateBranch);
  document
    .getElementById("persona-insight")
    .setAttribute("aria-live", "polite");
  document
    .getElementById("network-caption")
    .setAttribute("aria-live", "polite");

  // The renderer only runs while it can be seen, and freezes its clock on pause.
  function syncAnimation() {
    var active = running();
    document.documentElement.dataset.motion = active ? "running" : "paused";
    document
      .getElementById("motion-toggle")
      .setAttribute("aria-pressed", String(!active));
    document.querySelector(".motion-icon").textContent = active ? "Ⅱ" : "▷";
    document.getElementById("motion-label").textContent = active
      ? text[language].pause
      : text[language].play;
    document.querySelectorAll("svg").forEach(function (svg) {
      if (!active || document.hidden || svg.closest(".is-outside")) {
        if (svg.pauseAnimations) svg.pauseAnimations();
      } else if (svg.unpauseAnimations) svg.unpauseAnimations();
    });
    if (frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
    previousTime = null;
    if (active && !document.hidden && heroVisible && context)
      frame = requestAnimationFrame(tick);
    draw();
  }
  document
    .getElementById("motion-toggle")
    .addEventListener("click", function () {
      motionOverride = running() ? "paused" : "running";
      try {
        localStorage.setItem("gaworld.landing.motion", motionOverride);
      } catch (_) {}
      syncAnimation();
    });
  reduce.addEventListener("change", syncAnimation);
  document.addEventListener("visibilitychange", function () {
    document.documentElement.classList.toggle("page-hidden", document.hidden);
    syncAnimation();
  });
  function tick(now) {
    frame = null;
    if (!running() || document.hidden || !heroVisible) return;
    if (previousTime !== null)
      elapsed += Math.min((now - previousTime) / 1000, 0.06);
    previousTime = now;
    draw();
    frame = requestAnimationFrame(tick);
  }
  function line(points, stroke, weight, fill) {
    context.beginPath();
    points.forEach(function (point, i) {
      if (i) context.lineTo(point[0], point[1]);
      else context.moveTo(point[0], point[1]);
    });
    if (fill) {
      context.closePath();
      context.fillStyle = fill;
      context.fill();
    }
    if (stroke) {
      context.strokeStyle = stroke;
      context.lineWidth = weight || 1;
      context.stroke();
    }
  }
  function dot(x, y, radius, color) {
    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fillStyle = color;
    context.fill();
  }
  function iso(x, z, elevation) {
    return [(x - z) * 31, (x + z) * 15 - (elevation || 0)];
  }
  var buildings = [];
  for (var bx = -4; bx <= 4; bx++)
    for (var bz = -4; bz <= 4; bz++) {
      if ((bx + bz + 18) % 3 === 0 || bx === 0 || bz === 0) continue;
      buildings.push({
        x: bx,
        z: bz,
        h: 23 + ((bx * bx * 13 + bz * bz * 7 + 17) % 66),
      });
    }
  buildings.sort(function (a, b) {
    return a.x + a.z - b.x - b.z;
  });
  function city(cx, cy, scale, alternative) {
    context.save();
    context.translate(cx, cy);
    context.scale(scale, scale);
    var ground = [iso(-5, -5), iso(5, -5), iso(5, 5), iso(-5, 5)];
    line(ground, "#698c5c80", 1, "#244b37");
    line(
      [iso(5, -5), iso(5, 5), iso(-5, 5), [-310, 12], [0, 162], [310, 12]],
      null,
      0,
      "#0a241b",
    );
    // Roads between blocks leave room for pedestrians and moving signals.
    for (var lane = -4.5; lane <= 4.5; lane++) {
      line([iso(lane, -5), iso(lane, 5)], "#afcb9433", 3);
      line([iso(-5, lane), iso(5, lane)], "#afcb9433", 3);
    }
    buildings.forEach(function (building, index) {
      var x = building.x,
        z = building.z,
        h = building.h;
      var a = iso(x - 0.31, z - 0.31),
        b = iso(x + 0.31, z - 0.31),
        c = iso(x + 0.31, z + 0.31),
        d = iso(x - 0.31, z + 0.31);
      var at = [a[0], a[1] - h],
        bt = [b[0], b[1] - h],
        ct = [c[0], c[1] - h],
        dt = [d[0], d[1] - h];
      var warm = alternative && index % 5 === 0;
      line([d, c, ct, dt], "#97b78040", 0.6, warm ? "#966947" : "#6e9063");
      line([b, c, ct, bt], "#97b78040", 0.6, warm ? "#6a5038" : "#365b43");
      line(
        [at, bt, ct, dt],
        "#d5e7b05c",
        0.7,
        warm ? "#e8a078" : index % 7 === 0 ? "#c4ef8a" : "#aec58e",
      );
      for (var floor = 13; floor < h - 6; floor += 12) {
        line(
          [
            [d[0] + 3, d[1] - floor],
            [c[0] - 3, c[1] - floor - 1.5],
          ],
          "#cfe3b288",
          0.9,
        );
      }
    });
    for (var i = 0; i < 65; i++) {
      var progress = (elapsed * (0.04 + (i % 5) * 0.004) + i * 0.137) % 1;
      var corridor = -4.5 + (i % 10);
      var p =
        i % 2
          ? iso(-4.8 + progress * 9.6, corridor)
          : iso(corridor, 4.8 - progress * 9.6);
      var color = i % 5 === 0 ? "#efa97b" : "#cfec9d";
      dot(p[0], p[1] - 2, 4.5, "#c4ef8a10");
      dot(p[0], p[1] - 2, 1.7 + (i % 3) * 0.2, color);
    }
    context.restore();
  }
  function drawCity() {
    context.save();
    context.strokeStyle = "#b4d78f16";
    context.lineWidth = 1;
    for (var i = 0; i < 4; i++) {
      context.beginPath();
      context.ellipse(405, 280, 240 + i * 40, 110 + i * 18, 0, 0, Math.PI * 2);
      context.stroke();
    }
    context.restore();
    city(400, 288, 0.93, false);
    var angle = elapsed * 0.22;
    dot(405 + 300 * Math.cos(angle), 280 + 138 * Math.sin(angle), 3, "#e8a078");
  }
  function drawNetwork() {
    var nodes = [],
      count = 95,
      yaw = elapsed * 0.09;
    for (var i = 0; i < count; i++) {
      var phi = Math.acos(1 - (2 * (i + 0.5)) / count),
        theta = i * 2.39996 + yaw;
      var x = Math.sin(phi) * Math.cos(theta) * 205,
        z = Math.sin(phi) * Math.sin(theta) * 205,
        y = Math.cos(phi) * 190;
      nodes.push({
        x: 400 + x,
        y: 258 + y + z * 0.16,
        depth: z,
        r: 2 + (z + 205) / 165,
      });
    }
    nodes.forEach(function (node, index) {
      [1, 7, 14].forEach(function (gap) {
        var other = nodes[(index + gap) % count],
          distance = Math.hypot(node.x - other.x, node.y - other.y);
        if (distance < 115)
          line(
            [
              [node.x, node.y],
              [other.x, other.y],
            ],
            "#a9cf7c" + (node.depth > 0 ? "45" : "14"),
            0.7,
          );
      });
    });
    for (var j = 0; j < 12; j++) {
      var a = nodes[j * 7],
        b = nodes[(j * 7 + 7) % count],
        f = (elapsed * 0.23 + j * 0.17) % 1;
      dot(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, 2.2, "#eda97b");
    }
    nodes
      .slice()
      .sort(function (a, b) {
        return a.depth - b.depth;
      })
      .forEach(function (node, index) {
        if (index % 17 === 0) dot(node.x, node.y, node.r + 7, "#c4f08a13");
        dot(
          node.x,
          node.y,
          node.r,
          index % 17 === 0 ? "#eda97b" : node.depth > 0 ? "#d0eea4" : "#57794c",
        );
      });
    context.beginPath();
    context.ellipse(400, 258, 300, 80, -0.3, 0, Math.PI * 2);
    context.strokeStyle = "#aacd7e35";
    context.lineWidth = 1;
    context.stroke();
  }
  function drawWorlds() {
    context.beginPath();
    context.moveTo(115, 270);
    context.lineTo(225, 270);
    context.bezierCurveTo(285, 270, 270, 150, 350, 150);
    context.moveTo(225, 270);
    context.bezierCurveTo(285, 270, 270, 390, 350, 390);
    context.strokeStyle = "#aacd7e80";
    context.lineWidth = 1.2;
    context.stroke();
    dot(115, 270, 26, "#a6c486");
    dot(115, 270, 8, "#173a2b");
    city(495, 175, 0.53, false);
    city(495, 405, 0.53, true);
    context.fillStyle = "#bad59d";
    context.font = "11px monospace";
    context.fillText("A / CONTROL", 410, 48);
    context.fillStyle = "#e8a078";
    context.fillText("B / INTERVENTION", 410, 289);
    var f = (elapsed * 0.25) % 1;
    dot(115 + 110 * f, 270, 3, "#e8a078");
  }
  function draw() {
    if (!context || !width || !height) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);
    var scale = Math.min(width / 800, height / 530);
    context.translate(width / 2, height / 2);
    context.scale(scale, scale);
    context.translate(-400, -265);
    [drawCity, drawNetwork, drawWorlds][scene]();
  }
  function resize() {
    if (!context) return;
    width = viewport.clientWidth;
    height = viewport.clientHeight;
    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(width * pixelRatio));
    canvas.height = Math.max(1, Math.round(height * pixelRatio));
    viewport.classList.add("canvas-ready");
    draw();
  }
  if (context) {
    resize();
    if (typeof ResizeObserver !== "undefined")
      new ResizeObserver(resize).observe(viewport);
    else window.addEventListener("resize", resize);
  }
  if (typeof IntersectionObserver !== "undefined") {
    var visibility = new IntersectionObserver(
      function (items) {
        items.forEach(function (item) {
          item.target.classList.toggle("is-outside", !item.isIntersecting);
          item.target.querySelectorAll("svg").forEach(function (svg) {
            if (!item.isIntersecting || !running() || document.hidden) {
              if (svg.pauseAnimations) svg.pauseAnimations();
            } else if (svg.unpauseAnimations) svg.unpauseAnimations();
          });
          if (item.target === viewport) {
            heroVisible = item.isIntersecting;
            syncAnimation();
          }
        });
      },
      { rootMargin: "100px" },
    );
    [
      viewport,
      document.querySelector(".tools-section"),
      document.querySelector(".mind-diagram"),
      document.querySelector(".network-panel"),
      document.querySelector(".branch-diagram"),
      document.querySelector(".closing"),
    ].forEach(function (el) {
      visibility.observe(el);
    });
    if (!reduce.matches) {
      var reveal = new IntersectionObserver(
        function (items) {
          items.forEach(function (item) {
            if (item.isIntersecting) {
              item.target.classList.add("is-visible");
              reveal.unobserve(item.target);
            }
          });
        },
        { threshold: 0.08 },
      );
      document.querySelectorAll(".reveal").forEach(function (el) {
        if (el.getBoundingClientRect().top > window.innerHeight) {
          el.classList.add("will-reveal");
          reveal.observe(el);
        }
      });
    }
  }
  var menu = document.getElementById("menu-toggle"),
    nav = document.getElementById("main-nav");
  function closeMenu() {
    menu.setAttribute("aria-expanded", "false");
    nav.classList.remove("is-open");
  }
  menu.addEventListener("click", function () {
    var open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("is-open", open);
  });
  nav.addEventListener("click", function (event) {
    if (event.target.closest("a")) closeMenu();
  });
  document.addEventListener("keydown", function (event) {
    if (
      event.key === "Escape" &&
      menu.getAttribute("aria-expanded") === "true"
    ) {
      closeMenu();
      menu.focus();
    }
  });
  window.matchMedia("(max-width: 900px)").addEventListener("change", closeMenu);
  document
    .getElementById("copy-install")
    .addEventListener("click", async function () {
      var code = document.getElementById("install-command"),
        success = false;
      try {
        await navigator.clipboard.writeText(code.textContent);
        success = true;
      } catch (_) {
        var selection = window.getSelection(),
          range = document.createRange();
        range.selectNodeContents(code);
        selection.removeAllRanges();
        selection.addRange(range);
        try {
          success = document.execCommand("copy");
        } catch (_) {}
        if (success) selection.removeAllRanges();
      }
      document.getElementById("copy-status").textContent = success
        ? language === "zh"
          ? "已复制安装与启动命令。"
          : "Installation and launch commands copied."
        : language === "zh"
          ? "命令已选中，请手动复制。"
          : "Commands selected. Please copy them manually.";
    });
  document.documentElement.classList.add("js-ready");
  updateBranch();
  setLanguage();
  syncAnimation();
})();
