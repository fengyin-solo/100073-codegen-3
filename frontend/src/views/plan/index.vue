<template>
  <section class="page" data-module="plan">
    <header class="page-head no-print">
      <div>
        <h2>养护计划管理</h2>
        <p class="page-desc">按养护类型配置间隔与提前量；登记时自动判定间隔、在途与排期冲突，规则调整后存量计划重新判定并标出不合规项。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记养护计划</button>
        <button class="btn" type="button" @click="openRules">编排规则</button>
        <button class="btn" type="button" @click="printLedger">打印台账</button>
        <button class="btn" type="button" @click="exportRows">导出清单</button>
      </div>
    </header>

    <h3 class="print-title">养护计划台账</h3>

    <div class="stat-row no-print">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ 'stat-warn': item.warn }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar no-print" @submit.prevent="reload">
      <label class="filter-item">
        <span>计划编号</span>
        <input v-model="filters.keyword" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>计划状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>合规情况</span>
        <select v-model="filters.compliance">
          <option value="">全部</option>
          <option value="ok">仅合规</option>
          <option value="bad">仅不合规</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table ledger-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th class="no-print">可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in pagedRows" :key="String(row.id)" :class="{ 'row-clash': clashId === row.id, 'row-bad': !row['合规'] }">
          <td>{{ row['计划编号'] ?? '—' }}</td>
          <td>{{ row['养护类型'] ?? '—' }}</td>
          <td>{{ row['养护对象'] ?? '—' }}</td>
          <td>{{ row['开工日期'] ?? '—' }}</td>
          <td>{{ row['完工日期'] ?? '—' }}</td>
          <td>{{ row['预算金额'] ?? '—' }}</td>
          <td>{{ row['编制人员'] || '—' }}</td>
          <td>{{ row['status'] ?? '—' }}</td>
          <td>
            <span v-if="row['合规']" class="badge badge-ok">合规</span>
            <button v-else class="link" type="button" :title="violationTexts(row).join('；')" @click="locate = row.id">
              <span class="badge badge-bad">不合规（{{ (row['违规项'] || []).length }}）</span>
            </button>
          </td>
          <td class="violation-cell">
            <ul v-if="(row['违规项'] || []).length" class="violation-list">
              <li v-for="(v, i) in row['违规项']" :key="v.code + i">
                {{ v.message }}
                <button
                  v-if="v['冲突计划'] && String(v['冲突计划'].id) !== String(row.id)"
                  class="link"
                  type="button"
                  @click="locateConflict(v['冲突计划'].id)"
                >定位冲突计划</button>
              </li>
            </ul>
            <span v-else>—</span>
          </td>
          <td class="row-actions no-print">
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
        <tr v-if="!pagedRows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无养护计划数据，可先登记养护计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot no-print">
      <span>
        共 {{ filteredRows.length }} 条养护计划记录，第 {{ page }} / {{ totalPages || 1 }} 页
        <button class="btn" type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="page += 1">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记 / 修改 养护计划 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <h3>{{ formMode === 'create' ? '登记养护计划' : `修改养护计划 ${form['计划编号']}` }}</h3>
        <div class="form-grid">
          <label v-for="f in formFields" :key="f.name" :class="{ 'field-error': errorFields.has(f.name) }">
            <span>{{ f.label }}<i v-if="f.required">*</i></span>
            <input
              v-model="form[f.name]"
              :type="f.type || 'text'"
              :list="f.list"
              :placeholder="f.placeholder || ''"
            />
          </label>
        </div>
        <datalist id="object-list">
          <option v-for="o in objectOptions" :key="o['对象编码']" :value="o['对象名称']">[{{ o['对象分类'] }}] {{ o['对象编码'] }}</option>
        </datalist>
        <datalist id="type-list">
          <option v-for="r in rules" :key="r.id" :value="r['养护类型']"></option>
        </datalist>
        <p class="form-hint">养护对象从道路、桥梁、隧道台账中按编码或名称选择；同对象同类型存在在途计划时不可再排，排期重叠会指出撞了哪一条。</p>
        <ul v-if="formViolations.length" class="violation-list violation-block">
          <li v-for="(v, i) in formViolations" :key="v.code + i" class="error-text">
            {{ v.message }}
            <button
              v-if="v['冲突计划']"
              class="link"
              type="button"
              @click="jumpConflictFromForm(v['冲突计划'].id)"
            >查看冲突计划 {{ v['冲突计划']['计划编号'] }}</button>
          </li>
        </ul>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="submitForm">
            {{ saving ? '校验中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 编排规则 -->
    <div v-if="rulesVisible" class="modal-mask" @click.self="rulesVisible = false">
      <div class="modal modal-wide">
        <h3>养护类型编排规则</h3>
        <p class="form-hint">调整间隔或提前量并保存后，已编好的养护计划会按新规则重新判定，下方会标出不合规的那几条。最小间隔填 0 表示该类型不做间隔限制。</p>
        <table class="data-table">
          <thead>
            <tr>
              <th>养护类型</th>
              <th>最小间隔（天）</th>
              <th>提前量（天）</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in rules" :key="rule.id">
              <td>{{ rule['养护类型'] }}</td>
              <td><input v-model.number="rule['最小间隔天数']" type="number" min="0" class="rule-input" /></td>
              <td><input v-model.number="rule['提前量天数']" type="number" min="0" class="rule-input" /></td>
              <td><button class="btn" type="button" @click="saveRule(rule)">保存并重判</button></td>
            </tr>
          </tbody>
        </table>
        <div class="new-rule">
          <span>新增类型：</span>
          <input v-model="newRule['养护类型']" placeholder="养护类型，如：修复养护" />
          <input v-model.number="newRule['最小间隔天数']" type="number" min="0" placeholder="最小间隔天数" />
          <input v-model.number="newRule['提前量天数']" type="number" min="0" placeholder="提前量天数" />
          <button class="btn primary" type="button" @click="saveRule(newRule)">新增规则</button>
        </div>
        <div v-if="recheckMessage" class="recheck-box">
          <p>{{ recheckMessage }}</p>
          <ul v-if="flagged.length" class="violation-list">
            <li v-for="f in flagged" :key="f.id">
              <button class="link" type="button" @click="locateFromRules(f.id)">
                {{ f['计划编号'] }}（{{ f['养护对象'] }}）
              </button>
              <span v-for="(v, i) in f['违规项']" :key="v.code + i"> — {{ v.code }}</span>
            </li>
          </ul>
          <span v-else>所有养护计划均符合当前规则。</span>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="rulesVisible = false">完成</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>
type Violation = { code: string; message: string; fields?: string[]; 冲突计划?: { id: number; 计划编号: string } }
type Rule = { id?: number; 养护类型: string; 最小间隔天数: number | null; 提前量天数: number | null }

const ENDPOINT = '/api/plan'
const PAGE_SIZE = 10
const columns = ['计划编号', '养护类型', '养护对象', '开工日期', '完工日期', '预算金额', '编制人员', '计划状态', '合规判定', '违规原因']
const actions = ['提交审批', '确认批复', '作废计划']
const statuses = ['待编制', '待审批', '已批复', '已作废']

type FormFieldDef = {
  name: string
  label: string
  required?: boolean
  type?: string
  list?: string
  placeholder?: string
}

const formFields: FormFieldDef[] = [
  { name: '计划编号', label: '计划编号', required: true },
  { name: '养护类型', label: '养护类型', required: true, list: 'type-list', placeholder: '从已配置类型中选择或输入新类型' },
  { name: '养护对象', label: '养护对象', required: true, list: 'object-list', placeholder: '按编码或名称选择台账设施' },
  { name: '开工日期', label: '开工日期', required: true, type: 'date' },
  { name: '完工日期', label: '完工日期', type: 'date' },
  { name: '预算金额', label: '预算金额（万元）', type: 'number' },
  { name: '编制人员', label: '编制人员' },
  { name: '审批人员', label: '审批人员' },
]

const rows = ref<Row[]>([])
const rules = ref<Row[]>([])
const objectOptions = ref<Row[]>([])
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '', compliance: '' })
const page = ref(1)
const clashId = ref<number | string | null>(null)
const locate = ref<number | string | null>(null)

const formVisible = ref(false)
const rulesVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const saving = ref(false)
const formViolations = ref<Violation[]>([])
const recheckMessage = ref('')
const flagged = ref<Row[]>([])

const emptyForm = (): Row => ({
  计划编号: '', 养护类型: '', 养护对象: '', 开工日期: '', 完工日期: '',
  预算金额: '', 编制人员: '', 审批人员: '',
})
const form = ref<Row>(emptyForm())
const newRule = ref<Rule>({ 养护类型: '', 最小间隔天数: null, 提前量天数: null })

const filteredRows = computed(() => {
  let list = rows.value
  if (filters.value.compliance === 'ok') list = list.filter((r) => r['合规'])
  if (filters.value.compliance === 'bad') list = list.filter((r) => !r['合规'])
  return list
})
const totalPages = computed(() => Math.ceil(filteredRows.value.length / PAGE_SIZE))
const pagedRows = computed(() => {
  if (page.value > totalPages.value) page.value = Math.max(1, totalPages.value)
  const start = (page.value - 1) * PAGE_SIZE
  return filteredRows.value.slice(start, start + PAGE_SIZE)
})
const stats = computed(() => [
  { label: '待审批计划', value: rows.value.filter((r) => r.status === '待审批').length },
  { label: '已批复计划', value: rows.value.filter((r) => r.status === '已批复').length },
  { label: '不合规计划', value: rows.value.filter((r) => !r['合规']).length, warn: true },
  { label: '计划总数', value: rows.value.length },
])
const errorFields = computed(() => new Set(formViolations.value.flatMap((v) => v.fields || [])))

function violationTexts(row: Row): string[] {
  return (row['违规项'] || []).map((v: Violation) => v.message)
}

async function loadRules() {
  const response = await request(`${ENDPOINT}/rules`)
  if (response.ok) rules.value = await response.json()
}

async function loadObjects() {
  const response = await request(`${ENDPOINT}/objects`)
  if (response.ok) objectOptions.value = await response.json()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}&size=200`)
    if (!response.ok) throw new Error('养护计划台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    await maybeShowLocate()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护计划台账读取失败'
  }
}

function resetFilters() {
  filters.value = { keyword: '', status: '', compliance: '' }
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function printLedger() {
  clashId.value = null
  window.print()
}

// ------------------------------------------------------------ 登记 / 修改
function openCreate() {
  formMode.value = 'create'
  editingId.value = null
  form.value = emptyForm()
  formViolations.value = []
  formVisible.value = true
}

function openEdit(row: Row) {
  formMode.value = 'edit'
  editingId.value = row.id
  form.value = { ...emptyForm(), ...pickRow(row) }
  formViolations.value = []
  formVisible.value = true
}

function pickRow(row: Row): Row {
  const picked: Row = {}
  for (const f of formFields) picked[f.name] = row[f.name] ?? ''
  return picked
}

function closeForm() {
  formVisible.value = false
}

async function submitForm() {
  saving.value = true
  formViolations.value = []
  const values: Record<string, unknown> = {}
  for (const f of formFields) {
    const raw = form.value[f.name]
    if (raw === '' || raw === null || raw === undefined) continue
    values[f.name] = raw
  }
  const isEdit = formMode.value === 'edit' && editingId.value !== null
  try {
    const response = await request(isEdit ? `${ENDPOINT}/${editingId.value}` : ENDPOINT, {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      formViolations.value = payload.violations || [{ code: '保存失败', message: payload.message, fields: [] }]
      return
    }
    formVisible.value = false
    await reload()
  } catch (error) {
    formViolations.value = [{ code: '网络错误', message: error instanceof Error ? error.message : '请求未送达', fields: [] }]
  } finally {
    saving.value = false
  }
}

// ------------------------------------------------------------ 状态动作
async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '养护计划动作未生效'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护计划操作失败'
  }
}

// ------------------------------------------------------------ 编排规则
function openRules() {
  rulesVisible.value = true
  recheckMessage.value = ''
  flagged.value = []
  void loadRules()
}

async function saveRule(rule: Row) {
  errorMessage.value = ''
  if (!rule['养护类型']?.trim() || rule['最小间隔天数'] === null || rule['提前量天数'] === null) {
    errorMessage.value = '养护类型、最小间隔天数、提前量天数都要填写（间隔可填 0）'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/rules`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          养护类型: rule['养护类型'],
          最小间隔天数: rule['最小间隔天数'],
          提前量天数: rule['提前量天数'],
        },
      }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message
      return
    }
    recheckMessage.value = payload.recheck_message
    flagged.value = payload.flagged || []
    newRule.value = { 养护类型: '', 最小间隔天数: null, 提前量天数: null }
    await Promise.all([loadRules(), reload()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '规则保存失败'
  }
}

// ------------------------------------------------------------ 冲突定位
async function maybeShowLocate() {
  if (locate.value === null) return
  const found = rows.value.some((r) => String(r.id) === String(locate.value))
  if (found) {
    clashId.value = locate.value
    locate.value = null
    window.setTimeout(() => {
      if (clashId.value !== null) clashId.value = null
    }, 4000)
  } else {
    // 冲突计划被过滤或在其它页：清掉条件重新拉
    filters.value = { keyword: '', status: '', compliance: '' }
    page.value = 1
    await reload()
  }
}

async function focusConflict(id: number | string) {
  formVisible.value = false
  rulesVisible.value = false
  locate.value = id
  clashId.value = null
  page.value = 1
  filters.value = { keyword: '', status: '', compliance: '' }
  await reload()
}

function locateConflict(id: number | string) {
  void focusConflict(id)
}

function jumpConflictFromForm(id: number | string) {
  void focusConflict(id)
}

function locateFromRules(id: number | string) {
  void focusConflict(id)
}

onMounted(() => {
  void reload()
  void loadRules()
  void loadObjects()
})
</script>

<style scoped>
.print-title { display: none; margin: 0 0 12px; }
.stat-warn { color: #b42318; }
.ledger-table td { vertical-align: top; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.badge-ok { background: #e7f6ec; color: #1a7f37; border: 1px solid #b7dfc4; }
.badge-bad { background: #fdecea; color: #b42318; border: 1px solid #f3b4ad; }
.violation-cell { max-width: 320px; }
.violation-list { margin: 0; padding-left: 16px; }
.violation-list li { font-size: 12px; margin: 2px 0; }
.violation-block { padding: 8px 12px; background: #fdecea; border-radius: 6px; }
.row-bad { background: #fff8f7; }
.row-clash { background: #fff3cd !important; transition: background-color 0.5s; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { background: #fff; border-radius: 10px; padding: 20px 24px; width: 640px; max-height: 86vh; overflow: auto; }
.modal-wide { width: 820px; }
.modal h3 { margin: 0 0 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.form-grid label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.form-grid label i { color: #b42318; font-style: normal; margin-left: 2px; }
.form-grid input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.form-grid .field-error input { border-color: #b42318; background: #fdecea; }
.form-hint { font-size: 12px; color: var(--muted); margin: 10px 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.rule-input { width: 90px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; }
.new-rule { display: flex; gap: 8px; align-items: center; margin: 14px 0; flex-wrap: wrap; }
.new-rule input { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.recheck-box { background: #f6f8fb; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.page-foot button.btn { margin-left: 6px; padding: 2px 8px; }

@media print {
  .no-print, .modal-mask { display: none !important; }
  .app-side, .app-head { display: none !important; }
  .app-main { padding: 0; }
  .print-title { display: block; }
  .page { padding: 0; }
  .ledger-table, .ledger-table tr { background: #fff; }
  .row-bad, .row-clash { background: #fff !important; }
}
</style>
