<script setup>
import { onMounted } from "vue";

const TAGLINE = "讓聲音被理解，讓重點被記住。";
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
  const login = document.getElementById("loginGreeting");
  if (login) login.textContent = g;
  const home = document.getElementById("homeGreeting");
  if (home) home.textContent = name ? `${g}，${name}。` : `${g}。`;
}
function buildTagline() {
  const box = document.getElementById("entTagline");
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
  const node = document.getElementById("entrance");
  if (!node) return;
  buildTagline();
  document.getElementById("entranceGreeting").textContent = `${timeGreeting()}，${name}`;
  node.className = "entrance";
  node.hidden = false;
  void node.offsetWidth;
  node.classList.add("is-playing");
  await wait(reduced() ? 300 : 2150);
}
async function open() {
  const node = document.getElementById("entrance");
  if (!node) return;
  const app = document.getElementById("appView");
  if (app) {
    app.classList.remove("home-in");
    void app.offsetWidth;
    app.classList.add("home-in");
  }
  node.classList.add("is-leaving");
  await wait(reduced() ? 0 : 520);
  node.hidden = true;
  node.className = "entrance";
}

onMounted(() => greet());
defineExpose({ greet, close, open });
</script>

<template>
  <div class="entrance" id="entrance" hidden>
    <div class="ent-inner">
      <div class="ent-mark" aria-hidden="true">
        <svg class="ent-brackets" viewBox="0 0 48 48"><g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="3"><path d="M8 19V10a2 2 0 0 1 2-2h9" stroke="#2B2420"/><path d="M40 29v9a2 2 0 0 1-2 2h-9" stroke="#5E7A5A"/></g></svg>
        <svg class="ent-bars" viewBox="0 0 48 48"><g fill="#2B2420"><rect class="b1" x="15" y="20" width="4" height="8" rx="2"/><rect class="b2" x="22" y="14" width="4" height="20" rx="2"/><rect class="b3" x="29" y="18" width="4" height="12" rx="2"/></g></svg>
      </div>
      <p class="ent-tagline" id="entTagline" role="status"></p>
      <div class="ent-line"></div>
      <span class="ent-greet" id="entranceGreeting"></span>
    </div>
  </div>
</template>
