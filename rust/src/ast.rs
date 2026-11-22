use serde::{Deserialize, Serialize};

use crate::identifiers::{CONTINUE, START};

pub const RESERVED: &[&str] = &[
    "graph", "return", "true", "false", "and", "or", "xor", "not", "dot", "cross", "inf", "nan",
];

pub fn is_reserved(s: &str) -> bool {
    RESERVED.contains(&s)
}

/// Whether an identifier may start with the character `c`: `_`, an ASCII letter, or past ASCII a
/// character of XID_Start. One rule for the lexer, which reads a name, and the printer, which
/// writes one bare or quoted, from the tables python/base_node/names.py reads too.
pub fn starts_name(c: char) -> bool {
    if c.is_ascii() {
        return c.is_ascii_alphabetic() || c == '_';
    }
    in_table(START, c)
}

/// Whether an identifier may go on with the character `c`: `_`, an ASCII letter or digit, or past
/// ASCII a character of XID_Continue, but `·` (the dot product).
pub fn goes_on_name(c: char) -> bool {
    if c.is_ascii() {
        return c.is_ascii_alphanumeric() || c == '_';
    }
    in_table(CONTINUE, c)
}

/// Whether `c` is in a table of sorted bounds, each range from an even index to the odd one after
/// it, excluded.
fn in_table(table: &[u32], c: char) -> bool {
    table.partition_point(|&b| b <= c as u32) % 2 == 1
}

/// What the lexer reads as one name: `height`, `_2`, `ρ_θ_φ`; not `2d`, `a b`, `a·b`, `x²`.
pub fn is_identifier(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if starts_name(c) => chars.all(goes_on_name),
        _ => false,
    }
}

/// A name the printer writes as it is: an identifier, not a reserved word. Any other is quoted
/// where the grammar takes a quoted name, or written by its key.
pub fn is_bare(s: &str) -> bool {
    !is_reserved(s) && is_identifier(s)
}

/// A name written bare where a value goes, an enum value or a material: bare, and not `_`, which
/// is no value there. Any other is a string.
pub fn is_word(s: &str) -> bool {
    s != "_" && is_bare(s)
}

/// A name as written in text: `Base Color` -> `base_color`. Lowercase, each run of characters an
/// identifier does not hold one `_`, a `_` before a first character no identifier starts with,
/// and after a reserved word: always a bare identifier.
pub fn snake(name: &str) -> String {
    let mut words = String::new();
    let mut gap = false;
    for c in name.to_lowercase().chars() {
        if goes_on_name(c) {
            if gap && !words.is_empty() {
                words.push('_');
            }
            words.push(c);
            gap = false;
        } else {
            gap = true;
        }
    }
    let mut s = words.trim_matches('_').to_string();
    if !s.chars().next().is_some_and(starts_name) {
        s.insert(0, '_');
    }
    if is_reserved(&s) {
        s.push('_');
    }
    s
}

pub fn key(name: &str) -> String {
    if is_bare(name) {
        name.to_string()
    } else {
        snake(name)
    }
}

/// A declared name: bare when the lexer reads it back as that name, else quoted.
pub fn name_display(n: &str) -> String {
    if is_bare(n) {
        n.to_string()
    } else {
        quote(n)
    }
}

/// An argument or socket name: bare when the lexer reads it back as that name, else quoted.
pub fn label_display(n: &str) -> String {
    if is_bare(n) {
        n.to_string()
    } else {
        quote(n)
    }
}

/// A string of the text, any string read back as it is: `"` and `\` escaped, the line breaks,
/// the tabs and the other control characters by their escape, `\n` or `\u{1b}`.
pub fn quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            '\0'..='\x1f' | '\x7f' => out.push_str(&format!("\\u{{{:x}}}", c as u32)),
            _ => out.push(c),
        }
    }
    out.push('"');
    out
}

/// A call's name: `m::"Big Blend"` when what follows the module is not a chain of identifiers.
pub fn call_name(n: &str) -> String {
    match n.split_once("::") {
        Some((module, rest)) if !rest.split("::").all(is_bare) => {
            format!("{}::{}", module, quote(rest))
        }
        _ => n.to_string(),
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Number {
    pub value: f64,
    pub is_int: bool,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StringLit {
    pub value: String,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct BoolLit {
    pub value: bool,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Tuple {
    pub items: Vec<Expr>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ref {
    pub name: String,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Member {
    pub target: Box<Expr>,
    pub socket: String,
    pub line: usize,
    pub col: usize,
}

/// `Math[ADD, use_clamp: true](Value: a, Value_001: b)`: a setting of a node, what no wire can feed.
///
/// Its value is a literal, a name (an enum value, a template's type, `_`), a tuple of them or a
/// call of them, such as `Ramp(…)`: never a name that holds a value. Which settings a node has,
/// the host says.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Setting {
    /// None for a setting given by position
    pub name: Option<String>,
    pub value: Expr,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Call {
    pub name: String,
    pub args: Vec<Arg>,
    pub line: usize,
    pub col: usize,
    pub outputs: Option<Vec<Param>>,
    pub single_output: bool,
    /// `attribute_or<Vector>(…)`: the types a template is called with, as written; None when inferred
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub type_args: Option<Vec<String>>,
    /// `Math[ADD](Value: a, Value_001: b)`: the settings written in brackets, in source order
    #[serde(default)]
    pub settings: Vec<Setting>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Pipe {
    pub left: Box<Expr>,
    pub call: Box<Expr>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BinOp {
    pub op: String,
    pub left: Box<Expr>,
    pub right: Box<Expr>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Neg {
    pub value: Box<Expr>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Not {
    pub value: Box<Expr>,
    pub line: usize,
    pub col: usize,
}

/// `cond ? then : orelse`: one value or the other. `line` and `col` are those of the `?`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Cond {
    pub cond: Box<Expr>,
    pub then: Box<Expr>,
    pub orelse: Box<Expr>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Expr {
    Number(Number),
    String(StringLit),
    Bool(BoolLit),
    Tuple(Tuple),
    Ref(Ref),
    Member(Member),
    Call(Call),
    Pipe(Pipe),
    BinOp(BinOp),
    Neg(Neg),
    Not(Not),
    Cond(Cond),
}

impl Expr {
    pub fn line(&self) -> usize {
        match self {
            Expr::Number(e) => e.line,
            Expr::String(e) => e.line,
            Expr::Bool(e) => e.line,
            Expr::Tuple(e) => e.line,
            Expr::Ref(e) => e.line,
            Expr::Member(e) => e.line,
            Expr::Call(e) => e.line,
            Expr::Pipe(e) => e.line,
            Expr::BinOp(e) => e.line,
            Expr::Neg(e) => e.line,
            Expr::Not(e) => e.line,
            Expr::Cond(e) => e.line,
        }
    }

    pub fn col(&self) -> usize {
        match self {
            Expr::Number(e) => e.col,
            Expr::String(e) => e.col,
            Expr::Bool(e) => e.col,
            Expr::Tuple(e) => e.col,
            Expr::Ref(e) => e.col,
            Expr::Member(e) => e.col,
            Expr::Call(e) => e.col,
            Expr::Pipe(e) => e.col,
            Expr::BinOp(e) => e.col,
            Expr::Neg(e) => e.col,
            Expr::Not(e) => e.col,
            Expr::Cond(e) => e.col,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Arg {
    pub name: Option<String>,
    pub value: Expr,
    pub line: usize,
    pub col: usize,
    pub options: Vec<Arg>,
    pub type_decl: Option<Param>,
    pub alias: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Param {
    pub name: String,
    pub type_name: String,
    pub line: usize,
    pub col: usize,
    pub default: Option<Expr>,
    pub range: Option<(Option<Expr>, Option<Expr>)>,
    pub options: Vec<Arg>,
    pub alias: Option<String>,
}

impl Param {
    pub fn key(&self) -> String {
        self.alias.clone().unwrap_or_else(|| key(&self.name))
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Panel {
    pub name: String,
    pub items: Vec<ParamTreeItem>,
    pub line: usize,
    pub col: usize,
    pub options: Vec<Arg>,
    pub end: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[allow(clippy::large_enum_variant)]
pub enum ParamTreeItem {
    Param(Param),
    Panel(Panel),
}

pub fn flatten(items: &[ParamTreeItem]) -> Vec<Param> {
    let mut out = Vec::new();
    for item in items {
        match item {
            ParamTreeItem::Param(p) => out.push(p.clone()),
            ParamTreeItem::Panel(panel) => out.extend(flatten(&panel.items)),
        }
    }
    out
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Look {
    pub flags: Vec<String>,
    pub line: usize,
    pub col: usize,
    pub label: Option<String>,
    pub color: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Record {
    pub fields: Vec<Arg>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum ReturnValue {
    Expr(Expr),
    Record(Record),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Return {
    pub value: ReturnValue,
    pub line: usize,
    pub col: usize,
    pub look: Option<Look>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Frame {
    pub label: Option<String>,
    pub color: Option<String>,
    pub body: Vec<Stmt>,
    pub line: usize,
    pub col: usize,
    pub end: usize,
    pub continued: bool,
}

/// `name[settings](arguments) -> { … return … }`: a call that takes a body, its settings optional,
/// written only as the value of an assignment. The name may be qualified, as any call's. Which names take a body, what their
/// arguments are, what the body sees and what it returns, the host says.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BodyCall {
    pub name: String,
    pub args: Vec<Arg>,
    pub body: Vec<Stmt>,
    pub line: usize,
    pub col: usize,
    pub end: usize,
    /// `name[SETTING](…) -> {`: the settings written in brackets, in source order
    #[serde(default)]
    pub settings: Vec<Setting>,
}

/// `graph(x: Float, …) -> Float { … return … }`: a graph with no name, a value, written only as
/// the value of an assignment. It writes no kind: it has the kind of the graph that holds it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NamelessGraph {
    pub params: Vec<Param>,
    pub outputs: Vec<Param>,
    pub single_output: bool,
    pub body: Vec<Stmt>,
    pub line: usize,
    pub col: usize,
    pub end: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum AssignValue {
    Expr(Expr),
    BodyCall(BodyCall),
    NamelessGraph(NamelessGraph),
}

impl AssignValue {
    /// The statements of a call with a body or of a graph with no name, and the line of the
    /// brace that closes them.
    pub fn body(&self) -> Option<(&[Stmt], usize)> {
        match self {
            AssignValue::Expr(_) => None,
            AssignValue::BodyCall(c) => Some((&c.body, c.end)),
            AssignValue::NamelessGraph(g) => Some((&g.body, g.end)),
        }
    }

    pub fn body_mut(&mut self) -> Option<&mut Vec<Stmt>> {
        match self {
            AssignValue::Expr(_) => None,
            AssignValue::BodyCall(c) => Some(&mut c.body),
            AssignValue::NamelessGraph(g) => Some(&mut g.body),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Assign {
    pub name: String,
    pub value: AssignValue,
    pub line: usize,
    pub col: usize,
    pub look: Option<Look>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Stmt {
    Assign(Assign),
    Return(Return),
    Frame(Frame),
}

/// `T: Float | Vector | Color`: a template's type parameter and the types it is built for.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TypeParam {
    pub name: String,
    pub types: Vec<String>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Graph {
    pub kind: String,
    pub name: String,
    pub params: Vec<Param>,
    pub outputs: Vec<Param>,
    pub single_output: bool,
    pub body: Vec<Stmt>,
    pub line: usize,
    pub col: usize,
    pub end: usize,
    pub description: Option<String>,
    pub description_line: usize,
    pub settings: Vec<Arg>,
    pub param_tree: Option<Vec<ParamTreeItem>>,
    pub output_tree: Option<Vec<ParamTreeItem>>,
    /// `graph attribute_or<T: Float | Vector>(…)`: a template, built once for each type it is called with
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub type_params: Vec<TypeParam>,
}

impl Graph {
    pub fn tree(&self, side: &str) -> Vec<ParamTreeItem> {
        if side == "INPUT" {
            if let Some(ref pt) = self.param_tree {
                pt.clone()
            } else {
                self.params
                    .iter()
                    .map(|p| ParamTreeItem::Param(p.clone()))
                    .collect()
            }
        } else if let Some(ref ot) = self.output_tree {
            ot.clone()
        } else {
            self.outputs
                .iter()
                .map(|p| ParamTreeItem::Param(p.clone()))
                .collect()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Use {
    pub name: String,
    pub alias: Option<String>,
    pub names: Option<Vec<String>>,
    pub source: Option<String>,
    pub line: usize,
    pub col: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct File {
    pub uses: Vec<Use>,
    pub graphs: Vec<Graph>,
}
