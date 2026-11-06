//! Native maintenance guards. No filesystem or backend operation is authorized here.
//! The desktop controller supplies native-selected paths and random handle nonces;
//! core must still authenticate the current actor at actual execution time.

use std::{collections::HashMap, io::BufRead, path::PathBuf};

pub const CONTROL_FRAME_LIMIT: usize = 262_144;
pub const RESPONSE_FRAME_LIMIT: usize = 16_384;
const MAX_HANDLES: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GuardError {
    FrameTooLarge,
    FrameIncomplete,
    FrameInvalid,
    PipeFailed,
    HandleInvalid,
    HandleLimit,
    PathInvalid,
    ResponseMismatch,
    TransitionInvalid,
}

impl GuardError {
    pub fn code(self) -> &'static str {
        match self {
            Self::FrameTooLarge => "CONTROL_FRAME_TOO_LARGE",
            Self::FrameIncomplete => "CONTROL_FRAME_INCOMPLETE",
            Self::FrameInvalid => "CONTROL_FRAME_INVALID",
            Self::PipeFailed => "CONTROL_PIPE_FAILED",
            Self::HandleInvalid => "PICKER_HANDLE_INVALID",
            Self::HandleLimit => "PICKER_HANDLE_LIMIT",
            Self::PathInvalid => "PICKER_PATH_INVALID",
            Self::ResponseMismatch => "CONTROL_RESPONSE_MISMATCH",
            Self::TransitionInvalid => "TRANSITION_INVALID",
        }
    }
}

/// Read one UTF-8 line without ever allocating an unbounded line. The limit
/// includes LF (and CR for CRLF). A failure is terminal for this pipe: callers
/// must not discard the prefix and try to interpret the remaining bytes.
pub fn read_frame(reader: &mut impl BufRead, limit: usize) -> Result<Vec<u8>, GuardError> {
    let mut frame = Vec::with_capacity(limit.min(1024));
    loop {
        let available = reader.fill_buf().map_err(|_| GuardError::PipeFailed)?;
        if available.is_empty() {
            return Err(GuardError::FrameIncomplete);
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let count = newline.map_or(available.len(), |index| index + 1);
        if count > limit.saturating_sub(frame.len()) {
            return Err(GuardError::FrameTooLarge);
        }
        frame.extend_from_slice(&available[..count]);
        reader.consume(count);
        if newline.is_some() {
            if frame.len() == 1 || std::str::from_utf8(&frame).is_err() {
                return Err(GuardError::FrameInvalid);
            }
            return Ok(frame);
        }
        if frame.len() == limit {
            return Err(GuardError::FrameTooLarge);
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PickerPurpose {
    BackupDestination,
    MoveDestination,
    RestoreSource,
    RestoreDestination,
}

struct PickerBinding {
    purpose: PickerPurpose,
    operation_id: String,
    path: PathBuf,
}

/// Memory-only capabilities, never serialized to machine config or journal.
/// Register is called ONLY after a native dialog returns. The renderer cannot
/// supply the nonce or path. Nonces must be freshly generated 32 random bytes
/// encoded as lowercase hex by the desktop's existing CSPRNG dependency.
pub struct PickerHandles {
    generation: String,
    bindings: HashMap<String, PickerBinding>,
}

impl PickerHandles {
    pub fn new(generation: String) -> Self {
        Self {
            generation,
            bindings: HashMap::new(),
        }
    }

    pub fn register(
        &mut self,
        nonce: String,
        operation_id: String,
        purpose: PickerPurpose,
        path: PathBuf,
    ) -> Result<String, GuardError> {
        self.validate_selection(&nonce, &operation_id, &path)?;
        if self.bindings.len() >= MAX_HANDLES {
            return Err(GuardError::HandleLimit);
        }
        Ok(self.insert_binding(nonce, operation_id, purpose, path))
    }

    /// Replace one native purpose after a known successful dialog result. Validate
    /// first so cancellation/invalid selection never destroys the previous choice.
    pub fn replace_purpose(
        &mut self,
        nonce: String,
        operation_id: String,
        purpose: PickerPurpose,
        path: PathBuf,
    ) -> Result<String, GuardError> {
        self.validate_selection(&nonce, &operation_id, &path)?;
        let old = self
            .bindings
            .values()
            .filter(|binding| binding.operation_id == operation_id && binding.purpose == purpose)
            .count();
        if self.bindings.len() - old >= MAX_HANDLES {
            return Err(GuardError::HandleLimit);
        }
        self.bindings.retain(|_, binding| {
            binding.operation_id != operation_id || binding.purpose != purpose
        });
        Ok(self.insert_binding(nonce, operation_id, purpose, path))
    }

    pub fn generation(&self) -> &str {
        &self.generation
    }

    fn validate_selection(
        &self,
        nonce: &str,
        operation_id: &str,
        path: &std::path::Path,
    ) -> Result<(), GuardError> {
        if nonce.len() != 64
            || !nonce
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            || operation_id.is_empty()
            || operation_id.len() > 64
            || self.bindings.contains_key(nonce)
        {
            return Err(GuardError::HandleInvalid);
        }
        let text = path.to_str().ok_or(GuardError::PathInvalid)?;
        if !path.is_absolute()
            || text.contains('\0')
            || text.encode_utf16().count() > 32_767
            || text.len() > 98_304
        {
            return Err(GuardError::PathInvalid);
        }
        Ok(())
    }

    fn insert_binding(
        &mut self,
        nonce: String,
        operation_id: String,
        purpose: PickerPurpose,
        path: PathBuf,
    ) -> String {
        self.bindings.insert(
            nonce.clone(),
            PickerBinding {
                purpose,
                operation_id,
                path,
            },
        );
        nonce
    }

    /// Reusable for loss-of-ACK retry, but never rebindable to a different path,
    /// purpose, operation or process generation. Core also binds these in receipts.
    pub fn resolve(
        &self,
        handle: &str,
        generation: &str,
        operation_id: &str,
        purpose: PickerPurpose,
    ) -> Result<&std::path::Path, GuardError> {
        let binding = self.bindings.get(handle).ok_or(GuardError::HandleInvalid)?;
        if generation != self.generation
            || operation_id != binding.operation_id
            || purpose != binding.purpose
        {
            return Err(GuardError::HandleInvalid);
        }
        Ok(&binding.path)
    }

    pub fn revoke_operation(&mut self, operation_id: &str) {
        self.bindings
            .retain(|_, binding| binding.operation_id != operation_id);
    }
}

/// An exit alone (including exit 0) is not a clean maintenance close. Any pipe
/// error/timeout/force termination poisons this proof even if an ACK arrives late.
pub struct CloseProof {
    generation: String,
    operation_id: String,
    request_id: String,
    acknowledged: bool,
    exited_zero: bool,
    failed: bool,
}

impl CloseProof {
    pub fn new(generation: String, operation_id: String, request_id: String) -> Self {
        Self {
            generation,
            operation_id,
            request_id,
            acknowledged: false,
            exited_zero: false,
            failed: false,
        }
    }

    pub fn acknowledge(
        &mut self,
        generation: &str,
        operation_id: &str,
        request_id: &str,
        state: &str,
        success: bool,
    ) -> Result<(), GuardError> {
        if generation != self.generation
            || operation_id != self.operation_id
            || request_id != self.request_id
            || state != "CLOSED"
            || !success
        {
            self.failed = true;
            return Err(GuardError::ResponseMismatch);
        }
        self.acknowledged = true;
        Ok(())
    }

    pub fn observe_exit(&mut self, code: Option<i32>) {
        self.exited_zero = code == Some(0);
        self.failed |= !self.exited_zero;
    }

    pub fn mark_unclean(&mut self) {
        self.failed = true;
    }

    pub fn is_clean(&self) -> bool {
        self.acknowledged && self.exited_zero && !self.failed
    }

    pub fn matches_operation(&self, operation_id: &str) -> bool {
        self.operation_id == operation_id
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransitionPhase {
    Intent,
    Quiesced,
    Prepared,
    OldClosed,
    ConfigSwitched,
    CandidateDormant,
    ActivationDispatched,
    Active,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecoveryAdmission {
    SourceDormant,
    ReconcileConfig,
    CandidateDormant,
}

impl TransitionPhase {
    pub fn advance(self, next: Self) -> Result<Self, GuardError> {
        use TransitionPhase::*;
        if matches!(
            (self, next),
            (Intent, Quiesced)
                | (Quiesced, Prepared)
                | (Prepared, OldClosed)
                | (OldClosed, ConfigSwitched)
                | (ConfigSwitched, CandidateDormant)
                | (CandidateDormant, ActivationDispatched)
                | (ActivationDispatched, Active)
        ) {
            Ok(next)
        } else {
            Err(GuardError::TransitionInvalid)
        }
    }

    /// A journal never permits automatic active boot or fallback to the old root.
    /// Even ACTIVE needs reconciliation of the same target and activation receipt.
    pub fn recovery_admission(self) -> RecoveryAdmission {
        use TransitionPhase::*;
        match self {
            Intent | Quiesced | Prepared => RecoveryAdmission::SourceDormant,
            OldClosed => RecoveryAdmission::ReconcileConfig,
            ConfigSwitched | CandidateDormant | ActivationDispatched | Active => {
                RecoveryAdmission::CandidateDormant
            }
        }
    }
}
