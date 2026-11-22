//! What a .bn file says of itself to Blender: the head the core reads (`base_node::header`), and
//! what the file offers when it is dropped on Blender.
//!
//! ```text
//! // @module mesh_maps
//! // @offer library, groups
//! ```
//!
//! `@target` names targets of targets/ (`blender@5.3 gltf`: a target, a version of it, a variant;
//! an alias such as `blender@latest` is the command line's, not a text's); `@offer`, `@example`, `@modifier` and `@mesh` tell the add-on
//! what it may do with the file (see [`OFFERS`]), and are checked against its graphs. The Python
//! package's `python/base_node_blender/header.py`, message for message.

use std::collections::{HashMap, HashSet};

use serde::Serialize;

use base_node::ast::{flatten, key, AssignValue, Expr, File, Graph, ReturnValue, Stmt};
use base_node::header::{read_head_by, unquote};
use base_node::{parse, BnError, Diagnostic};

use crate::targets::promise_refusal;

/// What a dropped file may be used for, in the order a dialog lists them.
pub const OFFERS: [&str; 4] = ["library", "groups", "example", "modifier"];
/// The mesh `modifier` makes when no object takes the modifier.
pub const MESHES: [&str; 5] = ["cube", "plane", "sphere", "cylinder", "grid"];
const KNOWN: [&str; 4] = ["offer", "example", "modifier", "mesh"];

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
                AssignValue::BodyCall(z) => {
                    z.args.iter().for_each(|s| calls_of(&s.value, out));
                    calls_in(&z.body, out);
                }
                AssignValue::NamelessGraph(z) => calls_in(&z.body, out),
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
    let head = read_head_by(source, filename, &promise_refusal, &KNOWN);
    let core = head.header.clone();
    let mut h = Header {
        module: core.module,
        version: core.version,
        target: core.target,
        edition: core.edition,
        title: core.title,
        author: core.author,
        license: core.license,
        lines: core.lines,
        ..Header::default()
    };
    let get = |name: &str| head.get(name).cloned();
    let mut diags: Vec<Diagnostic> = head.diagnostics.clone();
    let error = |diags: &mut Vec<Diagnostic>, line: usize, col: usize, message: String| {
        diags.push(Diagnostic {
            filename: filename.to_owned(),
            line,
            col,
            message,
        });
    };

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
