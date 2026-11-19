pub const VERSION: &str = "0.13.1";
pub const EDITION: &str = "2026";
pub const STDLIB_VERSION: &str = "0.13.1";

pub mod ast;
pub mod errors;
pub mod format;
pub mod header;
pub mod lexer;
pub mod parser;
pub mod stdlib;
pub mod targets;
pub mod tokens;

pub use ast::File;
pub use errors::{BnError, Diagnostic};
pub use format::{format_file, format_source};
pub use header::{header, header_of, Header};
pub use lexer::tokenize;
pub use parser::{parse, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES};
pub use targets::{
    check_against, check_target, check_target_with, check_targets, check_targets_with, infer,
    infer_with, load_target, target_names, translate, translation_issues, Inference, Issue, Target,
    UnknownTarget,
};
pub use tokens::{Token, TokenKind};
