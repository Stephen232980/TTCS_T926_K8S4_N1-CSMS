// File.type comes from the filename on some platforms; send the actual format.
// The backend still decodes and validates dimensions, size and frame count.
export async function stationPhotoMime(file: File): Promise<string> {
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(new Error('Không đọc được tệp ảnh. Hãy chọn lại ảnh.'))
    reader.readAsArrayBuffer(file.slice(0, 12))
  })
  const signature = new Uint8Array(bytes)
  if (signature[0] === 255 && signature[1] === 216 && signature[2] === 255) return 'image/jpeg'
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((value, i) => signature[i] === value)) return 'image/png'
  const text = String.fromCharCode(...signature)
  if (text.startsWith('RIFF') && text.slice(8, 12) === 'WEBP') return 'image/webp'
  throw new Error('Nội dung tệp không phải ảnh JPEG, PNG hoặc WebP. Đổi tên đuôi tệp không chuyển đổi định dạng ảnh.')
}
