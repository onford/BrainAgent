import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue') },
    { path: '/workflows', name: 'workflows', component: () => import('../views/WorkflowsView.vue') },
    { path: '/searches', name: 'searches', component: () => import('../views/SearchesView.vue') },
    { path: '/settings/integrations', name: 'integrations', component: () => import('../views/IntegrationsView.vue') },
  ],
})
