import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import AgentsView from '../views/AgentsView.vue'
import IntegrationsView from '../views/IntegrationsView.vue'
import WorkflowsView from '../views/WorkflowsView.vue'
import SearchesView from '../views/SearchesView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/agents', name: 'agents', component: AgentsView },
    { path: '/workflows', name: 'workflows', component: WorkflowsView },
    { path: '/searches', name: 'searches', component: SearchesView },
    { path: '/settings/integrations', name: 'integrations', component: IntegrationsView },
  ],
})
