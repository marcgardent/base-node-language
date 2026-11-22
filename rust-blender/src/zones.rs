//! Blender's zones, as the text writes them (python/base_node_blender/zones.py).
//!
//! The language has calls that take a body, `name[settings](arguments) -> { … }`, and graphs with no name,
//! `graph(x: Float) -> Float { … }`: what they are is a host's to say. Here, `repeat`, `simulate`
//! and `foreach` are the calls that take a body, a Repeat, a Simulation and a For Each Geometry
//! Element zone (its domain a setting, `foreach[FACE](…)`), and a graph with no name is a Closure
//! zone.

use base_node::ast::{AssignValue, BodyCall};

/// The calls that take a body.
pub const BODY_CALLS: [&str; 3] = ["repeat", "simulate", "foreach"];

/// The zone word of the value of an assignment, as a target lists it (`targets/*.json`, "zones").
pub fn word(value: &AssignValue) -> Option<&'static str> {
    match value {
        AssignValue::Expr(_) => None,
        AssignValue::NamelessGraph(_) => Some("closure"),
        AssignValue::BodyCall(c) => call_word(&c.name),
    }
}

/// The zone a call with a body of that name writes.
pub fn call_word(name: &str) -> Option<&'static str> {
    BODY_CALLS.iter().find(|w| **w == name).copied()
}

/// Why a call with a body is no zone: its name takes none, or its arguments are not of the
/// zone's shape. `(line, col, message)`, the same as the Python library says.
pub fn refused(call: &BodyCall) -> Option<(usize, usize, String)> {
    let at = |message: &str| Some((call.line, call.col, message.to_owned()));
    let args = &call.args;
    if matches!(call.name.as_str(), "repeat" | "simulate") && !call.settings.is_empty() {
        return at(&format!("{} has no settings", call.name));
    }
    match call.name.as_str() {
        "repeat" => {
            if args.is_empty() || args[0].name.is_some() {
                return at(
                    "repeat expects iteration count first: repeat(10, state: start, …) -> { … }",
                );
            }
            if args.len() < 2 {
                return at("repeat expects at least one state: repeat(10, state: start) -> { … }");
            }
            if args.iter().any(|a| !a.options.is_empty()) {
                return at("repeat state does not take options");
            }
            None
        }
        "simulate" => {
            if args.iter().any(|a| a.name.is_none()) {
                return at("simulate expects named states: simulate(state: start, …) -> { … }");
            }
            None
        }
        "foreach" => {
            // A state of repeat or simulate may take a key of its own; a foreach item not yet
            for a in args {
                if let (Some(name), Some(alias)) = (&a.name, &a.alias) {
                    return Some((
                        a.line,
                        a.col,
                        format!("'{name} as {alias}': 'as' only aliases an item of an item node"),
                    ));
                }
            }
            if args.is_empty()
                || args[0].name.is_some()
                || args[1..].iter().any(|a| a.name.is_none())
            {
                return at("foreach expects geometry first, then named items: \
                           foreach[FACE](geometry, item: field, …) -> { … }");
            }
            None
        }
        name => at(&format!(
            "'{name}' takes no body: repeat, simulate and foreach do"
        )),
    }
}
