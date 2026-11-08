//! Explicit user Exit process contract shared by production and the headless harness.
use std::time::{Duration, Instant};

/// Deliberately exposes no kill operation: a failed tray Exit must retain a live child.
pub trait GracefulExitProcess {
    fn poll_exit(&mut self) -> Result<Option<bool>, ()>;
    fn request_exit(&mut self) -> Result<(), ()>;
}

pub struct ExitAttempt {
    pub terminal: bool,
    pub result: Result<(), &'static str>,
}

pub fn explicit_exit(process: &mut impl GracefulExitProcess, timeout: Duration) -> ExitAttempt {
    let stopped = |success| ExitAttempt {
        terminal: true,
        result: if success {
            Ok(())
        } else {
            Err("SHUTDOWN_FAILED")
        },
    };
    match process.poll_exit() {
        Ok(Some(false)) => return stopped(false),
        // An unexpected prior stop is reported once. The controller can discard
        // this observed-dead handle; the next explicit Exit can close the app.
        Ok(Some(true)) => {
            return ExitAttempt {
                terminal: true,
                result: Err("SIDECAR_NOT_RUNNING"),
            }
        }
        Err(()) => {
            return ExitAttempt {
                terminal: false,
                result: Err("SHUTDOWN_STATUS_UNKNOWN"),
            }
        }
        Ok(None) => {}
    }
    if process.request_exit().is_err() {
        return ExitAttempt {
            terminal: false,
            result: Err("SHUTDOWN_PIPE_FAILED"),
        };
    }
    let deadline = Instant::now() + timeout;
    loop {
        match process.poll_exit() {
            Ok(Some(success)) => return stopped(success),
            Err(()) => {
                return ExitAttempt {
                    terminal: false,
                    result: Err("SHUTDOWN_STATUS_UNKNOWN"),
                }
            }
            Ok(None) if Instant::now() >= deadline => {
                return ExitAttempt {
                    terminal: false,
                    result: Err("SHUTDOWN_TIMEOUT"),
                }
            }
            Ok(None) => std::thread::sleep(
                Duration::from_millis(25).min(deadline.saturating_duration_since(Instant::now())),
            ),
        }
    }
}

#[cfg(test)]
#[path = "../../tests/desktop/clean_shutdown.rs"]
mod clean_shutdown_tests;
