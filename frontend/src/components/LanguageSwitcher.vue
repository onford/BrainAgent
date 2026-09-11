<script setup lang="ts">
import { locale, setLocale } from '../i18n'
defineProps<{ dark?: boolean }>()
</script>

<template>
  <div class="language-switcher" :class="{ dark }" role="group" aria-label="Language / 语言">
    <button type="button" lang="en" :aria-pressed="locale === 'en'" aria-label="English" @click="setLocale('en')">EN</button>
    <button type="button" lang="zh-CN" :aria-pressed="locale === 'zh'" aria-label="简体中文" @click="setLocale('zh')">中文</button>
  </div>
</template>

<style scoped>
.language-switcher{display:inline-flex;flex:none;align-items:center;gap:2px;padding:3px;border:1px solid #dce5df;border-radius:8px;background:#f3f6f4}
.language-switcher button{border:0;border-radius:5px;padding:5px 8px;margin:0;background:transparent;color:#63776b;font:500 11px/1.4 system-ui,sans-serif;min-height:28px;cursor:pointer;white-space:nowrap;letter-spacing:0}
.language-switcher button[aria-pressed=true]{background:#fff;color:#245f43;box-shadow:0 1px 3px #173d2314}
.language-switcher button:hover{color:#1e593d;background:#e5ede8}
.language-switcher button:focus-visible{outline:2px solid #397957;outline-offset:2px}
.dark{background:#202020;border-color:#373737}
.dark button{color:#a6b0aa}.dark button[aria-pressed=true]{background:#37473d;color:#e0f0e5;box-shadow:none}
.dark button:hover{background:#303a33;color:#fff}
</style>
