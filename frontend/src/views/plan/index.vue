<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>养护计划管理</h2>
        <p class="page-desc">维护养护计划，登记与修改都按编排规则判定：间隔没到、已有在途计划、排期撞同一时间段、编号重复或对象不存在时不允许保存。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记养护计划</button>
        <button class="btn" type="button" @click="reevaluate">按规则重新判定</button>
        <button class="btn" type="button" @click="exportRows">导出养护计划清单</button>
        <button class="btn" type="button" @click="printLedger">打印台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showForm" class="edit-panel" @submit.prevent="submitForm">
      <h3 class="edit-title">{{ editingId ? `修改养护计划（${form.计划编号}）` : '登记养护计划' }}</h3>
      <div class="edit-grid">
        <label class="edit-item">
          <span>计划编号</span>
          <input v-model="form.计划编号" placeholder="如 PLAN-0004" />
        </label>
        <label class="edit-item">
          <span>养护类型</span>
          <select v-model="form.养护类型">
            <option value="" disabled>请选择养护类型</option>
            <option v-for="item in typeOptions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label class="edit-item">
          <span>养护对象</span>
          <select v-model="form.养护对象">
            <option value="" disabled>请选择设施台账内的养护对象</option>
            <option v-for="item in targetOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="edit-item">
          <span>计划开始日期</span>
          <input v-model="form.计划开始日期" type="date" />
        </label>
        <label class="edit-item">
          <span>计划结束日期</span>
          <input v-model="form.计划结束日期" type="date" />
        </label>
        <label class="edit-item">
          <span>计划工期</span>
          <input v-model="form.计划工期" placeholder="如 3天" />
        </label>
        <label class="edit-item">
          <span>预算金额</span>
          <input v-model="form.预算金额" type="number" placeholder="万元" />
        </label>
        <label class="edit-item">
          <span>编制人员</span>
          <input v-model="form.编制人员" />
        </label>
      </div>
      <div class="edit-actions">
        <button class="btn primary" type="submit">保存计划</button>
        <button class="btn ghost" type="button" @click="closeForm">取消</button>
      </div>
      <div v-if="formError" class="form-error">
        <p class="error-text">{{ formError }}</p>
        <button v-if="conflictEntry" class="link" type="button" @click="openConflict">
          打开已有计划 {{ conflictEntry.计划编号 }} 去修改
        </button>
      </div>
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
          <th>合规判定</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-violation': row.合规提示 }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.合规提示" class="violation-tag" :title="String(row.合规提示)">不合规：{{ row.合规提示 }}</span>
            <span v-else class="ok-tag">合规</span>
          </td>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无养护计划数据，可先登记养护计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护计划记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/plan'
const columns = ["计划编号", "养护类型", "养护对象", "计划开始日期", "计划结束日期", "预算金额", "编制人员", "计划状态"]
const actions = ["提交审批", "确认批复", "作废计划"]
const stats = [{"label": "待审批计划", "value": 0}, {"label": "已批复计划", "value": 0}, {"label": "本月计划金额", "value": 0}]
const formKeys = ["计划编号", "养护类型", "养护对象", "计划开始日期", "计划结束日期", "计划工期", "预算金额", "编制人员"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const showForm = ref(false)
const editingId = ref<number | null>(null)
const form = ref<Record<string, string>>({})
const formError = ref('')
const conflictEntry = ref<Row | null>(null)
const typeOptions = ref<string[]>([])
const targetOptions = ref<{ value: string; label: string }[]>([])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function printLedger() {
  window.print()
}

function openCreate() {
  editingId.value = null
  form.value = {}
  formError.value = ''
  conflictEntry.value = null
  showForm.value = true
}

function openEdit(row: Row) {
  editingId.value = Number(row.id)
  form.value = Object.fromEntries(formKeys.map((key) => [key, String(row[key] ?? '')]))
  formError.value = ''
  conflictEntry.value = null
  showForm.value = true
}

function openConflict() {
  if (conflictEntry.value) {
    openEdit(conflictEntry.value)
  }
}

function closeForm() {
  showForm.value = false
  formError.value = ''
  conflictEntry.value = null
}

async function submitForm() {
  formError.value = ''
  conflictEntry.value = null
  const url = editingId.value ? `${ENDPOINT}/${editingId.value}` : ENDPOINT
  try {
    const response = await request(url, {
      method: editingId.value ? 'PUT' : 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      formError.value = payload.message ?? '养护计划保存失败'
      conflictEntry.value = payload.entry ?? null
      return
    }
    noticeMessage.value = payload.message ?? ''
    closeForm()
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '养护计划保存失败'
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
      throw new Error(payload.message ?? '养护计划动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护计划操作失败'
  }
}

async function reevaluate() {
  errorMessage.value = ''
  try {
    const response = await request('/api/planrule/reevaluate', { method: 'POST' })
    const payload = await response.json()
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新判定失败'
  }
}

async function loadOptions() {
  try {
    const [rules, roads, bridges, tunnels] = await Promise.all([
      request('/api/planrule?size=200').then((res) => res.json()),
      request('/api/road?size=200').then((res) => res.json()),
      request('/api/bridge?size=200').then((res) => res.json()),
      request('/api/tunnel?size=200').then((res) => res.json()),
    ])
    typeOptions.value = (rules.items ?? [])
      .filter((item: Row) => item.status === '启用')
      .map((item: Row) => String(item.养护类型))
    const facilities = [
      ...(roads.items ?? []).map((item: Row) => ({ value: String(item.设施编码), label: `${item.设施编码} · ${item.道路名称}` })),
      ...(bridges.items ?? []).map((item: Row) => ({ value: String(item.桥梁编码), label: `${item.桥梁编码} · ${item.桥梁名称}` })),
      ...(tunnels.items ?? []).map((item: Row) => ({ value: String(item.隧道编码), label: `${item.隧道编码} · ${item.隧道名称}` })),
    ]
    targetOptions.value = facilities
  } catch {
    // 选项加载失败不阻塞台账浏览，保存时后端仍会校验并说明原因
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('养护计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护计划列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadOptions()
})
</script>
