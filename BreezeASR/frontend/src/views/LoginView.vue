<script setup>
import { ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import { useAuth } from "../composables/useAuth";

const router = useRouter();
const { login } = useAuth();
const username = ref("");
const password = ref("");
const status = ref("");
const submitting = ref(false);

async function onSubmit() {
  status.value = "";
  submitting.value = true;
  try {
    await login(username.value.trim(), password.value);
    await router.push("/");
  } catch (error) {
    status.value = error.message || "登入失敗";
    submitting.value = false;
  }
}
</script>

<template>
  <AuthLayout>
    <header class="page-header">
      <p class="eyebrow">身分驗證</p>
      <h1>登入</h1>
      <p class="lead">每位使用者必須使用自己的專屬帳號，禁止共用。</p>
    </header>
    <form id="auth-form" class="card" @submit.prevent="onSubmit">
      <label for="username">帳號</label>
      <input id="username" v-model="username" name="username" type="text" autocomplete="username" required maxlength="32">
      <label for="password">密碼</label>
      <input id="password" v-model="password" name="password" type="password" autocomplete="current-password" required minlength="12">
      <button type="submit" :disabled="submitting">登入</button>
      <p id="auth-status" class="error" role="status">{{ status }}</p>
      <p class="hint">還沒有帳號？<RouterLink to="/register">建立專屬帳號</RouterLink></p>
    </form>
  </AuthLayout>
</template>
