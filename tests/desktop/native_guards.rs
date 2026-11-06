// Compile the production primitives directly, without Tauri/browser mocks or
// adding a second dependency tree. This does not test native GUI or installation.
#[path = "../../desktop/src/native_guards.rs"]
mod native_guards;

use native_guards::*;
use std::{
    io::{BufReader, Cursor},
    path::PathBuf,
};

fn native_path() -> PathBuf {
    std::env::temp_dir().join("Cafe Fin dữ liệu")
}
fn handles() -> PickerHandles {
    PickerHandles::new("generation-a".into())
}
fn nonce() -> String {
    "ab".repeat(32)
}
fn proof() -> CloseProof {
    CloseProof::new(
        "generation-a".into(),
        "operation-a".into(),
        "request-a".into(),
    )
}
fn ack(proof: &mut CloseProof) {
    proof
        .acknowledge("generation-a", "operation-a", "request-a", "CLOSED", true)
        .unwrap();
}

#[test]
fn fragmented_unicode_frames_preserve_correlated_next_frame() {
    let input = "{\"name\":\"Cà phê\"}\r\n{\"state\":\"CLOSED\"}\n";
    let mut reader = BufReader::with_capacity(1, Cursor::new(input.as_bytes()));
    assert_eq!(
        read_frame(&mut reader, 100).unwrap(),
        "{\"name\":\"Cà phê\"}\r\n".as_bytes()
    );
    assert_eq!(
        read_frame(&mut reader, 100).unwrap(),
        b"{\"state\":\"CLOSED\"}\n"
    );
}

#[test]
fn hard_byte_limit_includes_newline() {
    let frame = [vec![b'x'; RESPONSE_FRAME_LIMIT - 1], vec![b'\n']].concat();
    assert_eq!(
        read_frame(&mut Cursor::new(&frame), RESPONSE_FRAME_LIMIT)
            .unwrap()
            .len(),
        RESPONSE_FRAME_LIMIT
    );
    let too_long = [vec![b'x'; RESPONSE_FRAME_LIMIT], vec![b'\n']].concat();
    assert_eq!(
        read_frame(&mut Cursor::new(too_long), RESPONSE_FRAME_LIMIT),
        Err(GuardError::FrameTooLarge)
    );
    assert_eq!(CONTROL_FRAME_LIMIT, 262_144);
}

#[test]
fn rejects_oversized_nonterminated_input_without_reading_it_all() {
    let source = Cursor::new(vec![b'x'; CONTROL_FRAME_LIMIT * 2]);
    let mut reader = BufReader::with_capacity(4096, source);
    assert_eq!(
        read_frame(&mut reader, CONTROL_FRAME_LIMIT),
        Err(GuardError::FrameTooLarge)
    );
    assert!(reader.into_inner().position() <= CONTROL_FRAME_LIMIT as u64);
}

#[test]
fn rejects_truncation_invalid_utf8_empty_and_io_error_without_echo() {
    for frame in [b"secret-token-path".as_slice(), b"".as_slice()] {
        assert_eq!(
            read_frame(&mut Cursor::new(frame), 100),
            Err(GuardError::FrameIncomplete)
        );
    }
    for frame in [b"\xff\n".as_slice(), b"\n".as_slice()] {
        assert_eq!(
            read_frame(&mut Cursor::new(frame), 100),
            Err(GuardError::FrameInvalid)
        );
    }
    struct Broken;
    impl std::io::Read for Broken {
        fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("private-path-secret"))
        }
    }
    let result = read_frame(&mut BufReader::new(Broken), 100).unwrap_err();
    assert_eq!(result.code(), "CONTROL_PIPE_FAILED");
}

#[test]
fn picker_binding_cannot_change_purpose_operation_or_generation() {
    let mut vault = handles();
    let path = native_path();
    let handle = vault
        .register(
            nonce(),
            "operation-a".into(),
            PickerPurpose::RestoreSource,
            path.clone(),
        )
        .unwrap();
    for (generation, operation, purpose) in [
        ("generation-b", "operation-a", PickerPurpose::RestoreSource),
        ("generation-a", "operation-b", PickerPurpose::RestoreSource),
        (
            "generation-a",
            "operation-a",
            PickerPurpose::RestoreDestination,
        ),
    ] {
        assert_eq!(
            vault.resolve(&handle, generation, operation, purpose),
            Err(GuardError::HandleInvalid)
        );
    }
    for _ in 0..2 {
        assert_eq!(
            vault
                .resolve(
                    &handle,
                    "generation-a",
                    "operation-a",
                    PickerPurpose::RestoreSource
                )
                .unwrap(),
            path
        );
    }
    assert_eq!(
        vault.register(
            handle.clone(),
            "operation-b".into(),
            PickerPurpose::MoveDestination,
            native_path()
        ),
        Err(GuardError::HandleInvalid)
    );
    vault.revoke_operation("operation-a");
    assert_eq!(
        vault.resolve(
            &handle,
            "generation-a",
            "operation-a",
            PickerPurpose::RestoreSource
        ),
        Err(GuardError::HandleInvalid)
    );
}

#[test]
fn picker_memory_bounded_and_relative_non_unicode_or_nul_paths_refused() {
    let mut vault = handles();
    for path in [
        PathBuf::from("relative/path"),
        native_path().join("bad\0path"),
        native_path().join("é".repeat(32_768)),
        native_path().join("😀".repeat(16_384)),
    ] {
        assert_eq!(
            vault.register(nonce(), "op".into(), PickerPurpose::BackupDestination, path),
            Err(GuardError::PathInvalid)
        );
    }
    assert_eq!(
        vault.register(
            "not-random".into(),
            "op".into(),
            PickerPurpose::BackupDestination,
            native_path()
        ),
        Err(GuardError::HandleInvalid)
    );
    for i in 0..8 {
        vault
            .register(
                format!("{i:064x}"),
                "op".into(),
                PickerPurpose::BackupDestination,
                native_path(),
            )
            .unwrap();
    }
    assert_eq!(
        vault.register(
            nonce(),
            "op".into(),
            PickerPurpose::BackupDestination,
            native_path()
        ),
        Err(GuardError::HandleLimit)
    );
    vault.revoke_operation("op");
    assert!(vault
        .register(
            nonce(),
            "op".into(),
            PickerPurpose::BackupDestination,
            native_path()
        )
        .is_ok());
}

#[test]
#[cfg(windows)]
fn picker_refuses_unpaired_utf16_instead_of_lossy_path_alias() {
    use std::{ffi::OsString, os::windows::ffi::OsStringExt};
    let path = native_path().join(OsString::from_wide(&[0xd800]));
    assert_eq!(
        handles().register(nonce(), "op".into(), PickerPurpose::RestoreSource, path),
        Err(GuardError::PathInvalid)
    );
}

#[test]
fn repeated_purpose_reselection_revokes_old_handles_and_retains_other_purpose() {
    let mut vault = handles();
    assert_eq!(vault.generation(), "generation-a");
    let source = format!("{:064x}", 1);
    vault
        .register(
            source.clone(),
            "operation-a".into(),
            PickerPurpose::RestoreSource,
            native_path(),
        )
        .unwrap();
    let mut previous: Option<String> = None;
    for value in 2..102 {
        let nonce = format!("{value:064x}");
        vault
            .replace_purpose(
                nonce.clone(),
                "operation-a".into(),
                PickerPurpose::RestoreDestination,
                native_path().join(format!("choice-{value}")),
            )
            .unwrap();
        if let Some(old) = previous {
            assert_eq!(
                vault.resolve(
                    &old,
                    "generation-a",
                    "operation-a",
                    PickerPurpose::RestoreDestination
                ),
                Err(GuardError::HandleInvalid)
            );
        }
        assert!(vault
            .resolve(
                &source,
                "generation-a",
                "operation-a",
                PickerPurpose::RestoreSource
            )
            .is_ok());
        previous = Some(nonce);
    }
    let old = previous.unwrap();
    assert_eq!(
        vault.replace_purpose(
            "invalid".into(),
            "operation-a".into(),
            PickerPurpose::RestoreDestination,
            native_path()
        ),
        Err(GuardError::HandleInvalid)
    );
    assert!(vault
        .resolve(
            &old,
            "generation-a",
            "operation-a",
            PickerPurpose::RestoreDestination
        )
        .is_ok());
    assert_eq!(
        vault.replace_purpose(
            old.clone(),
            "operation-a".into(),
            PickerPurpose::RestoreDestination,
            native_path()
        ),
        Err(GuardError::HandleInvalid)
    );
    vault.revoke_operation("operation-a");
    assert_eq!(
        vault.resolve(
            &source,
            "generation-a",
            "operation-a",
            PickerPurpose::RestoreSource
        ),
        Err(GuardError::HandleInvalid)
    );
}

#[test]
fn clean_close_requires_both_matching_ack_and_zero_exit_in_either_order() {
    let mut first = proof();
    ack(&mut first);
    assert!(!first.is_clean());
    first.observe_exit(Some(0));
    assert!(first.is_clean());
    assert!(first.matches_operation("operation-a"));
    assert!(!first.matches_operation("operation-b"));
    let mut second = proof();
    second.observe_exit(Some(0));
    assert!(!second.is_clean());
    ack(&mut second);
    assert!(second.is_clean());
}

#[test]
fn stale_ack_shutdown_error_pipe_loss_timeout_and_kill_never_prove_clean_close() {
    for (generation, operation, request, state, success) in [
        ("old", "operation-a", "request-a", "CLOSED", true),
        ("generation-a", "other", "request-a", "CLOSED", true),
        ("generation-a", "operation-a", "old", "CLOSED", true),
        (
            "generation-a",
            "operation-a",
            "request-a",
            "SHUTDOWN_FAILED",
            false,
        ),
    ] {
        let mut p = proof();
        assert_eq!(
            p.acknowledge(generation, operation, request, state, success),
            Err(GuardError::ResponseMismatch)
        );
        p.observe_exit(Some(0));
        ack(&mut p);
        assert!(!p.is_clean());
    }
    for code in [None, Some(1), Some(86)] {
        let mut p = proof();
        ack(&mut p);
        p.observe_exit(code);
        assert!(!p.is_clean());
    }
    let mut p = proof();
    p.mark_unclean();
    ack(&mut p);
    p.observe_exit(Some(0));
    assert!(!p.is_clean());
}

#[test]
fn every_journal_recovery_is_dormant_and_never_skips_close_or_activation_intent() {
    use TransitionPhase::*;
    let phases = [
        Intent,
        Quiesced,
        Prepared,
        OldClosed,
        ConfigSwitched,
        CandidateDormant,
        ActivationDispatched,
        Active,
    ];
    for window in phases.windows(2) {
        assert_eq!(window[0].advance(window[1]), Ok(window[1]));
    }
    assert_eq!(
        Prepared.advance(ConfigSwitched),
        Err(GuardError::TransitionInvalid)
    );
    assert_eq!(
        CandidateDormant.advance(Active),
        Err(GuardError::TransitionInvalid)
    );
    for phase in phases {
        assert_eq!(phase.advance(Intent), Err(GuardError::TransitionInvalid));
        match phase {
            Intent | Quiesced | Prepared => {
                assert_eq!(phase.recovery_admission(), RecoveryAdmission::SourceDormant)
            }
            OldClosed => assert_eq!(
                phase.recovery_admission(),
                RecoveryAdmission::ReconcileConfig
            ),
            _ => assert_eq!(
                phase.recovery_admission(),
                RecoveryAdmission::CandidateDormant
            ),
        }
    }
}
