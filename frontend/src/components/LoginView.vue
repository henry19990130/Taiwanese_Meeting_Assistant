<script setup>
import { onMounted } from "vue";
import { session } from "../state.js";
import { accountOk, enterRoom, passwordOk } from "../composables/useAuth.js";
import { api } from "../composables/useApi.js";
import { $, showError } from "../lib/dom.js";
import { views } from "../views.js";

const REG_RULES = {
  ulen: (v) => v.username.trim().length >= 3 && v.username.trim().length <= 32,
  uchars: (v) => v.username.trim().length > 0 && /^[A-Za-z0-9_]*$/.test(v.username.trim()),
  plen: (v) => v.password.length >= 12 && v.password.length <= 200,
  pletter: (v) => /[A-Za-z]/.test(v.password),
  pdigit: (v) => /[0-9]/.test(v.password),
  pmatch: (v) => v.password2.length > 0 && v.password === v.password2,
};
const RULE_FIELD = { ulen: "username", uchars: "username", plen: "password", pletter: "password", pdigit: "password", pmatch: "password2" };

function regValues() {
  const f = $("registerForm");
  return { username: f.username.value, password: f.password.value, password2: f.password2.value };
}
function updateRegRules(showAll = false) {
  const v = regValues();
  for (const li of $("registerForm").querySelectorAll(".rules li")) {
    const rule = li.dataset.rule;
    const ok = REG_RULES[rule](v);
    const touched = showAll || v[RULE_FIELD[rule]].length > 0;
    li.classList.toggle("is-ok", ok);
    li.classList.toggle("is-bad", touched && !ok);
  }
}
function showAuth(which, message) {
  const register = which === "register";
  $("loginForm").hidden = register;
  $("registerForm").hidden = !register;
  showError($("loginError"), register ? "" : (message || ""));
  showError($("registerError"), "");
  if (register) updateRegRules();
}

onMounted(() => {
  views.showAuth = showAuth;
  $("registerForm").addEventListener("input", () => updateRegRules());
  $("showRegister").addEventListener("click", () => showAuth("register"));
  $("showLogin").addEventListener("click", () => showAuth("login"));
  $("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    showError($("loginError"), "");
    try {
      const data = await api("/api/v1/auth/login", {
        method: "POST", json: { username: f.get("username"), password: f.get("password") },
      });
      await enterRoom(data, e.target);
    } catch (err) { showError($("loginError"), err.message); }
  });
  $("registerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const username = String(f.get("username") || "").trim();
    const password = String(f.get("password") || "");
    const again = String(f.get("password2") || "");
    const display_name = String(f.get("display_name") || "").trim();
    showError($("registerError"), "");
    updateRegRules(true);
    if (display_name.length > 20) { showError($("registerError"), "稱呼最多 20 個字"); return; }
    if (!accountOk(username)) { showError($("registerError"), "帳號只允許 3 到 32 碼的英數字或底線"); return; }
    if (!passwordOk(password)) { showError($("registerError"), "密碼至少 12 碼，而且要同時含英文字母和數字"); return; }
    if (password !== again) { showError($("registerError"), "兩次輸入的密碼不相同"); return; }
    try {
      const data = await api("/api/v1/auth/register", { method: "POST", json: { username, password, display_name } });
      await enterRoom(data, e.target);
    } catch (err) { showError($("registerError"), err.message); }
  });
});
</script>

<template>
  <section class="login" id="loginView" :hidden="session.entered">
    <figure class="login-photo">
      <img src="/img/window-corner.jpg" alt="午後陽光下的窗邊木桌，桌上有麥克風、筆記本、茶杯和橄欖樹盆栽">
      <figcaption><span>15:00 · 會議室</span><span>錄音只在這台電腦處理</span></figcaption>
    </figure>
    <div class="login-panel">
      <div class="brand">
        <svg class="brand-mark" width="40" height="40" role="img" aria-label="覓聲"><use href="#ms-mark"/></svg>
        <span class="brand-name">覓聲</span><span class="brand-en">MeetSum</span>
      </div>
      <div class="login-main">
        <p class="eyebrow">AI 智慧會議紀錄與摘要系統　·　<span id="loginGreeting">早安</span></p>
        <h2 class="login-title">讓聲音被理解，<br>讓重點被記住。</h2>
        <form id="loginForm" class="login-form" autocomplete="on">
          <label>帳號<input class="line-input" name="username" required autocomplete="username" placeholder="你的帳號"></label>
          <label>密碼<input class="line-input" name="password" type="password" required autocomplete="current-password"></label>
          <p class="error" id="loginError" hidden></p>
          <button class="btn primary pill-btn" type="submit">進入會議室 <span aria-hidden="true">→</span></button>
          <button class="linkish" type="button" id="showRegister">建立帳號</button>
        </form>
        <form id="registerForm" class="login-form" hidden novalidate>
          <label><span>怎麼稱呼您 <span class="opt">（選填）</span></span>
            <input class="line-input" name="display_name" maxlength="20" autocomplete="nickname" placeholder="例如：小陳、王經理" aria-describedby="nameHint">
            <span class="field-hint" id="nameHint">登入後會用這個稱呼跟您打招呼，最多 20 個字；不填就用帳號</span>
          </label>
          <label>帳號
            <input class="line-input" name="username" autocomplete="username" required maxlength="100" aria-describedby="userRules">
            <ul class="rules" id="userRules" aria-live="polite">
              <li data-rule="ulen">3 到 32 碼</li>
              <li data-rule="uchars">只能用英文、數字或底線 _</li>
            </ul>
          </label>
          <label>密碼
            <input class="line-input" name="password" type="password" autocomplete="new-password" required aria-describedby="pwRules">
            <ul class="rules" id="pwRules" aria-live="polite">
              <li data-rule="plen">至少 12 碼</li>
              <li data-rule="pletter">含英文字母</li>
              <li data-rule="pdigit">含數字</li>
            </ul>
          </label>
          <label>再輸入一次密碼
            <input class="line-input" name="password2" type="password" autocomplete="new-password" required aria-describedby="pw2Rules">
            <ul class="rules" id="pw2Rules" aria-live="polite">
              <li data-rule="pmatch">兩次輸入相同</li>
            </ul>
          </label>
          <p class="error" id="registerError" hidden></p>
          <button class="btn primary pill-btn" type="submit">建立帳號 <span aria-hidden="true">→</span></button>
          <button class="linkish" type="button" id="showLogin">回到登入</button>
        </form>
      </div>
      <div class="login-foot"><span>本機模式 · 錄音不上雲</span><span>台語＋華語辨識</span></div>
    </div>
  </section>
</template>
