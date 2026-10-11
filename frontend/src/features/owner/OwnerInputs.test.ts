import { describe, expect, it } from 'vitest'
import { OwnerApiError } from './ownerApi'
import { stationPhotoMime } from './stationPhoto'

describe('owner input failures', () => {
  it('keeps missing-driver errors distinct from photo errors', () => {
    expect(new OwnerApiError(422, 'Không tìm thấy tài xế đang hoạt động với email này.', '/charging/cards').message).toContain('Tài xế cần có tài khoản')
    expect(new OwnerApiError(422, [], '/charging/cards').message).not.toContain('ảnh')
    expect(new OwnerApiError(409, 'Thẻ đã được khai báo.', '/charging/cards').message).toContain('Mã thẻ đã được cấp')
  })
  it('explains image dimensions separately from file size', () => {
    expect(new OwnerApiError(422, 'station_photo_dimensions_too_large', '/stations/s/photo').message).toContain('16 triệu điểm ảnh')
    expect(new OwnerApiError(422, 'station_photo_too_large', '/stations/s/photo').message).toContain('20 MB')
  })
  it.each([
    [new Uint8Array([255, 216, 255, 224]), 'image/jpeg'],
    [new Uint8Array([137,80,78,71,13,10,26,10]), 'image/png'],
    [new TextEncoder().encode('RIFF0000WEBP'), 'image/webp'],
  ])('uses actual file bytes instead of an incorrect extension', async (bytes, mime) => {
    const file = new File([bytes], 'incorrect.png', { type: 'image/png' })
    expect(await stationPhotoMime(file)).toBe(mime)
  })
  it('rejects a renamed non-image before sending it', async () => {
    await expect(stationPhotoMime(new File(['not a photo'], 'renamed.jpg', { type: 'image/jpeg' }))).rejects.toThrow('Đổi tên đuôi tệp')
  })
})
