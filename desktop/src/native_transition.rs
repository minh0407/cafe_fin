//! Serial transition wiring, independent of Tauri and UI. Hosts supply only the
//! current verified child and freshly authenticated private core calls.
use crate::{
    control::{ControlCommand, MaintenanceReply, OperationState, ReplyStatus},
    maintenance_dto::{BootSession, MaintenanceKind, MaintenancePhase, RuntimeState},
    native_guards::CloseProof,
    native_journal::{JournalStore, NativeJournal},
    native_paths::{valid_digest, valid_uuid},
};
use std::path::Path;

pub type TransitionResult<T> = Result<T, String>;

/// Status completion never starts a Runtime. Core has freshly authenticated the
/// current caller; its artifact fields must match every saved opaque binding.
pub fn finish_from_status(
    store: &JournalStore,
    journal: &mut NativeJournal,
    reply: &MaintenanceReply,
    candidate: bool,
) -> TransitionResult<bool> {
    let pending = store.load()?;
    if candidate {
        candidate_binding(journal, reply)?;
        if reply.state != OperationState::Active || reply.runtime_state != RuntimeState::Active {
            return Ok(false);
        }
        if pending.is_some() {
            if journal.phase == MaintenancePhase::CandidateDormant {
                journal.phase = MaintenancePhase::ActivationDispatched;
                store.advance(journal)?;
            }
            if journal.phase != MaintenancePhase::Active {
                journal.phase = MaintenancePhase::Active;
                store.advance(journal)?;
            }
            store.finish(journal)?;
        }
        Ok(true)
    } else {
        let verified = prepared_binding(journal, reply)?;
        if pending.is_some() && journal.phase != MaintenancePhase::Prepared {
            if journal.phase == MaintenancePhase::Intent && journal.kind != MaintenanceKind::Backup
            {
                journal.phase = MaintenancePhase::Quiesced;
                store.advance(journal)?;
            }
            if matches!(
                journal.phase,
                MaintenancePhase::Intent | MaintenancePhase::Quiesced
            ) {
                store.advance(&verified)?;
                *journal = verified;
            }
        }
        if journal.kind == MaintenanceKind::Backup && reply.runtime_state == RuntimeState::Active {
            if pending.is_some() {
                store.finish(journal)?;
            }
            Ok(true)
        } else {
            Ok(false)
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum RootSide {
    Source,
    Candidate,
}

pub trait TransitionHost {
    fn verify_root(
        &mut self,
        journal: &NativeJournal,
        token: &str,
        side: RootSide,
    ) -> TransitionResult<()>;
    fn call(
        &mut self,
        command: ControlCommand,
        journal: &NativeJournal,
        token: &str,
    ) -> TransitionResult<MaintenanceReply>;
    fn close_source(
        &mut self,
        journal: &NativeJournal,
        token: &str,
    ) -> TransitionResult<CloseProof>;
    fn source_live(&mut self, journal: &NativeJournal) -> TransitionResult<bool>;
    fn attach_candidate(
        &mut self,
        journal: &NativeJournal,
    ) -> TransitionResult<Option<BootSession>>;
    fn start_candidate(&mut self, journal: &NativeJournal) -> TransitionResult<BootSession>;
}

pub struct RunOutcome {
    pub journal: NativeJournal,
    pub boot_session: Option<BootSession>,
    pub completed: bool,
}

pub fn core_ok(reply: &MaintenanceReply) -> TransitionResult<()> {
    if reply.status == ReplyStatus::Error {
        return Err(reply
            .code
            .clone()
            .unwrap_or_else(|| "MAINTENANCE_COMMAND_FAILED".into()));
    }
    Ok(())
}

pub fn prepared_binding(
    journal: &NativeJournal,
    reply: &MaintenanceReply,
) -> TransitionResult<NativeJournal> {
    core_ok(reply)?;
    if reply.state != OperationState::Prepared
        || reply.operation_id != journal.operation_id
        || reply.kind != Some(journal.kind)
        || reply.source_root_id.as_deref() != Some(journal.source_root_id.as_str())
        || reply.source_fingerprint.as_deref() != Some(journal.source_fingerprint.as_str())
    {
        return Err("MAINTENANCE_ARTIFACT_CONFLICT".into());
    }
    let candidate_id = reply
        .candidate_root_id
        .as_ref()
        .filter(|value| valid_uuid(value))
        .ok_or("MAINTENANCE_ARTIFACT_CONFLICT")?;
    let candidate_fp = reply
        .candidate_fingerprint
        .as_ref()
        .filter(|value| valid_digest(value))
        .ok_or("MAINTENANCE_ARTIFACT_CONFLICT")?;
    let hash = reply
        .manifest_sha256
        .as_ref()
        .filter(|value| valid_digest(value))
        .ok_or("MAINTENANCE_ARTIFACT_CONFLICT")?;
    for (old, new) in [
        (&journal.candidate_root_id, candidate_id),
        (&journal.candidate_fingerprint, candidate_fp),
        (&journal.manifest_sha256, hash),
    ] {
        if old.as_ref().is_some_and(|old| old != new) {
            return Err("MAINTENANCE_ARTIFACT_CONFLICT".into());
        }
    }
    let mut prepared = journal.clone();
    prepared.phase = MaintenancePhase::Prepared;
    prepared.candidate_root_id = Some(candidate_id.clone());
    prepared.candidate_fingerprint = Some(candidate_fp.clone());
    prepared.manifest_sha256 = Some(hash.clone());
    prepared.validate()?;
    Ok(prepared)
}

pub fn candidate_binding(
    journal: &NativeJournal,
    reply: &MaintenanceReply,
) -> TransitionResult<()> {
    core_ok(reply)?;
    if reply.operation_id != journal.operation_id
        || reply.kind != Some(journal.kind)
        || reply.source_root_id.as_deref() != Some(journal.source_root_id.as_str())
        || reply.source_fingerprint.as_deref() != Some(journal.source_fingerprint.as_str())
        || reply.candidate_root_id != journal.candidate_root_id
        || reply.candidate_fingerprint != journal.candidate_fingerprint
        || reply.manifest_sha256 != journal.manifest_sha256
    {
        return Err("ACTIVATION_BINDING_INVALID".into());
    }
    Ok(())
}

fn candidate_boot(
    journal: &NativeJournal,
    boot: &BootSession,
    dormant_required: bool,
) -> TransitionResult<()> {
    if boot.maintenance_protocol != Some(1)
        || !boot.generation.as_deref().is_some_and(valid_uuid)
        || boot.runtime_state.is_none()
        || (dormant_required && boot.runtime_state != Some(RuntimeState::Dormant))
        || Path::new(&boot.data_root).canonicalize().ok() != journal.destination.canonicalize().ok()
        || !journal.destination.is_dir()
    {
        return Err("MAINTENANCE_RECOVERY_HELD".into());
    }
    Ok(())
}

/// Continue exactly the saved operation. No activation is performed by Run.
pub fn run<H: TransitionHost>(
    host: &mut H,
    store: &JournalStore,
    mut journal: NativeJournal,
    token: &str,
) -> TransitionResult<RunOutcome> {
    journal.validate()?;
    if store.load()?.as_ref() != Some(&journal) {
        return Err("JOURNAL_CONFLICT".into());
    }
    loop {
        match journal.phase {
            MaintenancePhase::Selecting => return Err("JOURNAL_INVALID".into()),
            MaintenancePhase::Intent if journal.kind != MaintenanceKind::Backup => {
                host.verify_root(&journal, token, RootSide::Source)?;
                let reply = host.call(ControlCommand::Quiesce, &journal, token)?;
                core_ok(&reply)?;
                if reply.state != OperationState::Quiesced
                    || reply.runtime_state != RuntimeState::Quiesced
                {
                    return Err("MAINTENANCE_RECOVERY_HELD".into());
                }
                journal.phase = MaintenancePhase::Quiesced;
                store.advance(&journal)?;
            }
            MaintenancePhase::Intent | MaintenancePhase::Quiesced => {
                host.verify_root(&journal, token, RootSide::Source)?;
                let reply = host.call(ControlCommand::Prepare, &journal, token)?;
                let prepared = prepared_binding(&journal, &reply)?;
                if journal.kind != MaintenanceKind::Backup
                    && reply.runtime_state != RuntimeState::Quiesced
                {
                    return Err("MAINTENANCE_RECOVERY_HELD".into());
                }
                store.advance(&prepared)?;
                journal = prepared;
            }
            MaintenancePhase::Prepared => {
                if !host.source_live(&journal)? {
                    return Err("MAINTENANCE_RECOVERY_HELD".into());
                }
                host.verify_root(&journal, token, RootSide::Source)?;
                let status = host.call(ControlCommand::Status, &journal, token)?;
                let verified = prepared_binding(&journal, &status)?;
                if verified != journal {
                    return Err("MAINTENANCE_ARTIFACT_CONFLICT".into());
                }
                if journal.kind == MaintenanceKind::Backup {
                    if status.runtime_state != RuntimeState::Active {
                        return Err("MAINTENANCE_RECOVERY_HELD".into());
                    }
                    store.finish(&journal)?;
                    return Ok(RunOutcome {
                        journal,
                        boot_session: None,
                        completed: true,
                    });
                }
                if !matches!(
                    status.runtime_state,
                    RuntimeState::Quiesced | RuntimeState::Dormant
                ) {
                    return Err("MAINTENANCE_RECOVERY_HELD".into());
                }
                let proof = host.close_source(&journal, token)?;
                journal.phase = MaintenancePhase::OldClosed;
                store.record_closed(&journal, &proof)?;
            }
            MaintenancePhase::OldClosed => {
                // A cold-recovery dormant source is a NEW live process. Its
                // previous generation's closure record does not close this child.
                if host.source_live(&journal)? {
                    host.verify_root(&journal, token, RootSide::Source)?;
                    let status = host.call(ControlCommand::Status, &journal, token)?;
                    prepared_binding(&journal, &status)?;
                    if !matches!(
                        status.runtime_state,
                        RuntimeState::Dormant | RuntimeState::Quiesced
                    ) {
                        return Err("MAINTENANCE_RECOVERY_HELD".into());
                    }
                    let proof = host.close_source(&journal, token)?;
                    store.record_closed(&journal, &proof)?;
                }
                store.switch_candidate(&journal)?;
                journal.phase = MaintenancePhase::ConfigSwitched;
                store.advance(&journal)?;
            }
            MaintenancePhase::ConfigSwitched => {
                let mut boot = match host.attach_candidate(&journal)? {
                    Some(boot) => boot,
                    None => host.start_candidate(&journal)?,
                };
                candidate_boot(&journal, &boot, true)?;
                journal.phase = MaintenancePhase::CandidateDormant;
                store.advance(&journal)?;
                boot.pending_transition = Some(journal.summary(true));
                return Ok(RunOutcome {
                    journal,
                    boot_session: Some(boot),
                    completed: false,
                });
            }
            MaintenancePhase::CandidateDormant
            | MaintenancePhase::ActivationDispatched
            | MaintenancePhase::Active => {
                let mut boot = match host.attach_candidate(&journal)? {
                    Some(boot) => boot,
                    None => host.start_candidate(&journal)?,
                };
                candidate_boot(&journal, &boot, false)?;
                boot.pending_transition = Some(journal.summary(true));
                return Ok(RunOutcome {
                    journal,
                    boot_session: Some(boot),
                    completed: false,
                });
            }
        }
    }
}

/// Explicit fresh-target activation only. Status/Run never call this implicitly.
pub fn activate<H: TransitionHost>(
    host: &mut H,
    store: &JournalStore,
    mut journal: NativeJournal,
    token: &str,
) -> TransitionResult<RunOutcome> {
    if !matches!(
        journal.phase,
        MaintenancePhase::CandidateDormant
            | MaintenancePhase::ActivationDispatched
            | MaintenancePhase::Active
    ) || journal.kind == MaintenanceKind::Backup
        || store.load()?.as_ref() != Some(&journal)
    {
        return Err("MAINTENANCE_RECOVERY_HELD".into());
    }
    host.verify_root(&journal, token, RootSide::Candidate)?;
    let status = host.call(ControlCommand::Status, &journal, token)?;
    candidate_binding(&journal, &status)?;
    if status.state == OperationState::ReplayRequired {
        return Err("ACTIVATION_REPLAY_REQUIRED".into());
    }
    if status.state != OperationState::Active || status.runtime_state != RuntimeState::Active {
        if status.state != OperationState::Dormant || status.runtime_state != RuntimeState::Dormant
        {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        if journal.phase == MaintenancePhase::CandidateDormant {
            journal.phase = MaintenancePhase::ActivationDispatched;
            store.advance(&journal)?;
        }
        let active = host.call(ControlCommand::Activate, &journal, token)?;
        candidate_binding(&journal, &active)?;
        if active.state != OperationState::Active || active.runtime_state != RuntimeState::Active {
            return Err("ACTIVATION_REPLAY_REQUIRED".into());
        }
    }
    if journal.phase != MaintenancePhase::Active {
        journal.phase = MaintenancePhase::Active;
        store.advance(&journal)?;
    }
    store.finish(&journal)?;
    Ok(RunOutcome {
        journal,
        boot_session: None,
        completed: true,
    })
}
