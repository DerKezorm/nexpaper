/**
 * The page tools in the places the pages of documents keep for them (`slots.ts`): each one hands the page's own way of
 * going on (reload, a sentence in the toast, another address) to the component of the page tools.
 */
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { inboxChanged, useSay } from '../lib/say'
import type { MergeDialogProps, NewVersionProps, PageEditorProps, SplitPanelProps, VersionActionsProps } from '../slots'
import { MergeDialog } from './MergeDialog'
import { PageEditor } from './PageEditor'
import { SplitPanel } from './SplitPanel'
import { UploadVersionDialog, VersionRowActions } from './VersionActions'

export function PageEditorSlot({ document, onDone }: PageEditorProps) {
  const { t } = useTranslation()
  const say = useSay()
  return (
    <PageEditor
      document={document}
      onDone={(saved) => onDone(saved !== null)}
      onSplit={(parts) => {
        inboxChanged()
        say(t('pagetools.editor.splitDone'), parts[0] ? `/eingang/${parts[0].id}` : '/eingang')
      }}
    />
  )
}

export function MergeDialogSlot({ document, onClose, onDone }: MergeDialogProps) {
  const say = useSay()
  const said = useRef('')
  return (
    <MergeDialog
      document={document}
      onClose={onClose}
      say={(text) => (said.current = text)}
      onMerged={(joined) => {
        onDone()
        // Another one may have been put first: the page goes to the document that stays.
        say(said.current, joined.id !== document.id ? `/dokument/${joined.id}` : undefined)
      }}
    />
  )
}

export function NewVersionSlot({ document, onClose, onDone }: NewVersionProps) {
  const say = useSay()
  return <UploadVersionDialog document={document} onClose={onClose} onUploaded={() => onDone()} say={(text) => say(text)} />
}

export function VersionActionsSlot({ document, version, canEdit, onDone }: VersionActionsProps) {
  const say = useSay()
  return <VersionRowActions document={document} version={version} canEdit={canEdit} onDone={() => onDone()} say={(text) => say(text)} />
}

export function SplitPanelSlot({ document, onDone, back }: SplitPanelProps) {
  const say = useSay()
  const said = useRef('')
  if (!document.split_suggested) return null
  // The page's `onDone` goes on to the next address; the sentence goes along to it.
  const done = (to: number | undefined) => {
    onDone(to)
    say(said.current, to ? `/eingang/${to}` : '/eingang')
  }
  return (
    <SplitPanel
      key={document.current_version}
      document={document}
      back={back}
      say={(text) => (said.current = text)}
      onSplit={(parts) => done(parts[0]?.id)}
      onKeep={() => done(document.id)}
    />
  )
}
