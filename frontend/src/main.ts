import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import './style.css'
import { initializeLocale } from './i18n'

initializeLocale()
createApp(App).use(createPinia()).use(router).mount('#app')
