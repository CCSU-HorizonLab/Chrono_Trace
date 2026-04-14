import test from 'node:test'
import assert from 'node:assert/strict'

import { getAvatarInitial, normalizeAvatarSrc, shouldRenderAvatar } from '../src/utils/avatar.js'

test('normalizeAvatarSrc trims usable urls', () => {
  assert.equal(normalizeAvatarSrc('  https://cdn.example/avatar.jpg  '), 'https://cdn.example/avatar.jpg')
  assert.equal(normalizeAvatarSrc('   '), '')
  assert.equal(normalizeAvatarSrc(null), '')
})

test('shouldRenderAvatar only allows non-empty urls without prior load errors', () => {
  assert.equal(shouldRenderAvatar('https://cdn.example/avatar.jpg', false), true)
  assert.equal(shouldRenderAvatar('https://cdn.example/avatar.jpg', true), false)
  assert.equal(shouldRenderAvatar('', false), false)
  assert.equal(shouldRenderAvatar('   ', false), false)
})

test('getAvatarInitial falls back cleanly for empty names', () => {
  assert.equal(getAvatarInitial('Chrono'), 'C')
  assert.equal(getAvatarInitial('张三'), '张')
  assert.equal(getAvatarInitial(''), '?')
  assert.equal(getAvatarInitial(null), '?')
})
