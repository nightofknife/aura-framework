<template>
  <div class="input-field">
    <div v-if="normalized.label || normalized.name" class="label">
      {{ normalized.label || normalized.name }}
      <span v-if="normalized.required" class="req">*</span>
    </div>

    <!-- base types -->
    <template v-if="isEnumSelect">
      <select class="select" v-model="innerValue" :disabled="normalized.readonly">
        <option v-for="opt in normalized.enum || []" :key="opt" :value="opt">{{ opt }}</option>
      </select>
    </template>
    <template v-else-if="normalized.type === 'string'">
      <input class="input" type="text" :placeholder="normalized.placeholder || ''"
             :disabled="normalized.readonly" v-model="innerValue" />
    </template>
    <template v-else-if="normalized.type === 'number'">
      <input class="input" type="number" :placeholder="normalized.placeholder || ''"
             :min="normalized.min" :max="normalized.max" :step="normalized.step || 'any'"
             :disabled="normalized.readonly" v-model.number="innerValue" />
    </template>
    <template v-else-if="normalized.type === 'boolean'">
      <label class="chk">
        <input type="checkbox" :disabled="normalized.readonly" v-model="innerValue" />
        {{ normalized.label || normalized.name }}
      </label>
    </template>

    <!-- Table view for list of simple dicts -->
    <div v-else-if="isSimpleDictList" class="table-block">
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="col in tableColumns" :key="col.key">
              {{ col.label || col.name || col.key }}
              <span v-if="col.required" class="req">*</span>
            </th>
            <th class="action-col">Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, idx) in listValue" :key="idx">
            <td v-for="col in tableColumns" :key="col.key">
               <!-- Render simple input directly here for performance and layout -->
               <!-- Enum/Select -->
               <select v-if="col.enum && col.enum.length" 
                       :value="item[col.key]" 
                       @change="updateTableItem(idx, col.key, $event.target.value)"
                       class="table-input"
                       :disabled="normalized.readonly">
                  <option v-for="opt in col.enum" :key="opt" :value="opt">{{ opt }}</option>
               </select>
               
               <!-- Boolean -->
               <input v-else-if="col.type === 'boolean'" 
                      type="checkbox"
                      :checked="item[col.key]"
                      @change="updateTableItem(idx, col.key, $event.target.checked)"
                      :disabled="normalized.readonly" />
               
               <!-- Number -->
               <input v-else-if="col.type === 'number'"
                      type="number"
                      :value="item[col.key]"
                      @input="updateTableItem(idx, col.key, parseFloat($event.target.value))"
                      :min="col.min" :max="col.max" :step="col.step || 'any'"
                      class="table-input"
                      :disabled="normalized.readonly" />
                      
               <!-- String (Default) -->
               <input v-else
                      type="text"
                      :value="item[col.key]"
                      @input="updateTableItem(idx, col.key, $event.target.value)"
                      :placeholder="col.placeholder || ''"
                      class="table-input"
                      :disabled="normalized.readonly" />
            </td>
            <td class="action-col">
              <button type="button" class="btn-ghost small remove-btn" @click="removeList(idx)">×</button>
            </td>
          </tr>
          <tr v-if="listValue.length === 0">
             <td :colspan="tableColumns.length + 1" class="empty-state">No items. Click Add to create one.</td>
          </tr>
        </tbody>
      </table>
      <button type="button" class="btn-secondary small add-btn" @click="addList">+ Add Row</button>
    </div>

    <!-- list -->
    <div v-else-if="normalized.type === 'list'" class="list-block">
      <div v-for="(item, idx) in listValue" :key="idx" class="list-row">
        <InputFieldRenderer
          :schema="normalized.item || {}"
          :model-value="item"
          @update:modelValue="updateList(idx, $event)"
        />
        <button type="button" class="btn-ghost small" @click="removeList(idx)">Del</button>
      </div>
      <button type="button" class="btn-ghost small" @click="addList">+ Add</button>
    </div>

    <!-- dict -->
    <div v-else-if="normalized.type === 'dict'" class="dict-block">
      <InputFieldRenderer
        v-for="(child, key) in normalized.properties || {}"
        :key="key"
        :schema="{ ...child, name: child.name || key, label: child.label || child.title || key }"
        :model-value="(innerValue || {})[key]"
        @update:modelValue="(val) => updateDict(key, val)"
      />
    </div>

    <div v-else class="unknown">Unsupported type: {{ normalized.type }}</div>

    <div v-if="normalized.description" class="desc">{{ normalized.description }}</div>
  </div>
</template>

<script setup>
import {computed, defineProps, defineEmits} from 'vue';
 import {buildDefaultFromSchema, cloneInputs, normalizeInputSchema, cloneDeep} from '../utils/inputSchema.js';

const props = defineProps({
  schema: {type: Object, required: true},
  modelValue: {type: [String, Number, Boolean, Object, Array, null], default: null},
});
const emit = defineEmits(['update:modelValue']);

const normalized = computed(() => normalizeInputSchema(props.schema || {}));
const isEnumSelect = computed(() => {
  const s = normalized.value || {};
  if (!Array.isArray(s.enum) || s.enum.length === 0) return false;
  const t = s.type || 'string';
  return ['string', 'number', 'boolean'].includes(t);
});
 
 const isSimpleDictList = computed(() => {
   // Check if it's a list
   if (normalized.value.type !== 'list') return false;
   const itemSchema = normalized.value.item;
   // Check if the item is a dict
   if (!itemSchema || itemSchema.type !== 'dict') return false;
   // Check if the dict has properties and they are simple types (string, number, boolean, enum)
   // This prevents recursion hell with nested tables or complex objects
   const props = itemSchema.properties || {};
   const keys = Object.keys(props);
   if (keys.length === 0) return false;
   
   for (const k of keys) {
     const p = props[k];
     const pType = p.type || 'string';
     if (!['string', 'number', 'boolean'].includes(pType) && !p.enum) {
        return false;
     }
   }
   return true;
 });
 
 const tableColumns = computed(() => {
    if (!isSimpleDictList.value) return [];
    const itemSchema = normalized.value.item || {};
    const props = itemSchema.properties || {};
    return Object.keys(props).map(key => ({
        key,
        ...normalizeInputSchema(props[key])
    }));
 });

const innerValue = computed({
  get() {
    const val = props.modelValue;
    if (val === undefined) return buildDefaultFromSchema(normalized.value);
    return val;
  },
  set(v) {
    emit('update:modelValue', v);
  }
});

const listValue = computed(() => Array.isArray(innerValue.value) ? innerValue.value : []);

function addList() {
  const itemDefault = buildDefaultFromSchema(normalized.value.item || {});
  emit('update:modelValue', [...listValue.value, itemDefault]);
}

function removeList(idx) {
  const next = listValue.value.slice();
  next.splice(idx, 1);
  emit('update:modelValue', next);
}

function updateList(idx, val) {
  const next = listValue.value.slice();
  next[idx] = val;
  emit('update:modelValue', next);
}

function updateDict(key, val) {
  const base = props.modelValue && typeof props.modelValue === 'object' ? cloneInputs(props.modelValue) : {};
  base[key] = val;
  emit('update:modelValue', base);
}
 
 function updateTableItem(idx, key, val) {
   const nextList = cloneDeep(listValue.value);
   if (!nextList[idx]) nextList[idx] = {};
   nextList[idx][key] = val;
   emit('update:modelValue', nextList);
 }
</script>

<style scoped>
.input-field{display:flex;flex-direction:column;gap:6px;padding:6px 0;}
.label{font-size:13px;font-weight:600;color:var(--text-primary,#222);}
.req{color:#c00;margin-left:4px;}
.input,.select{width:100%;padding:8px;border:1px solid #d0d7de;border-radius:6px;}
.chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text-secondary,#555);}
.list-block{display:flex;flex-direction:column;gap:8px;}
.list-row{display:flex;align-items:flex-start;gap:8px;}
.dict-block{display:flex;flex-direction:column;gap:4px;border-left:2px solid #eef1f5;padding-left:8px;}
.desc{font-size:12px;color:var(--text-secondary,#666);}
.btn-ghost.small{border:1px solid #d0d7de;background:transparent;padding:4px 8px;border-radius:4px;cursor:pointer;}
.unknown{color:#a00;font-size:12px;}

/* Table Styles */
.table-block {
  overflow-x: auto;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 8px;
  background: #f9f9f9;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data-table th, .data-table td {
  border-bottom: 1px solid #eee;
  padding: 6px;
  text-align: left;
}
.data-table th {
  background: #f1f3f5;
  font-weight: 600;
  color: #333;
}
.table-input {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid #ccc;
  border-radius: 4px;
}
.action-col {
  width: 40px;
  text-align: center;
}
.remove-btn {
  color: #c00;
  border-color: #fdd;
  background: #fff0f0;
  font-weight: bold;
  width: 24px;
  height: 24px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.add-btn {
  margin-top: 8px;
}
.empty-state {
  text-align: center;
  color: #999;
  padding: 12px;
}
</style>
