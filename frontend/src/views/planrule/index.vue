<template>
  <section class="page" data-module="planrule">
    <header class="page-head">
      <div>
        <h2>养护计划编排规则</h2>
        <p class="page-desc">按养护类型配置间隔天数与提前天数；规则保存或启停后，已编养护计划会按新规则重新判定，不合规的会在养护计划台账里标出。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记编排规则</button>
        <button class="btn" type="button" @click="reevaluate">按规则重新判定</button>
        <button class="btn" type="button" @click="exportRows">导出编排规则清单</button>
      </div>
    </header>

    <form v-if="showForm" class="edit-panel" @submit.prevent="submitForm">
      <h3 class="edit-title">{{ editingId ? `修改编排规则（${form.规则编号}）` : '登记编排规则' }}</h3>
      <div class="edit-grid">
        <label v-for="field in formFields" :key="field.key" class="edit-item">
          <span>{{ field.label }}</span>
          <input v-model="form[field.key]" :type="field.type ?? 'text'" :placeholder="field.placeholder ?? ''" />
        </label>
      </div>
      <div class="edit-actions">
        <button class="btn primary" type="submit">保存规则</button>
        <button class="btn ghost" type="button" @click="closeForm">取消</button>
      </div>
      <p v-if="formError" class="error-text">{{ formError }}</p>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">修改</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无编排规则数据，可先登记编排规则</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条编排规则记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/planrule'
const columns = ["规则编号", "养护类型", "间隔天数", "提前天数", "适用对象", "生效日期", "编制人员", "规则状态"]
const actions = ["启用规则", "停用规则"]
const formFields = [
  { key: '规则编号', label: '规则编号', placeholder: '如 RULE-0004' },
  { key: '养护类型', label: '养护类型', placeholder: '如 日常保洁' },
  { key: '间隔天数', label: '间隔天数', type: 'number', placeholder: '同一对象两次养护的最小间隔' },
  { key: '提前天数', label: '提前天数', type: 'number', placeholder: '计划开始需提前编制的天数' },
  { key: '适用对象', label: '适用对象', placeholder: '如 道路设施' },
  { key: '生效日期', label: '生效日期', type: 'date' },
  { key: '编制人员', label: '编制人员' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 2)

const showForm = ref(false)
const editingId = ref<number | null>(null)
const form = ref<Record<string, string>>({})
const formError = ref('')

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  editingId.value = null
  form.value = {}
  formError.value = ''
  showForm.value = true
}

function openEdit(row: Row) {
  editingId.value = Number(row.id)
  form.value = Object.fromEntries(formFields.map((field) => [field.key, String(row[field.key] ?? '')]))
  formError.value = ''
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  formError.value = ''
}

async function submitForm() {
  formError.value = ''
  const url = editingId.value ? `${ENDPOINT}/${editingId.value}` : ENDPOINT
  try {
    const response = await request(url, {
      method: editingId.value ? 'PUT' : 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      formError.value = payload.message ?? '编排规则保存失败'
      return
    }
    noticeMessage.value = payload.message ?? ''
    closeForm()
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '编排规则保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message ?? '编排规则动作未生效')
    }
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '编排规则操作失败'
  }
}

async function reevaluate() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reevaluate`, { method: 'POST' })
    const payload = await response.json()
    noticeMessage.value = payload.message ?? ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新判定失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('编排规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '编排规则列表读取失败'
  }
}

onMounted(reload)
</script>
