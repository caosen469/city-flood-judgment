<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    sev?: 's' | 'w' | 'd' | 'n' // success / warning / danger / neutral(info)
    size?: 'default' | 'small' | 'large'
    effect?: 'light' | 'dark' | 'plain'
  }>(),
  { sev: 'n', size: 'default', effect: 'light' },
)

const type = computed(() => {
  switch (props.sev) {
    case 's':
      return 'success'
    case 'w':
      return 'warning'
    case 'd':
      return 'danger'
    default:
      return 'info'
  }
})
</script>

<template>
  <el-tag :type="type" :size="size" :effect="effect" class="sev-tag">
    <slot />
  </el-tag>
</template>

<style scoped>
.sev-tag {
  font-family: -apple-system, "PingFang SC", sans-serif;
  letter-spacing: 0;
}
</style>
