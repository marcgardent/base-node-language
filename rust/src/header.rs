//! What a .bn file says of itself: the `// @name value` lines at its head.
//!
//! ```text
//! // @module mesh_maps
//! // @title Mesh maps
//! // @author Marc
//! // @license MIT
//! ```
//!
//! The head is the comment and blank lines before the first `use` or graph. `@module`,
//! `@version` and `@edition` are those of the standard library, `@target` the targets the file
//! promises to fit (spec/targets.md). A directive this module does not know is left alone, for
//! other tools to read; one it knows is checked. `@edition` is the language's: a text of an edition
//! this reader does not know is refused, here and by the parser ([`edition_error`]). A host has directives of its own, saying what it
//! may do with the file: [`read_head`] checks that each is written once, with a value, and gives
//! them back as written, for the host to judge. The Python package's `python/base_node/header.py`,
//! message for message.

use std::collections::HashMap;

use serde::Serialize;

use crate::ast::is_bare;
use crate::errors::{BnError, Diagnostic};
use crate::lexer::string_literal;

const TEXT: [&str; 5] = ["title", "author", "license", "version", "edition"];
const KNOWN: [&str; 7] = [
    "module", "target", "title", "author", "license", "version", "edition",
];

/// The editions of the language this reader knows, the latest last: a text that names none is of
/// the latest.
pub const EDITIONS: [&str; 1] = ["2026"];

/// The directives of a file. `lines` keeps the line of each directive written.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Header {
    pub module: Option<String>,
    pub version: Option<String>,
    /// The targets promised, none when not written.
    pub target: Vec<String>,
    pub edition: Option<String>,
    pub title: Option<String>,
    pub author: Option<String>,
    pub license: Option<String>,
    pub lines: HashMap<String, usize>,
}

/// A directive of the head as written: its name, its value, and the line and column (1-based,
/// in characters) of the value.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Directive {
    pub name: String,
    pub value: String,
    pub line: usize,
    pub col: usize,
}

/// The directives of the head of `source`, as written.
pub fn directives(source: &str) -> Vec<Directive> {
    let mut out = Vec::new();
    for (number, raw) in source.lines().enumerate() {
        let text = raw.trim();
        if text.is_empty() {
            continue;
        }
        if !text.starts_with("//") {
            break;
        }
        let indent = raw.chars().count() - raw.trim_start().chars().count();
        if let Some((name, value, at)) = directive(text) {
            out.push(Directive {
                name,
                value: value.trim().to_owned(),
                line: number + 1,
                col: indent + at + 1,
            });
        }
    }
    out
}

/// `// @name value` read from a comment line: its name, its value, and where the value starts
/// (in characters); none for a plain comment, or `// @target"x"` (no space before the value).
fn directive(text: &str) -> Option<(String, String, usize)> {
    let chars: Vec<char> = text.chars().collect();
    let mut i = 2;
    while i < chars.len() && chars[i].is_whitespace() {
        i += 1;
    }
    if chars.get(i) != Some(&'@') {
        return None;
    }
    i += 1;
    let start = i;
    if !chars
        .get(i)
        .is_some_and(|c| c.is_ascii_alphabetic() || *c == '_')
    {
        return None;
    }
    while i < chars.len()
        && (chars[i].is_ascii_alphanumeric() || chars[i] == '_' || chars[i] == '-')
    {
        i += 1;
    }
    let name: String = chars[start..i].iter().collect();
    let spaced = i;
    while i < chars.len() && chars[i].is_whitespace() {
        i += 1;
    }
    let value: String = chars[i..].iter().collect();
    if !value.is_empty() && spaced == i {
        return None;
    }
    Some((name, value, i))
}

/// A name written in a directive: a string, its escapes read as in any string
/// (`"say \"hi\""` is `say "hi"`), or a bare one as written. None when it is neither, or empty.
pub fn unquote(value: &str) -> Option<String> {
    if value.starts_with('"') {
        return string_literal(value).filter(|s| !s.is_empty());
    }
    is_bare(value).then(|| value.to_owned())
}

/// A directive's free text: the string it is, its escapes read, when it is one, else as written.
pub fn unquoted(value: &str) -> String {
    value
        .starts_with('"')
        .then(|| string_literal(value))
        .flatten()
        .unwrap_or_else(|| value.to_owned())
}

fn unknown_edition(value: &str) -> String {
    format!(
        "@edition '{value}': not an edition this reader knows ({})",
        EDITIONS.join(", ")
    )
}

/// The diagnostic of the `@edition` of a source when this reader does not know that edition.
pub fn edition_error(source: &str, filename: &str) -> Option<Diagnostic> {
    // The first one written is the file's: a second is an error of the head
    let d = directives(source)
        .into_iter()
        .find(|d| d.name == "edition")?;
    let value = unquoted(&d.value);
    (!d.value.is_empty() && !EDITIONS.contains(&value.as_str())).then(|| Diagnostic {
        filename: filename.to_owned(),
        line: d.line,
        col: d.col,
        message: unknown_edition(&value),
    })
}

/// The head of a source as [`read_head`] read it: nothing has failed yet.
#[derive(Clone, Debug)]
pub struct Head {
    pub header: Header,
    /// What is wrong in the head so far; the caller adds what it finds.
    pub diagnostics: Vec<Diagnostic>,
    written: HashMap<String, Directive>,
}

impl Head {
    /// A directive as written, and where its value is; none when it is not written, or has no
    /// value.
    pub fn get(&self, name: &str) -> Option<&Directive> {
        self.written.get(name).filter(|d| !d.value.is_empty())
    }
}

/// The head of a .bn source, read: nothing fails.
///
/// `targets` are the names the caller accepts after `@target`: with none, any name is read.
/// `extra` are the directives of the caller: [`Head::get`] gives each as written, and the caller
/// adds to the diagnostics what it finds.
pub fn read_head(source: &str, filename: &str, targets: &[&str], extra: &[&str]) -> Head {
    let refuse = |word: &str| {
        (!targets.is_empty() && !targets.contains(&word))
            .then(|| format!("one of {}", targets.join(", ")))
    };
    read_head_by(source, filename, &refuse, extra)
}

/// The same, for a caller whose targets are more than a list of names: `refuse` says of a name as
/// written why it is refused (what follows `@target '<name>': `), or none. A name is written
/// `name`, `name@version` or either with words after it, spaces apart: what the version and the
/// words mean is the caller's.
pub fn read_head_by(
    source: &str,
    filename: &str,
    refuse: &dyn Fn(&str) -> Option<String>,
    extra: &[&str],
) -> Head {
    let mut h = Header::default();
    let mut diags: Vec<Diagnostic> = Vec::new();
    let error = |diags: &mut Vec<Diagnostic>, line: usize, col: usize, message: String| {
        diags.push(Diagnostic {
            filename: filename.to_owned(),
            line,
            col,
            message,
        });
    };

    let mut written: HashMap<String, Directive> = HashMap::new();
    for d in directives(source) {
        if !KNOWN.contains(&d.name.as_str()) && !extra.contains(&d.name.as_str()) {
            continue;
        }
        if let Some(first) = written.get(&d.name) {
            let message = format!("@{} is already set on line {}", d.name, first.line);
            error(&mut diags, d.line, d.col, message);
            continue;
        }
        h.lines.insert(d.name.clone(), d.line);
        if d.value.is_empty() {
            error(
                &mut diags,
                d.line,
                d.col,
                format!("@{} needs a value", d.name),
            );
        }
        written.insert(d.name.clone(), d);
    }
    // A directive and where its value is, when it has one.
    let get = |name: &str| written.get(name).filter(|d| !d.value.is_empty()).cloned();

    for name in TEXT {
        let value = get(name).map(|d| unquoted(&d.value));
        match name {
            "title" => h.title = value,
            "author" => h.author = value,
            "license" => h.license = value,
            "version" => h.version = value,
            _ => h.edition = value,
        }
    }
    if let (Some(d), Some(value)) = (get("edition"), h.edition.as_deref()) {
        if !EDITIONS.contains(&value) {
            error(&mut diags, d.line, d.col, unknown_edition(value));
        }
    }
    if let Some(d) = get("target") {
        let mut at = d.col;
        for part in d.value.split(',') {
            let word = unquoted(part.trim());
            let word = word.split_whitespace().collect::<Vec<_>>().join(" ");
            let lead = part.chars().count() - part.trim_start().chars().count();
            let where_ = at + lead;
            at += part.chars().count() + 1;
            if let Some(why) = refuse(&word) {
                error(
                    &mut diags,
                    d.line,
                    where_,
                    format!("@target '{word}': {why}"),
                );
            } else if !h.target.contains(&word) {
                h.target.push(word);
            }
        }
    }
    if let Some(d) = get("module") {
        match unquote(&d.value).filter(|n| is_bare(n)) {
            Some(name) => h.module = Some(name),
            None => error(
                &mut diags,
                d.line,
                d.col,
                format!(
                    "@module '{}': a module is named by an identifier (letters, digits, _), its file being <name>.bn",
                    d.value
                ),
            ),
        }
    }
    Head {
        header: h,
        diagnostics: diags,
        written,
    }
}

/// The checked header of a .bn source. Fails on a malformed directive. `targets` are the names
/// accepted after `@target`: with none, any name is read.
pub fn header(source: &str, filename: &str, targets: &[&str]) -> Result<Header, BnError> {
    let head = read_head(source, filename, targets, &[]);
    if head.diagnostics.is_empty() {
        Ok(head.header)
    } else {
        Err(BnError::from_diagnostics(head.diagnostics))
    }
}
