<script setup lang="ts">
import { t } from '../i18n'
</script>
<template>
  <details class="figure-export"><summary>{{ t('Export figure') }}</summary><div class="export-options"><slot /></div></details>
</template>
<style scoped>
.figure-export { position: relative; margin: 0; }
.figure-export > summary { margin: 0; padding: 7px 11px; border: 1px solid #d4dce3; border-radius: 5px; color: #445967; font-size: 12px; cursor: pointer; }
.export-options { position: absolute; right: 0; top: calc(100% + 5px); z-index: 5; display: flex; flex-direction: column; gap: 6px; min-width: 190px; padding: 8px; border: 1px solid #d4dce3; border-radius: 6px; background: white; box-shadow: 0 4px 16px #24374614; }
</style>
