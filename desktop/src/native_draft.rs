//! One memory-only SELECTING draft. Replacing it is not persistent cancellation.
//! Caller holds the native state mutex; no renderer-provided busy/uncertain flag
//! is accepted. Journal existence/errors and native latches are authoritative.
use crate::{
    maintenance_dto::{
        MaintenanceKind, MaintenancePhase, MaintenanceView, RuntimeState, SelectionPurpose,
    },
    native_guards::{PickerHandles, PickerPurpose},
    native_journal::JournalStore,
    native_paths::{check_local_path, derive_destination, valid_uuid},
};
use std::path::Path;

struct Draft {
    operation_id: String,
    generation: String,
    kind: MaintenanceKind,
    destination: Option<String>,
    backup_source: Option<String>,
    uncertain: bool,
    intent_attempted: bool,
    dispatched: bool,
}

/// Opaque native correlation ticket, not a renderer DTO or path capability.
#[derive(Clone)]
pub struct SelectionTicket {
    sequence: u64,
    operation_id: String,
    generation: String,
    purpose: SelectionPurpose,
}

#[derive(Default)]
pub struct DraftSlot {
    current: Option<Draft>,
    selection: Option<SelectionTicket>,
    sequence: u64,
}

impl DraftSlot {
    pub fn begin(
        &mut self,
        operation_id: String,
        generation: String,
        kind: MaintenanceKind,
        journal: &JournalStore,
        handles: &mut PickerHandles,
    ) -> Result<(), &'static str> {
        no_journal(journal)?;
        if !valid_uuid(&operation_id)
            || !valid_uuid(&generation)
            || generation != handles.generation()
        {
            return Err("DRAFT_IDENTITY_INVALID");
        }
        if self.selection.is_some() {
            return Err("DRAFT_BUSY");
        }
        if let Some(old) = &self.current {
            if old.uncertain || old.intent_attempted || old.dispatched {
                return Err("MAINTENANCE_RECOVERY_HELD");
            }
            if old.generation != generation {
                return Err("DRAFT_GENERATION_STALE");
            }
            if old.operation_id == operation_id {
                return Err("DRAFT_IDENTITY_CONFLICT");
            }
            handles.revoke_operation(&old.operation_id);
        }
        self.current = Some(Draft {
            operation_id,
            generation,
            kind,
            destination: None,
            backup_source: None,
            uncertain: false,
            intent_attempted: false,
            dispatched: false,
        });
        Ok(())
    }

    pub fn start_selection(
        &mut self,
        operation_id: &str,
        generation: &str,
        purpose: SelectionPurpose,
        journal: &JournalStore,
    ) -> Result<SelectionTicket, &'static str> {
        no_journal(journal)?;
        let draft = self.current.as_ref().ok_or("DRAFT_NOT_FOUND")?;
        selecting(draft, operation_id, generation)?;
        if self.selection.is_some() {
            return Err("DRAFT_BUSY");
        }
        if purpose == SelectionPurpose::BackupSource && draft.kind != MaintenanceKind::Restore {
            return Err("PICKER_PURPOSE_INVALID");
        }
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or("DRAFT_SEQUENCE_EXHAUSTED")?;
        let ticket = SelectionTicket {
            sequence: self.sequence,
            operation_id: operation_id.into(),
            generation: generation.into(),
            purpose,
        };
        self.selection = Some(ticket.clone());
        Ok(ticket)
    }

    /// None means native dialog cancellation: keep the prior known selection.
    /// An error in an actual path result also keeps the old purpose binding.
    pub fn finish_selection(
        &mut self,
        ticket: SelectionTicket,
        selected: Option<&Path>,
        nonce: String,
        journal: &JournalStore,
        handles: &mut PickerHandles,
    ) -> Result<(), &'static str> {
        let active = self.selection.as_ref().ok_or("PICKER_RESULT_STALE")?;
        if active.sequence != ticket.sequence
            || active.operation_id != ticket.operation_id
            || active.generation != ticket.generation
            || active.purpose != ticket.purpose
        {
            return Err("PICKER_RESULT_STALE");
        }
        let draft = self.current.as_mut().ok_or("DRAFT_NOT_FOUND")?;
        selecting(draft, &ticket.operation_id, &ticket.generation)?;
        if handles.generation() != ticket.generation {
            return Err("DRAFT_GENERATION_STALE");
        }
        if no_journal(journal).is_err() {
            draft.uncertain = true;
            self.selection = None;
            return Err("MAINTENANCE_RECOVERY_HELD");
        }
        self.selection = None;
        let Some(selected) = selected else {
            return Ok(());
        };
        let path = match ticket.purpose {
            SelectionPurpose::Destination => derive_destination(
                selected,
                &draft.operation_id,
                draft.kind == MaintenanceKind::Backup,
            )?,
            SelectionPurpose::BackupSource => {
                check_local_path(selected)?;
                if !selected.is_dir() {
                    return Err("BACKUP_SOURCE_UNAVAILABLE");
                }
                selected
                    .canonicalize()
                    .map_err(|_| "BACKUP_SOURCE_UNAVAILABLE")?
            }
        };
        let purpose = binding_purpose(draft.kind, ticket.purpose)?;
        let handle = handles
            .replace_purpose(nonce, draft.operation_id.clone(), purpose, path)
            .map_err(|error| error.code())?;
        match ticket.purpose {
            SelectionPurpose::Destination => draft.destination = Some(handle),
            SelectionPurpose::BackupSource => draft.backup_source = Some(handle),
        }
        Ok(())
    }

    /// Set before any uncertain intent-write outcome. There is deliberately no
    /// public reset/abandon: failed persistence must be reconciled, not discarded.
    pub fn mark_intent_attempted(&mut self, operation_id: &str) -> Result<(), &'static str> {
        if self.selection.is_some() {
            return Err("DRAFT_BUSY");
        }
        let draft = self.current.as_mut().ok_or("DRAFT_NOT_FOUND")?;
        if draft.operation_id != operation_id {
            return Err("DRAFT_IDENTITY_CONFLICT");
        }
        if draft.uncertain || draft.dispatched {
            return Err("MAINTENANCE_RECOVERY_HELD");
        }
        draft.intent_attempted = true;
        Ok(())
    }

    pub fn mark_dispatched(&mut self, operation_id: &str) -> Result<(), &'static str> {
        if self.selection.is_some() {
            return Err("DRAFT_BUSY");
        }
        let draft = self.current.as_mut().ok_or("DRAFT_NOT_FOUND")?;
        if draft.operation_id != operation_id {
            return Err("DRAFT_IDENTITY_CONFLICT");
        }
        draft.dispatched = true;
        Ok(())
    }

    pub fn mark_uncertain(&mut self, operation_id: &str) -> Result<(), &'static str> {
        let draft = self.current.as_mut().ok_or("DRAFT_NOT_FOUND")?;
        if draft.operation_id != operation_id {
            return Err("DRAFT_IDENTITY_CONFLICT");
        }
        draft.uncertain = true;
        self.selection = None;
        Ok(())
    }

    pub fn view(
        &self,
        journal: &JournalStore,
        handles: &PickerHandles,
        runtime_state: Option<RuntimeState>,
    ) -> Result<MaintenanceView, &'static str> {
        no_journal(journal)?;
        let draft = self.current.as_ref().ok_or("DRAFT_NOT_FOUND")?;
        if draft.generation != handles.generation() {
            return Err("DRAFT_GENERATION_STALE");
        }
        let path_display =
            |handle: &Option<String>, purpose| -> Result<Option<String>, &'static str> {
                handle
                    .as_ref()
                    .map(|handle| {
                        handles
                            .resolve(handle, &draft.generation, &draft.operation_id, purpose)
                            .map(|path| path.to_string_lossy().into_owned())
                            .map_err(|error| error.code())
                    })
                    .transpose()
            };
        let destination_display = path_display(
            &draft.destination,
            binding_purpose(draft.kind, SelectionPurpose::Destination)?,
        )?;
        let backup_source_display =
            path_display(&draft.backup_source, PickerPurpose::RestoreSource)?;
        let held = draft.uncertain || draft.intent_attempted || draft.dispatched;
        let ready = !held
            && self.selection.is_none()
            && destination_display.is_some()
            && (draft.kind != MaintenanceKind::Restore || backup_source_display.is_some());
        Ok(MaintenanceView {
            operation_id: draft.operation_id.clone(),
            kind: draft.kind,
            phase: MaintenancePhase::Selecting,
            recovery_required: held,
            generation: draft.generation.clone(),
            runtime_state,
            destination_display,
            backup_source_display,
            ready,
            can_activate: false,
        })
    }

    pub fn operation_id(&self) -> Option<&str> {
        self.current
            .as_ref()
            .map(|draft| draft.operation_id.as_str())
    }
}

fn no_journal(journal: &JournalStore) -> Result<(), &'static str> {
    match journal.load() {
        Ok(None) => Ok(()),
        Ok(Some(_)) => Err("MAINTENANCE_PENDING"),
        Err(_) => Err("MAINTENANCE_RECOVERY_HELD"),
    }
}

fn selecting(draft: &Draft, operation_id: &str, generation: &str) -> Result<(), &'static str> {
    if draft.operation_id != operation_id || draft.generation != generation {
        return Err("DRAFT_GENERATION_STALE");
    }
    if draft.uncertain || draft.intent_attempted || draft.dispatched {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    Ok(())
}

fn binding_purpose(
    kind: MaintenanceKind,
    purpose: SelectionPurpose,
) -> Result<PickerPurpose, &'static str> {
    match (kind, purpose) {
        (MaintenanceKind::Backup, SelectionPurpose::Destination) => {
            Ok(PickerPurpose::BackupDestination)
        }
        (MaintenanceKind::Move, SelectionPurpose::Destination) => {
            Ok(PickerPurpose::MoveDestination)
        }
        (MaintenanceKind::Restore, SelectionPurpose::Destination) => {
            Ok(PickerPurpose::RestoreDestination)
        }
        (MaintenanceKind::Restore, SelectionPurpose::BackupSource) => {
            Ok(PickerPurpose::RestoreSource)
        }
        _ => Err("PICKER_PURPOSE_INVALID"),
    }
}
