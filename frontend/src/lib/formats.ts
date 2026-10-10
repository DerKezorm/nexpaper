/**
 * The kinds of file the server takes, as a file dialog wants them (the `accept` of every field that chooses documents:
 * Upload, the quick upload, the camera page, a new version). One list, so that no field offers what the server
 * turns away. The server still decides by the content of the file (a dialog can be set to "all files", and a name can lie).
 */
const TYPES = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/tiff',
  'image/heic',
  'image/heif',
  'image/webp',
  'image/avif',
  'application/xml',
  'text/xml',
]
const ENDINGS = ['.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.heif', '.webp', '.avif', '.xml']

export const ACCEPT = [...TYPES, ...ENDINGS].join(',')
/** The pictures only, for the choice from the photo library. */
export const ACCEPT_PHOTOS = TYPES.filter((type) => type.startsWith('image/')).join(',')
