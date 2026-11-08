//! Deterministic process/transport seam checks, not frozen-sidecar/GUI acceptance.
use super::*;
use std::collections::VecDeque;

struct Peer {
    observations: VecDeque<Result<Option<bool>, ()>>,
    send_fails: bool,
    sent: usize,
}
impl Peer {
    fn new(observations: impl IntoIterator<Item = Result<Option<bool>, ()>>) -> Self {
        Self {
            observations: observations.into_iter().collect(),
            send_fails: false,
            sent: 0,
        }
    }
}
impl GracefulExitProcess for Peer {
    fn poll_exit(&mut self) -> Result<Option<bool>, ()> {
        self.observations.pop_front().unwrap_or(Ok(None))
    }
    fn request_exit(&mut self) -> Result<(), ()> {
        self.sent += 1;
        if self.send_fails {
            Err(())
        } else {
            Ok(())
        }
    }
}

#[test]
fn clean_exit_requires_a_request_and_observed_zero_exit() {
    let mut peer = Peer::new([Ok(None), Ok(None), Ok(Some(true))]);
    let result = explicit_exit(&mut peer, Duration::from_secs(1));
    assert!(result.terminal);
    assert_eq!(result.result, Ok(()));
    assert_eq!(peer.sent, 1);
}

#[test]
fn failed_send_keeps_the_process_handle_available_for_recovery() {
    let mut peer = Peer::new([Ok(None)]);
    peer.send_fails = true;
    let result = explicit_exit(&mut peer, Duration::ZERO);
    assert!(!result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_PIPE_FAILED"));
    assert_eq!(peer.sent, 1);
}

#[test]
fn timeout_does_not_claim_exit_or_discard_the_live_process() {
    let mut peer = Peer::new([Ok(None)]);
    let result = explicit_exit(&mut peer, Duration::from_millis(2));
    assert!(!result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_TIMEOUT"));
    assert_eq!(peer.sent, 1);
    // A late clean exit can be observed on a later user attempt; it is warned
    // once rather than being confused with this timed-out request succeeding.
    peer.observations.push_back(Ok(Some(true)));
    let later = explicit_exit(&mut peer, Duration::ZERO);
    assert!(later.terminal);
    assert_eq!(later.result, Err("SIDECAR_NOT_RUNNING"));
    assert_eq!(peer.sent, 1);
}

#[test]
fn nonzero_exit_is_terminal_but_never_reported_as_success() {
    let mut peer = Peer::new([Ok(None), Ok(Some(false))]);
    let result = explicit_exit(&mut peer, Duration::ZERO);
    assert!(result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_FAILED"));
}

#[test]
fn an_already_dead_child_is_clearable_after_one_warning_without_sending() {
    let mut peer = Peer::new([Ok(Some(true))]);
    let result = explicit_exit(&mut peer, Duration::ZERO);
    assert!(result.terminal);
    assert_eq!(result.result, Err("SIDECAR_NOT_RUNNING"));
    assert_eq!(peer.sent, 0);
}

#[test]
fn observation_failures_never_release_an_unconfirmed_live_handle() {
    let mut before_send = Peer::new([Err(())]);
    let result = explicit_exit(&mut before_send, Duration::ZERO);
    assert!(!result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_STATUS_UNKNOWN"));
    assert_eq!(before_send.sent, 0);
    let mut after_send = Peer::new([Ok(None), Err(())]);
    let result = explicit_exit(&mut after_send, Duration::ZERO);
    assert!(!result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_STATUS_UNKNOWN"));
    assert_eq!(after_send.sent, 1);
}

struct ProcessPeer {
    child: std::process::Child,
}
impl GracefulExitProcess for ProcessPeer {
    fn poll_exit(&mut self) -> Result<Option<bool>, ()> {
        self.child
            .try_wait()
            .map(|status| status.map(|status| status.success()))
            .map_err(|_| ())
    }
    fn request_exit(&mut self) -> Result<(), ()> {
        use std::io::Write;
        self.child
            .stdin
            .as_mut()
            .ok_or(())?
            .write_all(b"shutdown\n")
            .map_err(|_| ())
    }
}
impl Drop for ProcessPeer {
    fn drop(&mut self) {
        // Fixture cleanup, not product shutdown behavior. Closing this synthetic
        // peer's stdin ends its loop, including when it deliberately ignored Exit.
        self.child.stdin.take();
        let deadline = Instant::now() + Duration::from_secs(2);
        while matches!(self.child.try_wait(), Ok(None)) && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(5));
        }
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

fn process_peer(ignore_exit: bool) -> ProcessPeer {
    let module = module_path!().split_once("::").unwrap().1;
    let mut command = std::process::Command::new(std::env::current_exe().unwrap());
    command
        .args([
            "--ignored",
            "--exact",
            &format!("{module}::transport_child_fixture"),
        ])
        .env(
            "CAFE_FIN_SHUTDOWN_FIXTURE_IGNORE",
            if ignore_exit { "1" } else { "0" },
        )
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    ProcessPeer {
        child: command.spawn().expect("synthetic test peer must start"),
    }
}

#[test]
fn real_process_observes_graceful_pipe_shutdown() {
    let mut process = process_peer(false);
    let result = explicit_exit(&mut process, Duration::from_secs(2));
    assert!(result.terminal);
    assert_eq!(result.result, Ok(()));
    assert!(process.child.try_wait().unwrap().unwrap().success());
}

#[test]
fn real_process_ignoring_shutdown_remains_alive_after_timeout() {
    let mut process = process_peer(true);
    let result = explicit_exit(&mut process, Duration::from_millis(10));
    assert!(!result.terminal);
    assert_eq!(result.result, Err("SHUTDOWN_TIMEOUT"));
    assert!(process.child.try_wait().unwrap().is_none());
}

#[test]
#[ignore = "synthetic subprocess entrypoint, called only by process seam tests"]
fn transport_child_fixture() {
    assert!(std::env::var("CAFE_FIN_SHUTDOWN_FIXTURE_IGNORE").is_ok());
    let ignore = std::env::var("CAFE_FIN_SHUTDOWN_FIXTURE_IGNORE").unwrap() == "1";
    let mut line = String::new();
    loop {
        line.clear();
        if std::io::stdin().read_line(&mut line).unwrap() == 0 || (!ignore && line == "shutdown\n")
        {
            return;
        }
    }
}
