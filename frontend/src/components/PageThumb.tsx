/**
 * One page of a document as a picture from the server (the small size), as the page tools show it:
 * (fetched only near the screen, through the one queue of `lib/pictures.ts` that honours `Retry-After`), turned as the
 * editor has it before it is saved. Each version has its own address, so a new version never shows an old picture.
 */
import { pagePicture } from '../api/pagetools'
import { PagePicture } from './PagePicture'

type Props = {
  document: number
  version: number
  /** Counted from 1. */
  page: number
  /** Degrees clockwise, as the page is shown (the editor turns it before it is saved). */
  turn?: number
  className?: string
}

/** A page turned on its side is shrunk to fit its place (the width of a sheet of A4 over its height). */
const SIDEWAYS = 0.707

export function PageThumb({ document, version, page, turn = 0, className = '' }: Props) {
  const url = pagePicture(document, version, page)
  return (
    <div
      data-src={url}
      className={`rounded-[3px] transition-transform ${className}`}
      style={turn ? { transform: `rotate(${turn}deg)${Math.abs(turn / 90) % 2 === 1 ? ` scale(${SIDEWAYS})` : ''}` } : undefined}
    >
      <PagePicture src={url} alt="" margin="300px" />
    </div>
  )
}
