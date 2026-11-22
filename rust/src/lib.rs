/// The version of the crate, as Cargo.toml says it
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// The latest edition: that of a text that names none.
pub const EDITION: &str = header::EDITIONS[header::EDITIONS.len() - 1];
pub const STDLIB_VERSION: &str = "1.0.0-rc.5";

pub mod ast;
pub mod errors;
pub mod format;
pub mod header;
pub mod lexer;
pub mod parser;
pub mod tokens;

pub use ast::File;
pub use errors::{BnError, Diagnostic};
pub use format::{format_file, format_source};
pub use header::{header, read_head, read_head_by, Header, EDITIONS};
pub use lexer::tokenize;
pub use parser::{parse, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES};
pub use tokens::{Token, TokenKind};
