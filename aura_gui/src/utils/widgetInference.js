// UI控件自动推断引擎
// 根据 schema 定义智能选择最合适的 UI 控件

/**
 * 解析 list<type> 语法，提取内部类型
 */
function parseListType(typeStr) {
  if (!typeStr) return 'string';
  const match = typeStr.match(/^list<(.+)>$/);
  return match ? match[1] : 'string';
}

/**
 * 判断是否为固定维度的矩阵 (list<list<*>>)
 */
function isFixedDimension(schema) {
  return schema.min != null &&
         schema.max != null &&
         schema.min === schema.max &&
         schema.item?.min != null &&
         schema.item?.max != null &&
         schema.item.min === schema.item.max;
}

/**
 * 判断是否为列表类型
 */
function isList(type) {
  return type === 'list' || type?.startsWith('list<');
}

/**
 * UI控件自动推断引擎
 * @param {Object} schema - 规范化后的参数schema
 * @returns {Object} UI配置 { widget, ...options }
 */
export function inferWidget(schema) {
  const { type, enum: options, ui, min, max, properties, item } = schema;

  // 1. 用户显式指定 → 直接使用
  if (ui?.widget) {
    return { ...ui };
  }

  // 2. 判断是否为列表类型（决定单选/复选）
  const isListType = isList(type);
  const hasEnum = Array.isArray(options) && options.length > 0;
  const optionCount = hasEnum ? options.length : 0;

  // ========== 复选逻辑 ==========
  if (isListType) {
    if (!hasEnum) {
      // 无enum → 自由输入列表
      const itemType = parseListType(type);

      if (itemType === 'string') {
        return { widget: 'tag-input' }; // Tag输入框
      }
      if (itemType === 'number') {
        return { widget: 'dynamic-list', itemWidget: 'number' };
      }
      if (itemType === 'dict' || item?.properties) {
        // list<dict> → 检查是否适合表格
        const props = item?.properties || {};
        const propKeys = Object.keys(props);
        if (propKeys.length > 0 && propKeys.length <= 6) {
          // 字段少 → 表格
          const allSimple = propKeys.every(k => {
            const pType = props[k].type || 'string';
            return ['string', 'number', 'boolean'].includes(pType) || props[k].enum;
          });
          if (allSimple) {
            return { widget: 'table' };
          }
        }
        // 字段多或复杂 → 卡片
        return { widget: 'card-list' };
      }
      if (itemType?.startsWith('list<')) {
        // list<list<*>>
        if (isFixedDimension(schema)) {
          return { widget: 'matrix' }; // 固定维度矩阵
        }
        return { widget: 'grouped-list' }; // 动态分组
      }
      return { widget: 'dynamic-list' };
    }

    // 有enum → 多选
    if (optionCount <= 8) {
      return { widget: 'checkbox', layout: 'grid' };
    }
    if (optionCount <= 20) {
      return { widget: 'checkbox', columns: 2 };
    }
    return {
      widget: 'multiselect',
      searchable: optionCount > 30
    };
  }

  // ========== 单选逻辑 ==========
  if (type === 'boolean') {
    return { widget: 'checkbox' };
  }

  if (type === 'number') {
    if (!hasEnum) {
      // 有明确范围且范围适中 → 滑块
      if (min != null && max != null) {
        const range = max - min;
        if (range > 0 && range <= 1000) {
          return { widget: 'slider', showInput: true };
        }
      }
      return { widget: 'input', type: 'number' };
    }

    // 有enum → 单选
    if (optionCount <= 5) {
      return { widget: 'radio', layout: 'horizontal' };
    }
    return { widget: 'select' };
  }

  if (type === 'dict') {
    if (properties && Object.keys(properties).length > 0) {
      return { widget: 'fieldset' }; // 预定义字段组
    }
    return { widget: 'key-value-editor' }; // 动态键值对
  }

  // string 或默认
  if (!hasEnum) {
    return { widget: 'input', type: 'text' };
  }

  // string + enum → 单选
  if (optionCount <= 5) {
    return { widget: 'radio', layout: 'vertical' };
  }
  if (optionCount <= 15) {
    return { widget: 'select' };
  }
  return { widget: 'select', searchable: true };
}

/**
 * 获取数量限制提示文本
 */
export function getCountHintText(selectedCount, min, max) {
  if (min != null && max != null && min === max) {
    return `请选择 ${min} 项（已选 ${selectedCount}/${min}）`;
  }

  if (min != null && max != null) {
    return `请选择 ${min}-${max} 项（已选 ${selectedCount}）`;
  }

  if (max != null) {
    return `最多选择 ${max} 项（已选 ${selectedCount}/${max}）`;
  }

  if (min != null) {
    return `至少选择 ${min} 项（已选 ${selectedCount}）`;
  }

  return `已选择 ${selectedCount} 项`;
}

/**
 * 判断数量限制状态
 */
export function getCountHintStatus(selectedCount, min, max) {
  if (min != null && selectedCount < min) {
    return 'error'; // 未达下限
  }

  if (max != null && selectedCount >= max) {
    return 'full'; // 已达上限
  }

  return 'normal';
}
