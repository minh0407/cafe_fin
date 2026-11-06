//! Read-only reattachment to an already verified child. This interface has no
//! spawn, stop, initialize, activation, copy or config-write operation.
use crate::{
    maintenance_dto::{BootSession, PendingTransition},
    native_paths::valid_uuid,
};

pub trait ExistingChild {
    fn generation(&self) -> &str;
    fn verified(&self) -> bool;
    fn check_alive(&mut self) -> Result<(), &'static str>;
    fn check_health(&mut self) -> Result<(), &'static str>;
    fn session(&self) -> &BootSession;
}

/// Caller holds the native state mutex throughout this call, validates the
/// journal/config/root binding first and never falls back to spawn on an error.
/// None is returned ONLY when no child and no pending transition exist.
pub fn attach_existing<C: ExistingChild>(
    child: Option<&mut C>,
    pending: Option<&PendingTransition>,
    initialize: bool,
) -> Result<Option<BootSession>, &'static str> {
    if pending.is_some() && initialize {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    let Some(child) = child else {
        return if pending.is_some() {
            Err("MAINTENANCE_RECOVERY_HELD")
        } else {
            Ok(None)
        };
    };
    if initialize {
        return Err("ATTACH_INITIALIZE_DENIED");
    }
    if !child.verified() {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    let generation = child.generation().to_owned();
    if !valid_uuid(&generation) {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    child
        .check_alive()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    child
        .check_health()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    child
        .check_alive()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    if !child.verified() || child.generation() != generation {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    let session = child.session();
    if session.protocol_version != 1 {
        return Err("MAINTENANCE_RECOVERY_HELD");
    }
    match session.maintenance_protocol {
        Some(1)
            if session.generation.as_deref() == Some(generation.as_str())
                && session.runtime_state.is_some() => {}
        None if pending.is_none() && session.generation.is_none() => {} // legacy first-start lost ACK only
        _ => return Err("MAINTENANCE_RECOVERY_HELD"),
    }
    let mut session = session.clone();
    // Journal is the current transition binding, not a cached pre-Run session.
    session.pending_transition = pending.cloned();
    Ok(Some(session))
}
