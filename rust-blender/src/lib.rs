//! Base Node for Blender: what the core (`base-node`, which reads a text and names no destination)
//! leaves to a host. The targets a text is checked against or translated to (`targets/`), the
//! standard library (`stdlib/`), and the head of a file as the add-on reads it.

pub mod header;
pub mod stdlib;
pub mod targets;
pub mod zones;

pub use header::{header, header_of, Header};
pub use targets::{
    check_against, check_target, check_target_with, check_targets, check_targets_with, infer,
    infer_with, inferred_names, load_target, promise_names, promise_refusal, target_names,
    translate, translation_issues, variant_names, Inference, Issue, Target, UnknownTarget,
};
