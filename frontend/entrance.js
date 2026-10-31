window.Entrance = (() => {
  const TAGLINE = "讓聲音被理解，讓重點被記住。";
  const byId = (id) => document.getElementById(id);
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function timeGreeting() {
    const h = new Date().getHours();
    if (h < 11) return "早安";
    if (h < 18) return "午安";
    return "晚安";
  }

  function greet(name) {
    const g = timeGreeting();
    const login = byId("loginGreeting");
    if (login) login.textContent = g;
    const home = byId("homeGreeting");
    if (home) home.textContent = name ? `${g}，${name}。` : `${g}。`;
  }

  function buildTagline() {
    const box = byId("entTagline");
    if (!box || box.childElementCount) return;
    [...TAGLINE].forEach((ch, i) => {
      const s = document.createElement("span");
      s.textContent = ch;
      s.style.animationDelay = `${1250 + i * 30}ms`;
      box.append(s);
    });
    box.setAttribute("aria-label", TAGLINE);
  }

  async function close(name) {
    const el = byId("entrance");
    if (!el) return;
    buildTagline();
    byId("entranceGreeting").textContent = `${timeGreeting()}，${name}`;
    el.className = "entrance";
    el.hidden = false;
    void el.offsetWidth;
    el.classList.add("is-playing");
    await wait(reduced() ? 300 : 2150);
  }

  async function open() {
    const el = byId("entrance");
    if (!el) return;
    const app = byId("appView");
    if (app) {
      app.classList.remove("home-in");
      void app.offsetWidth;
      app.classList.add("home-in");
    }
    el.classList.add("is-leaving");
    await wait(reduced() ? 0 : 520);
    el.hidden = true;
    el.className = "entrance";
  }

  greet();
  return { close, open, greet };
})();
