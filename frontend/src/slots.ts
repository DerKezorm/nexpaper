/**
 * Places on the pages of the archive, the inbox and a document where other blocks plug in their own parts: the page
 * tools, joining, splitting and new versions (block B5), the export for the tax adviser (block B9). A place stays hidden
 * (no menu item, no empty box) while nothing is put into it. The pages take these as a prop, so a test can hand in its
 * own; the app fills `slots` once, where it starts.
 */
import type { ComponentType, ReactNode } from 'react'

import type { DocumentInfo, DocumentVersion, SearchFilters } from './api/client'
import { ExportDialog } from './components/ExportDialog'
import { MergeDialogSlot, NewVersionSlot, PageEditorSlot, SplitPanelSlot, VersionActionsSlot } from './components/pageToolSlots'

/** Turning, deleting and ordering pages; `onDone(true)` when a new version was saved. Shown instead of the pages. */
export type PageEditorProps = { document: DocumentInfo; onDone: (changed: boolean) => void }
/** Another document's pages added at the end of this one. */
export type MergeDialogProps = { document: DocumentInfo; onClose: () => void; onDone: () => void }
/** A new file as a new version of this document. */
export type NewVersionProps = { document: DocumentInfo; onClose: () => void; onDone: () => void }
/** What can be done with one version beside downloading it (bringing it back). Shown in its row of the list. */
export type VersionActionsProps = { document: DocumentInfo; version: DocumentVersion; canEdit: boolean; onDone: () => void }
/** A proposal to split a document in the inbox (a batch scan with blank sheets between the letters), shown in place of
 * the details when the document has one (`split_suggested`); `onDone` with the id of the first new part, or of the
 * document itself when it is kept as one. `back` stands above it (the way back to the list on a phone). */
export type SplitPanelProps = { document: DocumentInfo; onDone: (first?: number) => void; back?: ReactNode }
/** The export of the archive as it is filtered now: how many documents it shows and the sum of their amounts in cents
 * (shown until the server has counted), and a sentence for the page when the export was asked for. */
export type ExportDialogProps = { q: string; filters: SearchFilters; onClose: () => void; count: number; sum: number; say?: (text: string) => void }

export type Slots = {
  PageEditor?: ComponentType<PageEditorProps>
  MergeDialog?: ComponentType<MergeDialogProps>
  NewVersion?: ComponentType<NewVersionProps>
  VersionActions?: ComponentType<VersionActionsProps>
  SplitPanel?: ComponentType<SplitPanelProps>
  ExportDialog?: ComponentType<ExportDialogProps>
}

/** What the app plugs in: the export (B9) and the page tools (B5). */
export const slots: Slots = {
  ExportDialog,
  PageEditor: PageEditorSlot,
  MergeDialog: MergeDialogSlot,
  NewVersion: NewVersionSlot,
  VersionActions: VersionActionsSlot,
  SplitPanel: SplitPanelSlot,
}
