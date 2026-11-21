//! What a .bn file says of itself: the `// @name value` lines at its head.
//!
//! ```text
//! // @module mesh_maps
//! // @title Mesh maps
//! // @author Marc
//! // @license MIT
//! // @offer library, groups
//! ```
//!
//! The head is the comment and blank lines before the first `use` or graph. `@module`,
//! `@version` and `@edition` are those of the standard library, `@target` the targets the file
//! promises to fit (spec/targets.md); the others tell a host what it may do with the file when it is dropped on it (see [`OFFERS`]). A directive
//! this module does not know is left alone, for other tools to read; one it knows is checked.
//! The Python package's `base_node/header.py`, message for message.

use std::collections::{HashMap, HashSet};

use serde::Serialize;

use crate::ast::{flatten, is_identifier, key, AssignValue, Expr, File, Graph, ReturnValue, Stmt};
use crate::errors::{BnError, Diagnostic};
use crate::parser::parse;

/// What a dropped file may be used for, in the order a dialog lists them.
pub const OFFERS: [&str; 4] = ["library", "groups", "example", "modifier"];
/// The mesh `modifier` makes when no object takes the modifier.
pub const MESHES: [&str; 5] = ["cube", "plane", "sphere", "cylinder", "grid"];
const TEXT: [&str; 5] = ["title", "author", "license", "version", "edition"];
const KNOWN: [&str; 11] = [
    "module", "target", "offer", "example", "modifier", "mesh", "title", "author", "license",
    "version", "edition",
];

/// The directives of a file, checked against its graphs.
///
/// `offer` is what the file offers, as written or inferred; `example` and `modifier` the
/// graph each of these uses (none when not offered), `examples` and `modifiers` every graph
/// that could be used. `lines` keeps the line of each directive written.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Header {
    pub module: Option<String>,
    pub version: Option<String>,
    /// The targets promised, none when not written.
    pub target: Vec<String>,
    pub edition: Option<String>,
    pub title: Option<String>,
    pub author: Option<String>,
    pub license: Option<String>,
    pub offer: Vec<String>,
    pub offer_written: bool,
    pub example: Option<String>,
    pub modifier: Option<String>,
    pub mesh: String,
    pub examples: Vec<String>,
    pub modifiers: Vec<String>,
    pub lines: HashMap<String, usize>,
}

impl Default for Header {
    fn default() -> Self {
        Self {
            module: None,
            version: None,
            target: Vec::new(),
            edition: None,
            title: None,
            author: None,
            license: None,
            offer: Vec::new(),
            offer_written: false,
            example: None,
            modifier: None,
            mesh: "cube".to_owned(),
            examples: Vec::new(),
            modifiers: Vec::new(),
            lines: HashMap::new(),
        }
    }
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
    while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_' || chars[i] == '-') {
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

/// A quoted name, or a bare one, as written: none when it is neither.
fn unquote(value: &str) -> Option<String> {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() >= 2 && chars[0] == '"' && chars[chars.len() - 1] == '"' {
        let inner: String = chars[1..chars.len() - 1].iter().collect();
        return (!inner.contains('"') && !inner.is_empty()).then_some(inner);
    }
    is_identifier(value).then(|| value.to_owned())
}

/// `value` without the quotes around it, when it has them.
fn unquoted_text(value: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() >= 2 && chars[0] == '"' && chars[chars.len() - 1] == '"' {
        chars[1..chars.len() - 1].iter().collect()
    } else {
        value.to_owned()
    }
}

/// The value of a tree setting the graph writes, as `geometry(is_modifier: true) graph`.
fn setting(g: &Graph, name: &str) -> Option<bool> {
    g.settings.iter().find_map(|a| match (&a.name, &a.value) {
        (Some(n), Expr::Bool(b)) if n == name => Some(b.value),
        _ => None,
    })
}

/// (examples, modifiers): the names of the graphs nobody calls that make their own geometry (a
/// Geometry output, no Geometry input), then of those that are modifiers (first input and first
/// output Geometry, as the Blender builder decides).
pub fn shapes(file: &File) -> (Vec<String>, Vec<String>) {
    let mut called = HashSet::new();
    for g in &file.graphs {
        calls_in(&g.body, &mut called);
    }
    let (mut examples, mut modifiers) = (Vec::new(), Vec::new());
    for g in &file.graphs {
        if g.kind != "geometry" || called.contains(&key(&g.name)) || !g.type_params.is_empty() {
            continue;
        }
        let ins: Vec<String> = flatten(&g.tree("INPUT"))
            .into_iter()
            .map(|p| p.type_name)
            .collect();
        let outs: Vec<String> = flatten(&g.tree("OUTPUT"))
            .into_iter()
            .map(|p| p.type_name)
            .collect();
        let modifier = setting(g, "is_modifier").unwrap_or_else(|| {
            ins.first().is_some_and(|t| t == "Geometry")
                && outs.first().is_some_and(|t| t == "Geometry")
        });
        if modifier {
            modifiers.push(g.name.clone());
        }
        if outs.iter().any(|t| t == "Geometry") && !ins.iter().any(|t| t == "Geometry") {
            examples.push(g.name.clone());
        }
    }
    (examples, modifiers)
}

fn calls_in(body: &[Stmt], out: &mut HashSet<String>) {
    for stmt in body {
        match stmt {
            Stmt::Assign(a) => match &a.value {
                AssignValue::Expr(e) => calls_of(e, out),
                AssignValue::Repeat(z) => {
                    calls_of(&z.count, out);
                    z.states.iter().for_each(|s| calls_of(&s.value, out));
                    calls_in(&z.body, out);
                }
                AssignValue::Simulate(z) => {
                    z.states.iter().for_each(|s| calls_of(&s.value, out));
                    calls_in(&z.body, out);
                }
                AssignValue::Foreach(z) => {
                    calls_of(&z.geometry, out);
                    z.args.iter().for_each(|s| calls_of(&s.value, out));
                    calls_in(&z.body, out);
                }
                AssignValue::Closure(z) => calls_in(&z.body, out),
            },
            Stmt::Return(r) => match &r.value {
                ReturnValue::Expr(e) => calls_of(e, out),
                ReturnValue::Record(rec) => rec.fields.iter().for_each(|f| calls_of(&f.value, out)),
            },
            Stmt::Frame(f) => calls_in(&f.body, out),
        }
    }
}

fn calls_of(e: &Expr, out: &mut HashSet<String>) {
    match e {
        Expr::Call(c) => {
            out.insert(c.name.clone());
            c.args.iter().for_each(|a| calls_of(&a.value, out));
        }
        Expr::Tuple(t) => t.items.iter().for_each(|i| calls_of(i, out)),
        Expr::Member(m) => calls_of(&m.target, out),
        Expr::Pipe(p) => {
            calls_of(&p.left, out);
            calls_of(&p.call, out);
        }
        Expr::BinOp(b) => {
            calls_of(&b.left, out);
            calls_of(&b.right, out);
        }
        Expr::Neg(n) => calls_of(&n.value, out),
        Expr::Not(n) => calls_of(&n.value, out),
        Expr::Cond(c) => {
            calls_of(&c.cond, out);
            calls_of(&c.then, out);
            calls_of(&c.orelse, out);
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
    }
}

/// The checked header of a .bn source. Fails on a malformed directive, a choice offered that no
/// graph allows, a graph named that is not one of the file or not of its shape; a syntax error
/// is the parser's.
pub fn header(source: &str, filename: &str) -> Result<Header, BnError> {
    let file = parse(source, filename)?;
    header_of(source, filename, &file)
}

/// The checked header of a source whose syntax tree `file` the caller has already.
pub fn header_of(source: &str, filename: &str, file: &File) -> Result<Header, BnError> {
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
        if !KNOWN.contains(&d.name.as_str()) {
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
        let value = get(name).map(|d| unquoted_text(&d.value));
        match name {
            "title" => h.title = value,
            "author" => h.author = value,
            "license" => h.license = value,
            "version" => h.version = value,
            _ => h.edition = value,
        }
    }
    if let Some(d) = get("target") {
        let known = crate::targets::target_names();
        let mut at = d.col;
        for part in d.value.split(',') {
            let word = part.trim().trim_matches('"');
            let lead = part.chars().count() - part.trim_start().chars().count();
            let where_ = at + lead;
            at += part.chars().count() + 1;
            if !known.is_empty() && !known.contains(&word) {
                let message = format!("@target '{word}': one of {}", known.join(", "));
                error(&mut diags, d.line, where_, message);
            } else if !h.target.iter().any(|t| t == word) {
                h.target.push(word.to_owned());
            }
        }
    }
    if let Some(d) = get("module") {
        match unquote(&d.value).filter(|n| is_identifier(n)) {
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
    if let Some(d) = get("mesh") {
        let mesh = d.value.trim_matches('"');
        if MESHES.contains(&mesh) {
            h.mesh = mesh.to_owned();
        } else {
            let message = format!("@mesh '{}': one of {}", d.value, MESHES.join(", "));
            error(&mut diags, d.line, d.col, message);
        }
    }

    (h.examples, h.modifiers) = shapes(file);
    let by_key: HashMap<String, String> = file
        .graphs
        .iter()
        .map(|g| (key(&g.name), g.name.clone()))
        .collect();
    let pick = |diags: &mut Vec<Diagnostic>, kind: &str, candidates: &[String], shape: &str| {
        let Some(d) = get(kind) else {
            // The last graph is the file's main one.
            return candidates.last().cloned();
        };
        let Some(name) = unquote(&d.value) else {
            let message = format!(
                "@{kind} {}: a graph's name, quoted, or a bare identifier",
                d.value
            );
            error(diags, d.line, d.col, message);
            return None;
        };
        let graph = if file.graphs.iter().any(|g| g.name == name) {
            Some(name.clone())
        } else {
            by_key.get(&key(&name)).cloned()
        };
        let Some(graph) = graph else {
            let message = format!("@{kind} '{name}': no graph of that name in this file");
            error(diags, d.line, d.col, message);
            return None;
        };
        if !candidates.contains(&graph) {
            error(diags, d.line, d.col, format!("@{kind} '{name}': {shape}"));
            return None;
        }
        Some(graph)
    };
    let examples = h.examples.clone();
    let modifiers = h.modifiers.clone();
    let example = pick(
        &mut diags,
        "example",
        &examples,
        "not a geometry graph nobody calls that makes its own geometry (a Geometry output, no Geometry input)",
    );
    let modifier = pick(
        &mut diags,
        "modifier",
        &modifiers,
        "not a modifier: a geometry graph nobody calls whose first input and output are Geometry",
    );

    if let Some(d) = get("offer") {
        h.offer_written = true;
        let mut offered: Vec<&str> = Vec::new();
        let mut at = d.col;
        for part in d.value.split(',') {
            let word = part.trim();
            let lead = part.chars().count() - part.trim_start().chars().count();
            let where_ = at + lead;
            at += part.chars().count() + 1;
            if !OFFERS.contains(&word) {
                let message = format!("@offer '{word}': one of {}", OFFERS.join(", "));
                error(&mut diags, d.line, where_, message);
            } else if !offered.contains(&word) {
                offered.push(word);
            }
        }
        let why = |word: &str| -> Option<(bool, &str, &str)> {
            Some(match word {
                "library" => (
                    h.module.is_some(),
                    "module",
                    "there is no @module to install the file as",
                ),
                "example" => (
                    example.is_some(),
                    "example",
                    "no geometry graph nobody calls makes its own geometry",
                ),
                "modifier" => (
                    modifier.is_some(),
                    "modifier",
                    "no geometry graph nobody calls has Geometry as first input and output",
                ),
                _ => return None,
            })
        };
        let mut missing = Vec::new();
        for word in &offered {
            if let Some((false, source, message)) = why(word) {
                // A directive already in error says why: once is enough.
                let line = h.lines.get(source).copied();
                let told = diags.iter().any(|x| Some(x.line) == line);
                if !told {
                    missing.push(format!("@offer {word}: {message}"));
                }
            }
        }
        for message in missing {
            error(&mut diags, d.line, d.col, message);
        }
        h.offer = OFFERS
            .iter()
            .filter(|o| offered.contains(o))
            .map(|o| o.to_string())
            .collect();
    } else {
        h.offer = [
            ("library", h.module.is_some()),
            ("groups", true),
            ("example", example.is_some()),
            ("modifier", modifier.is_some()),
        ]
        .iter()
        .filter(|(_, ok)| *ok)
        .map(|(o, _)| o.to_string())
        .collect();
    }
    h.example = example.filter(|_| h.offer.iter().any(|o| o == "example"));
    h.modifier = modifier.filter(|_| h.offer.iter().any(|o| o == "modifier"));
    if diags.is_empty() {
        Ok(h)
    } else {
        Err(BnError::from_diagnostics(diags))
    }
}
