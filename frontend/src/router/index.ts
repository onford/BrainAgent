import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
    { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue') },
    { path: '/workflows', name: 'workflows', component: () => import('../views/WorkflowsView.vue') },
    { path: '/searches', name: 'searches', component: () => import('../views/SearchesView.vue') },
    { path: '/preprocessing/units', name: 'preprocessing-units', component: () => import('../views/PreprocessingUnitsView.vue') },
    { path: '/settings/integrations', name: 'integrations', component: () => import('../views/IntegrationsView.vue') },
  ],
})
