import assert from 'node:assert/strict'
import test from 'node:test'
import { extractBilibiliVideoId, extractDouyinVideoId, platformKind, videoPlayer } from './mediaLinks.js'

test('extracts canonical Douyin and Bilibili identifiers', () => {
  assert.equal(extractDouyinVideoId('https://www.douyin.com/video/7338851683520220451'), '7338851683520220451')
  assert.equal(extractDouyinVideoId('https://www.douyin.com/player/video?vid=7338851683520220451'), '7338851683520220451')
  assert.equal(extractBilibiliVideoId('https://www.bilibili.com/video/BV1xx411c7mD'), 'BV1xx411c7mD')
})

test('uses a direct media URL for in-workbench Douyin playback', () => {
  const player = videoPlayer({
    platform: '抖音',
    source_url: 'https://www.douyin.com/video/7338851683520220451',
    media_url: 'https://example-video.douyinvod.com/stream/video.mp4',
  })
  assert.deepEqual(player, {
    type: 'video',
    src: 'https://example-video.douyinvod.com/stream/video.mp4',
    platform: 'douyin',
  })
})

test('does not pretend that a Douyin webpage is embeddable', () => {
  const item = {
    platform: '抖音',
    source_url: 'https://www.douyin.com/video/7338851683520220451',
    media_url: 'https://www.douyin.com/video/7338851683520220451',
  }
  assert.equal(platformKind(item), 'douyin')
  assert.equal(videoPlayer(item), null)
})

test('keeps Bilibili playback in the existing official player', () => {
  assert.deepEqual(videoPlayer({ source_url: 'https://www.bilibili.com/video/BV1xx411c7mD' }), {
    type: 'iframe',
    src: 'https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&high_quality=1',
    platform: 'bilibili',
  })
})
