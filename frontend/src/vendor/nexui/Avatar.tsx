/**
 * A person's picture: their own (`src`), or one letter on a colour where there is none or it does not load. Letter and
 * hue come from `avatarPlaceholder` of the module `konten` (the same in every app, on the server and on the iPhone); the
 * kit only paints them: the hue as a number, saturation, lightness and the letter's colour from the app's variables
 * (`--nexui-avatar-saturation`, `--nexui-avatar-lightness`, `--nexui-avatar-text`). Always round; 32 px in a row of the
 * account list, 48 px at the head of the dialog "Manage". The picture says nothing to a reader: the name stands next to
 * it.
 */
import { useState, type CSSProperties } from 'react'

import { AVATAR, AVATAR_LETTER } from './styles'

export function Avatar({
  src,
  letter,
  hue,
  size = 32,
  testId,
}: {
  /** The address of the person's own picture; empty or missing: the letter. */
  src?: string | null
  /** The letter of the placeholder (`avatarPlaceholder(name).letter`). */
  letter: string
  /** The hue of the placeholder, 0 to 359 (`avatarPlaceholder(name).hue`). */
  hue: number
  /** 32 in a row, 48 at the head of a dialog. */
  size?: 32 | 48
  testId?: string
}) {
  const [failed, setFailed] = useState<string | null>(null)
  const box = size === 48 ? 'h-12 w-12' : 'h-8 w-8'
  if (src && failed !== src) {
    return (
      <img
        src={src}
        alt=""
        aria-hidden
        width={size}
        height={size}
        onError={() => setFailed(src)}
        className={`${AVATAR} ${box} object-cover`}
        data-avatar="picture"
        data-testid={testId}
      />
    )
  }
  const turn = ((Math.round(hue) % 360) + 360) % 360
  return (
    <span
      aria-hidden
      className={`${AVATAR} ${AVATAR_LETTER} ${box} ${size === 48 ? 'text-lg leading-7' : 'text-sm leading-5'}`}
      style={{ '--nexui-avatar-hue': String(turn) } as CSSProperties}
      data-avatar="letter"
      data-hue={turn}
      data-testid={testId}
    >
      {letter}
    </span>
  )
}
