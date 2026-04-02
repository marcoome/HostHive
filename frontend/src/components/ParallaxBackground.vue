<template>
  <div class="parallax-container" ref="containerRef">
    <div
      v-for="shape in shapes"
      :key="shape.id"
      class="parallax-shape"
      :style="shape.style"
    />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'

const containerRef = ref(null)

const shapes = reactive([
  { id: 1, x: 10, y: 15, size: 300, depth: 0.02, style: {} },
  { id: 2, x: 80, y: 10, size: 200, depth: 0.03, style: {} },
  { id: 3, x: 60, y: 70, size: 350, depth: 0.015, style: {} },
  { id: 4, x: 25, y: 80, size: 180, depth: 0.025, style: {} },
  { id: 5, x: 90, y: 50, size: 250, depth: 0.02, style: {} },
  { id: 6, x: 45, y: 35, size: 150, depth: 0.035, style: {} },
  { id: 7, x: 5, y: 50, size: 220, depth: 0.018, style: {} },
  { id: 8, x: 70, y: 90, size: 280, depth: 0.022, style: {} }
])

let mouseX = 0
let mouseY = 0
let rafId = null

function updateShapeStyles() {
  shapes.forEach((shape) => {
    const offsetX = (mouseX - window.innerWidth / 2) * shape.depth
    const offsetY = (mouseY - window.innerHeight / 2) * shape.depth

    shape.style = {
      left: shape.x + '%',
      top: shape.y + '%',
      width: shape.size + 'px',
      height: shape.size + 'px',
      transform: `translate(${offsetX}px, ${offsetY}px)`,
      borderRadius: shape.id % 3 === 0 ? '30%' : '50%',
      filter: `blur(${shape.size > 250 ? 60 : 40}px)`
    }
  })
}

function onMouseMove(e) {
  mouseX = e.clientX
  mouseY = e.clientY
}

function loop() {
  updateShapeStyles()
  rafId = requestAnimationFrame(loop)
}

onMounted(() => {
  updateShapeStyles()
  window.addEventListener('mousemove', onMouseMove, { passive: true })
  rafId = requestAnimationFrame(loop)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove)
  if (rafId) cancelAnimationFrame(rafId)
})
</script>
