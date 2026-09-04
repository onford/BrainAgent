<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  deleteIntegration,
  fetchIntegrations,
  saveIntegration,
  validateIntegration,
} from '../api/integrations'
import type { CredentialField, ToolIntegration } from '../types/integration'

type FieldValue = string | number | boolean

const tools = ref<ToolIntegration[]>([])
const selectedId = ref<string | null>(null)
const loading = ref(true)
const busyAction = ref<string | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const values = reactive<Record<string, FieldValue>>({})
const touched = reactive<Record<string, boolean>>({})
const removals = reactive<Record<string, boolean>>({})
const enabled = ref(true)

const selected = computed(() => tools.value.find((tool) => tool.id === selectedId.value) ?? null)

function statusLabel(tool: ToolIntegration): string {
  if (!tool.enabled) return '已停用'
  if (tool.status === 'valid') return '已验证'
  if (tool.status === 'invalid') return '验证失败'
  if (tool.credential_requirement === 'none' && !tool.configured) return '可直接使用'
  return tool.configured ? '待验证' : '未配置'
}

function statusClass(tool: ToolIntegration): string {
  if (!tool.enabled) return 'muted'
  if (tool.status === 'valid' || (tool.credential_requirement === 'none' && !tool.configured)) return 'valid'
  if (tool.status === 'invalid') return 'invalid'
  return 'pending'
}

function choose(tool: ToolIntegration): void {
  selectedId.value = tool.id
  enabled.value = tool.enabled
  error.value = null
  notice.value = null
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(touched)) delete touched[key]
  for (const key of Object.keys(removals)) delete removals[key]
  for (const field of tool.credential_schema) {
    if (field.type === 'boolean') values[field.key] = Boolean(field.value)
    else if (field.value !== null && field.value !== undefined) values[field.key] = field.value
    else values[field.key] = ''
  }
}

function updateValue(field: CredentialField, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  values[field.key] = field.type === 'boolean' && target instanceof HTMLInputElement
    ? target.checked
    : field.type === 'number'
      ? Number(target.value)
      : target.value
  touched[field.key] = true
  removals[field.key] = false
}

function removeField(field: CredentialField): void {
  removals[field.key] = true
  touched[field.key] = false
  values[field.key] = field.type === 'boolean' ? false : ''
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    tools.value = await fetchIntegrations()
    const next = tools.value.find((tool) => tool.id === selectedId.value) ?? tools.value[0]
    if (next) choose(next)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法加载工具配置'
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!selected.value) return
  busyAction.value = 'save'
  error.value = null
  notice.value = null
  const credentials: Record<string, FieldValue> = {}
  for (const field of selected.value.credential_schema) {
    if (touched[field.key] && !removals[field.key]) credentials[field.key] = values[field.key]
  }
  try {
    const updated = await saveIntegration(selected.value.id, {
      enabled: enabled.value,
      credentials,
      remove_credentials: Object.keys(removals).filter((key) => removals[key]),
    })
    tools.value = tools.value.map((tool) => tool.id === updated.id ? updated : tool)
    choose(updated)
    notice.value = '配置已安全保存，连接状态已重置为待验证。'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '保存失败'
  } finally {
    busyAction.value = null
  }
}

async function validate(): Promise<void> {
  if (!selected.value) return
  busyAction.value = 'validate'
  error.value = null
  notice.value = null
  try {
    const result = await validateIntegration(selected.value.id)
    await load()
    if (result.valid) notice.value = '连接验证成功。'
    else error.value = result.message
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '连接验证失败'
  } finally {
    busyAction.value = null
  }
}

async function clearConfiguration(): Promise<void> {
  if (!selected.value || !window.confirm(`删除 ${selected.value.name} 的所有已保存配置？`)) return
  busyAction.value = 'delete'
  error.value = null
  try {
    await deleteIntegration(selected.value.id)
    await load()
    notice.value = '已删除该工具的用户配置。'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '删除失败'
  } finally {
    busyAction.value = null
  }
}

onMounted(load)
</script>

<template>
  <main class="integrations-page">
    <header class="registry-header">
      <RouterLink to="/" class="back-link">← 返回对话</RouterLink>
      <span class="runtime-state"><i></i>Credential vault ready</span>
    </header>

    <div class="integrations-shell">
      <section class="integrations-heading">
        <span class="page-kicker">TOOL INTEGRATIONS</span>
        <h1>外部工具与凭据</h1>
        <p>为研究 Agent 配置外部数据源。密钥只会加密保存并在服务端调用时短暂解密，不会进入对话内容。</p>
      </section>

      <div v-if="loading" class="integration-loading">正在读取工具定义…</div>
      <p v-else-if="error && !selected" class="integration-alert error">{{ error }}</p>

      <div v-else class="integration-workspace">
        <nav class="tool-catalog" aria-label="外部工具列表">
          <button
            v-for="tool in tools"
            :key="tool.id"
            type="button"
            :class="{ active: tool.id === selectedId }"
            @click="choose(tool)"
          >
            <span class="tool-monogram">{{ tool.name.slice(0, 2).toUpperCase() }}</span>
            <span class="tool-list-copy"><strong>{{ tool.name }}</strong><small>{{ tool.category }}</small></span>
            <span class="status-chip" :class="statusClass(tool)">{{ statusLabel(tool) }}</span>
          </button>
        </nav>

        <section v-if="selected" class="integration-detail">
          <div class="integration-title-row">
            <div>
              <span class="detail-category">{{ selected.category }}</span>
              <h2>{{ selected.name }}</h2>
              <p>{{ selected.description }}</p>
            </div>
            <span class="status-chip large" :class="statusClass(selected)">{{ statusLabel(selected) }}</span>
          </div>

          <div class="integration-meta">
            <span><strong>{{ selected.cost_policy.tier }}</strong>{{ selected.cost_policy.summary }}</span>
            <span><strong>凭据</strong>{{ selected.credential_requirement === 'required' ? '必需' : selected.credential_requirement === 'optional' ? '可选' : '无需凭据' }}</span>
          </div>

          <form class="credential-form" @submit.prevent="save">
            <label class="enabled-row">
              <span><strong>启用此工具</strong><small>停用后 Agent 无法取得该工具客户端。</small></span>
              <input v-model="enabled" type="checkbox" />
            </label>

            <div v-if="selected.credential_schema.length" class="credential-fields">
              <div v-for="field in selected.credential_schema" :key="field.key" class="credential-field">
                <label :for="`${selected.id}-${field.key}`">
                  {{ field.label }} <em v-if="field.required">必填</em>
                  <small v-if="field.description">{{ field.description }}</small>
                </label>
                <div class="credential-control">
                  <input
                    v-if="field.type !== 'select' && field.type !== 'boolean'"
                    :id="`${selected.id}-${field.key}`"
                    :type="field.type === 'secret' ? 'password' : field.type"
                    :value="values[field.key]"
                    :placeholder="field.configured && field.type === 'secret' ? field.masked_value ?? '********' : field.placeholder ?? ''"
                    autocomplete="off"
                    @input="updateValue(field, $event)"
                  />
                  <select
                    v-else-if="field.type === 'select'"
                    :id="`${selected.id}-${field.key}`"
                    :value="values[field.key]"
                    @change="updateValue(field, $event)"
                  >
                    <option value="">请选择</option>
                    <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <input
                    v-else
                    :id="`${selected.id}-${field.key}`"
                    type="checkbox"
                    :checked="Boolean(values[field.key])"
                    @change="updateValue(field, $event)"
                  />
                  <button v-if="field.configured && !removals[field.key]" type="button" class="field-remove" @click="removeField(field)">移除</button>
                  <span v-if="removals[field.key]" class="removal-note">保存后移除</span>
                </div>
              </div>
            </div>
            <div v-else class="no-credentials">此服务可匿名访问，不需要保存凭据。</div>

            <p v-if="notice" class="integration-alert success">{{ notice }}</p>
            <p v-if="error" class="integration-alert error">{{ error }}</p>
            <p v-if="selected.last_validation_error" class="validation-history">最近验证：{{ selected.last_validation_error }}</p>

            <div class="integration-actions">
              <button class="primary-action" type="submit" :disabled="Boolean(busyAction)">{{ busyAction === 'save' ? '保存中…' : '保存配置' }}</button>
              <button class="secondary-action" type="button" :disabled="Boolean(busyAction)" @click="validate">{{ busyAction === 'validate' ? '验证中…' : '验证连接' }}</button>
              <button v-if="selected.configured" class="danger-action" type="button" :disabled="Boolean(busyAction)" @click="clearConfiguration">删除配置</button>
            </div>
          </form>
        </section>
      </div>
    </div>
  </main>
</template>
