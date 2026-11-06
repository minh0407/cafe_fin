//! One bounded stdout reader and one serial private-pipe request at a time.
//! A timed-out request stays pending; its operation/destination cannot be changed
//! or a second request sent into a stream whose first ACK has not been resolved.
use crate::{
    maintenance_dto::{MaintenanceKind, RuntimeState},
    native_guards::{read_frame, CONTROL_FRAME_LIMIT, RESPONSE_FRAME_LIMIT},
    native_paths::{valid_digest, valid_uuid},
};
use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    sync::mpsc::{self, Receiver, RecvTimeoutError, TryRecvError},
    thread::{self, JoinHandle},
    time::Duration,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum ControlCommand {
    #[serde(rename = "maintenance.quiesce")]
    Quiesce,
    #[serde(rename = "maintenance.prepare")]
    Prepare,
    #[serde(rename = "maintenance.status")]
    Status,
    #[serde(rename = "maintenance.close")]
    Close,
    #[serde(rename = "maintenance.activate")]
    Activate,
    #[serde(rename = "reports.authorize_open")]
    ReportsAuthorizeOpen,
}

// No Debug or Deserialize: private trusted-native input, not a renderer command.
#[derive(Serialize)]
pub struct ControlRequest<'a> {
    pub maintenance_protocol: u32,
    pub request_id: &'a str,
    pub generation: &'a str,
    pub command: ControlCommand,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub operation_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin_generation: Option<&'a str>,
    pub access_token: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<MaintenanceKind>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub destination: Option<&'a Path>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backup_source: Option<&'a Path>,
}

impl ControlRequest<'_> {
    pub fn encode(&self) -> Result<Vec<u8>, &'static str> {
        if self.maintenance_protocol != 1
            || !valid_uuid(self.request_id)
            || !valid_uuid(self.generation)
            || self.access_token.is_empty()
            || self.access_token.len() > 4096
            || self.access_token.chars().any(char::is_control)
        {
            return Err("CONTROL_REQUEST_INVALID");
        }
        if self.command == ControlCommand::ReportsAuthorizeOpen {
            if self.operation_id.is_some()
                || self.origin_generation.is_some()
                || self.kind.is_some()
                || self.destination.is_some()
                || self.backup_source.is_some()
            {
                return Err("CONTROL_REQUEST_INVALID");
            }
        } else if !self.operation_id.is_some_and(valid_uuid)
            || !self.origin_generation.is_some_and(valid_uuid)
        {
            return Err("CONTROL_REQUEST_INVALID");
        }
        if self.command == ControlCommand::Prepare {
            if self.kind.is_none()
                || self.destination.is_none()
                || (self.kind == Some(MaintenanceKind::Restore)) != self.backup_source.is_some()
            {
                return Err("CONTROL_REQUEST_INVALID");
            }
        } else if self.kind.is_some() || self.destination.is_some() || self.backup_source.is_some()
        {
            return Err("CONTROL_REQUEST_INVALID");
        }
        for path in [self.destination, self.backup_source].into_iter().flatten() {
            let text = path.to_str().ok_or("CONTROL_PATH_INVALID")?;
            if !path.is_absolute()
                || text.contains('\0')
                || text.encode_utf16().count() > 32767
                || text.len() > 98304
            {
                return Err("CONTROL_PATH_INVALID");
            }
        }
        let mut bytes = serde_json::to_vec(self).map_err(|_| "CONTROL_REQUEST_INVALID")?;
        bytes.push(b'\n');
        if bytes.len() > CONTROL_FRAME_LIMIT {
            return Err("CONTROL_FRAME_TOO_LARGE");
        }
        Ok(bytes)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ReplyStatus {
    Ok,
    Error,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MaintenanceReply {
    pub maintenance_protocol: u32,
    pub request_id: String,
    pub generation: String,
    pub operation_id: String,
    pub status: ReplyStatus,
    pub state: RuntimeState,
    // At quiesce/status before intent, kind may not yet be known to core. No
    // prepared/cutover action may proceed without exact expected kind matching.
    #[serde(deserialize_with = "required_kind")]
    pub kind: Option<MaintenanceKind>,
    pub source_root_id: Option<String>,
    pub candidate_root_id: Option<String>,
    pub manifest_sha256: Option<String>,
    pub source_fingerprint: Option<String>,
    pub candidate_fingerprint: Option<String>,
    pub code: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReportsReply {
    pub maintenance_protocol: u32,
    pub request_id: String,
    pub generation: String,
    pub allowed: bool,
    pub root_id: Option<String>,
    pub status: Option<ReplyStatus>,
    pub code: Option<String>,
}

pub enum ControlReply {
    Maintenance(MaintenanceReply),
    Reports(ReportsReply),
}

fn required_kind<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<MaintenanceKind>, D::Error> {
    Option::deserialize(deserializer)
}

// No token/path retained in the correlation slot.
struct Expected {
    request_id: String,
    generation: String,
    operation_id: Option<String>,
    command: ControlCommand,
    kind: Option<MaintenanceKind>,
}

enum ReaderEvent {
    Frame(Vec<u8>),
    Failed(&'static str),
    Eof,
}

pub struct ControlPipe<W: Write> {
    writer: W,
    receiver: Receiver<ReaderEvent>,
    reader: Option<JoinHandle<()>>,
    pending: Option<Expected>,
    broken: bool,
    boot_received: bool,
    reader_terminal: bool,
}

impl<W: Write> ControlPipe<W> {
    pub fn new<R: Read + Send + 'static>(writer: W, stdout: R) -> Self {
        let (sender, receiver) = mpsc::sync_channel(1);
        let reader = thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                match reader.fill_buf() {
                    Ok([]) => {
                        let _ = sender.send(ReaderEvent::Eof);
                        break;
                    }
                    Err(_) => {
                        let _ = sender.send(ReaderEvent::Failed("CONTROL_PIPE_FAILED"));
                        break;
                    }
                    _ => {}
                }
                match read_frame(&mut reader, RESPONSE_FRAME_LIMIT) {
                    Ok(frame) => {
                        if sender.send(ReaderEvent::Frame(frame)).is_err() {
                            break;
                        }
                    }
                    Err(error) => {
                        let _ = sender.send(ReaderEvent::Failed(error.code()));
                        break;
                    }
                }
            }
        });
        Self {
            writer,
            receiver,
            reader: Some(reader),
            pending: None,
            broken: false,
            boot_received: false,
            reader_terminal: false,
        }
    }

    /// First frame only, before a control request. Decode/validate with the boot
    /// schema in the desktop bootstrap. This replaces the post-handshake sink.
    pub fn boot_frame(&mut self, timeout: Duration) -> Result<Vec<u8>, &'static str> {
        if self.boot_received || self.pending.is_some() || self.broken {
            return Err("CONTROL_STATE_INVALID");
        }
        let frame = self.receive_frame(timeout)?;
        self.boot_received = true;
        Ok(frame)
    }

    pub fn send(&mut self, request: &ControlRequest<'_>) -> Result<(), &'static str> {
        if self.broken {
            return Err("CONTROL_PIPE_FAILED");
        }
        if !self.boot_received {
            return Err("CONTROL_STATE_INVALID");
        }
        if self.pending.is_some() {
            return Err("CONTROL_REQUEST_PENDING");
        }
        let bytes = request.encode()?;
        self.pending = Some(Expected {
            request_id: request.request_id.into(),
            generation: request.generation.into(),
            operation_id: request.operation_id.map(str::to_owned),
            command: request.command,
            kind: request.kind,
        });
        if self
            .writer
            .write_all(&bytes)
            .and_then(|_| self.writer.flush())
            .is_err()
        {
            self.broken = true;
            return Err("CONTROL_PIPE_FAILED");
        }
        Ok(())
    }

    /// On timeout, caller retains journal and can wait for the SAME pending ACK.
    /// A late ACK is not permission to replay a new operation with changed inputs.
    pub fn receive(&mut self, timeout: Duration) -> Result<ControlReply, &'static str> {
        if self.pending.is_none() {
            return Err("CONTROL_STATE_INVALID");
        }
        let frame = self.receive_frame(timeout)?;
        let expected = self.pending.as_ref().ok_or("CONTROL_STATE_INVALID")?;
        let result = decode_reply(&frame, expected);
        if result.is_err() {
            self.broken = true;
        } else {
            self.pending = None;
        }
        result
    }

    fn receive_frame(&mut self, timeout: Duration) -> Result<Vec<u8>, &'static str> {
        if self.broken {
            return Err("CONTROL_PIPE_FAILED");
        }
        match self.receiver.recv_timeout(timeout) {
            Ok(ReaderEvent::Frame(frame)) => Ok(frame),
            Ok(ReaderEvent::Failed(code)) => {
                self.broken = true;
                self.reader_terminal = true;
                Err(code)
            }
            Ok(ReaderEvent::Eof) => {
                self.broken = true;
                self.reader_terminal = true;
                Err("CONTROL_PIPE_CLOSED")
            }
            Err(RecvTimeoutError::Timeout) => Err("CONTROL_ACK_PENDING"),
            _ => {
                self.broken = true;
                Err("CONTROL_PIPE_FAILED")
            }
        }
    }

    /// Call after observed child exit. Do not block forever joining an alive
    /// stdout producer. Reader EOF is never substituted for process exit 0.
    pub fn finish_reader(&mut self) -> Result<(), &'static str> {
        match self.receiver.try_recv() {
            Ok(ReaderEvent::Eof) => {
                self.reader_terminal = true;
            }
            Ok(ReaderEvent::Failed(code)) => {
                self.reader_terminal = true;
                self.broken = true;
                return Err(code);
            }
            Ok(ReaderEvent::Frame(_)) => {
                self.broken = true;
                return Err("CONTROL_UNEXPECTED_FRAME");
            }
            Err(TryRecvError::Disconnected | TryRecvError::Empty) => {}
        }
        if self
            .reader
            .as_ref()
            .is_some_and(|reader| !reader.is_finished() && !self.reader_terminal)
        {
            return Err("CONTROL_READER_PENDING");
        }
        if let Some(reader) = self.reader.take() {
            reader.join().map_err(|_| "CONTROL_READER_FAILED")?;
        }
        Ok(())
    }
}

fn decode_reply(frame: &[u8], expected: &Expected) -> Result<ControlReply, &'static str> {
    if expected.command == ControlCommand::ReportsAuthorizeOpen {
        let reply: ReportsReply =
            serde_json::from_slice(frame).map_err(|_| "CONTROL_RESPONSE_INVALID")?;
        if reply.maintenance_protocol != 1
            || reply.generation != expected.generation
            || reply.request_id != expected.request_id
            || reply.root_id.as_ref().is_some_and(|id| !valid_uuid(id))
            || !valid_code(reply.code.as_deref())
            || (reply.allowed
                && (reply.root_id.is_none()
                    || reply.status == Some(ReplyStatus::Error)
                    || reply.code.is_some()))
            || (!reply.allowed && reply.code.is_none())
        {
            return Err("CONTROL_RESPONSE_MISMATCH");
        }
        return Ok(ControlReply::Reports(reply));
    }
    let reply: MaintenanceReply =
        serde_json::from_slice(frame).map_err(|_| "CONTROL_RESPONSE_INVALID")?;
    if reply.maintenance_protocol != 1
        || reply.request_id != expected.request_id
        || reply.generation != expected.generation
        || Some(reply.operation_id.as_str()) != expected.operation_id.as_deref()
        || !valid_code(reply.code.as_deref())
        || reply
            .source_root_id
            .as_ref()
            .is_some_and(|id| !valid_uuid(id))
        || reply
            .candidate_root_id
            .as_ref()
            .is_some_and(|id| !valid_uuid(id))
        || reply
            .manifest_sha256
            .as_ref()
            .is_some_and(|hash| !valid_digest(hash))
        || [&reply.source_fingerprint, &reply.candidate_fingerprint]
            .into_iter()
            .flatten()
            .any(|fingerprint| {
                fingerprint.is_empty()
                    || fingerprint.len() > 256
                    || fingerprint.chars().any(char::is_control)
            })
        || (reply.status == ReplyStatus::Error) != reply.code.is_some()
    {
        return Err("CONTROL_RESPONSE_MISMATCH");
    }
    if reply.status == ReplyStatus::Ok {
        let expected_state = match expected.command {
            ControlCommand::Quiesce => Some(RuntimeState::Quiesced),
            ControlCommand::Prepare => Some(RuntimeState::Prepared),
            ControlCommand::Close => Some(RuntimeState::Closed),
            ControlCommand::Activate => Some(RuntimeState::Active),
            _ => None,
        };
        if expected_state.is_some_and(|state| reply.state != state)
            || (expected.command == ControlCommand::Prepare && reply.kind != expected.kind)
        {
            return Err("CONTROL_RESPONSE_MISMATCH");
        }
    }
    Ok(ControlReply::Maintenance(reply))
}

fn valid_code(code: Option<&str>) -> bool {
    code.is_none_or(|code| {
        !code.is_empty()
            && code.len() <= 64
            && code
                .bytes()
                .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
    })
}
