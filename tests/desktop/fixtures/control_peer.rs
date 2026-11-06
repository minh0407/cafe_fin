//! Synthetic private-pipe peer, not Cafe Fin backend/GUI/installer acceptance.
use std::io::{self, BufRead, Write};

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_default();
    let mut stdout = io::stdout().lock();
    writeln!(stdout, "{{\"fixture_boot\":true}}").unwrap();
    stdout.flush().unwrap();
    let mut line = String::new();
    io::stdin().lock().read_line(&mut line).unwrap();
    let request: serde_json::Value = serde_json::from_str(&line).unwrap();
    if mode == "delayed" {
        std::thread::sleep(std::time::Duration::from_millis(150));
    }
    if mode == "oversized" {
        stdout.write_all(&vec![b'x'; 16385]).unwrap();
        stdout.flush().unwrap();
        return;
    }
    let command = request["command"].as_str().unwrap();
    let state = match command {
        "maintenance.close" => "CLOSED",
        "maintenance.prepare" => "PREPARED",
        "maintenance.quiesce" => "QUIESCED",
        _ => "ACTIVE",
    };
    let runtime_state = match command {
        "maintenance.prepare" => "QUIESCED",
        _ => state,
    };
    let mut response = serde_json::json!({
        "maintenance_protocol":1, "request_id":request["request_id"],
        "generation":request["generation"], "operation_id":request["operation_id"],
        "status":"ok", "state":state, "runtime_state":runtime_state, "kind":request["kind"],
    });
    if command == "reports.authorize_open" {
        response = serde_json::json!({"maintenance_protocol":1, "request_id":request["request_id"],
            "generation":request["generation"], "allowed":true,
            "root_id":"00000000-0000-4000-8000-000000000003"});
        response["source_fingerprint"] = "opaque:reports-source".into();
    }
    match mode.as_str() {
        "wrong-generation" => {
            response["generation"] = "00000000-0000-4000-8000-000000000099".into()
        }
        "wrong-operation" => {
            response["operation_id"] = "00000000-0000-4000-8000-000000000099".into()
        }
        "wrong-request" => response["request_id"] = "00000000-0000-4000-8000-000000000099".into(),
        "extra-field" => response["raw_exception"] = "synthetic-private-error".into(),
        "wrong-state" => response["state"] = "ACTIVE".into(),
        "wrong-kind" => response["kind"] = "restore".into(),
        "prepared-held" => {
            response["state"] = "PREPARED".into();
            response["runtime_state"] = "QUIESCED".into();
        }
        "replay-required" => {
            response["state"] = "REPLAY_REQUIRED".into();
            response["runtime_state"] = "DORMANT".into();
        }
        "bad-runtime-state" => response["runtime_state"] = "REPLAY_REQUIRED".into(),
        "close-authorized" => {
            response["state"] = "CLOSE_AUTHORIZED".into();
            response["runtime_state"] = "QUIESCED".into();
        }
        "close-not-drained" => response["runtime_state"] = "QUIESCED".into(),
        "failed-held" => {
            response["state"] = "FAILED_HELD".into();
            response["runtime_state"] = "QUIESCED".into();
            response["code"] = "MAINTENANCE_ARTIFACT_CONFLICT".into();
        }
        "missing-runtime" => {
            response.as_object_mut().unwrap().remove("runtime_state");
        }
        "wrong-origin" => {
            response["origin_generation"] = "00000000-0000-4000-8000-000000000099".into()
        }
        "wrong-activation" => {
            response["activation_id"] = "00000000-0000-4000-8000-000000000099".into()
        }
        "wrong-format" => response["format"] = 2.into(),
        _ => {}
    }
    writeln!(stdout, "{response}").unwrap();
    stdout.flush().unwrap();
    drop(stdout);
    if mode == "nonzero" {
        std::process::exit(86);
    }
}
