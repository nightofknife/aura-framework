// Utility helpers for task input schema normalization and defaults.

const inferEnumType = (values) => {
  if (!Array.isArray(values) || values.length === 0) return null;
  const kinds = new Set();
  values.forEach((val) => {
    if (typeof val === 'boolean') {
      kinds.add('boolean');
    } else if (typeof val === 'number') {
      kinds.add('number');
    } else if (typeof val === 'string') {
      kinds.add('string');
    } else {
      kinds.add('other');
    }
  });
  if (kinds.size !== 1 || kinds.has('other')) return null;
  return [...kinds][0];
};

export function normalizeInputSchema(schema = {}) {
  if (typeof schema !== 'object' || !schema) return { type: 'string' };
  const normalized = { ...schema };
  if (normalized.enum === undefined && normalized.options !== undefined) {
    normalized.enum = normalized.options;
  }
  if (normalized.enum !== undefined) {
    normalized.enum = normalized.enum || [];
  }

  let typeRaw = normalized.type;
  if (typeRaw === undefined || typeRaw === null || typeRaw === '') {
    typeRaw = inferEnumType(normalized.enum) || 'string';
  } else {
    typeRaw = String(typeRaw).toLowerCase();
  }
  if (typeRaw === 'enum') {
    typeRaw = inferEnumType(normalized.enum) || 'string';
  }

  const listMatch = typeRaw.match(/^list<(.+)>$/);
  if (listMatch) {
    normalized.type = 'list';
    const itemSchema = normalized.item || normalized.items || { type: listMatch[1] };
    normalized.item = normalizeInputSchema(itemSchema);
  } else {
    if (typeRaw === 'array') typeRaw = 'list';
    if (typeRaw === 'object') typeRaw = 'dict';
    const allowed = new Set(['string', 'number', 'boolean', 'list', 'dict']);
    normalized.type = allowed.has(typeRaw) ? typeRaw : 'string';
    if (normalized.type === 'list') {
      const itemSchema = normalized.item || normalized.items;
      if (itemSchema) normalized.item = normalizeInputSchema(itemSchema);
    }
    if (normalized.type === 'dict') {
      const props = {};
      Object.entries(normalized.properties || {}).forEach(([k, v]) => {
        if (v && typeof v === 'object') props[k] = normalizeInputSchema(v);
      });
      normalized.properties = props;
    }
  }
  return normalized;
}

export function buildDefaultFromSchema(schema = {}) {
  const s = normalizeInputSchema(schema);
  if (Object.prototype.hasOwnProperty.call(s, 'default')) {
    return cloneDeep(s.default);
  }
  if (Array.isArray(s.enum) && s.enum.length) {
    return cloneDeep(s.enum[0]);
  }
  if (s.type === 'list') {
    return [];
  }
  if (s.type === 'dict') {
    const obj = {};
    Object.entries(s.properties || {}).forEach(([k, v]) => {
      const val = buildDefaultFromSchema(v);
      if (val !== undefined) obj[k] = val;
    });
    return obj;
  }
  if (s.type === 'boolean') return false;
  if (s.type === 'number') return null;
  return '';
}

export const cloneDeep = (val) => {
  if (val === undefined) return undefined;
  if (val === null) return null;
  try {
    return JSON.parse(JSON.stringify(val));
  } catch (e) {
    return val;
  }
};

export const cloneInputs = cloneDeep;
