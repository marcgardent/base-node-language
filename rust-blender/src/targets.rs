//! Targets: what a destination accepts (spec/targets.md).
//!
//! A target is one JSON file of `targets/`: the kinds of tree, types, zones and nodes a text may
//! use there, and the translators that carry a text of another target to it. No target is defined
//! from another. The Python package's `python/base_node_blender/targets.py`, rule for rule.
//!
//! ```text
//! check_target(&file, "blender gltf")       -> the Issues outside it, [] when it fits
//! infer(&file)                              -> which targets accept it
//! translate(&file, "blender", "blade")      -> the text renamed for blade
//! ```
//!
//! `blender` is Blender's own, and has a catalog per version of Blender (`targets/blender/<x.y>.json`):
//! `blender@5.3` is one version, `blender` every version `targets/blender.json` promises,
//! `blender@lts` and `blender@latest` aliases for a command line. A word after it is a variant,
//! the shader nodes one consumer accepts: `blender@5.3 gltf`, `blender eevee`.
//!
//! A graph a text calls brings its issues: those of the text, and of the modules it `use`s: the
//! bridges of the target (modules shipped with it), the stdlib (built in, `crate::stdlib`), and
//! with the `_with` functions the modules their resolver finds before the stdlib. A name that is
//! not a target's is an error, [`UnknownTarget`], where Python raises ValueError.

use std::collections::{BTreeMap, HashSet};
use std::fmt;
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use crate::stdlib;
use base_node::ast::{
    key, Arg, AssignValue, Call, Expr, File, Graph, Param, ReturnValue, Stmt, Use as UseLine,
};

/// The targets that are a file of their own, `targets/<name>.json`, sorted by name: every one but
/// `blender`.
const FILES: &[(&str, &str)] = &[
    // One line per target
    ("blade", include_str!("../../targets/blade.json")),
];

/// The target of Blender, `targets/blender.json`: the versions it promises, the LTS, the variants.
const BLENDER: &str = "blender";
const DECLARATION: &str = include_str!("../../targets/blender.json");
/// The files of `targets/blender/` by name, listed by build.rs: the catalog of each version
/// (`5.3`) and the variants (`gltf`).
const BLENDER_FILES: &[(&str, &str)] = &include!(concat!(env!("OUT_DIR"), "/blender_files.rs"));
/// The kinds of tree Blender has. A graph called from a graph of another kind is built in the
/// caller's tree.
const BLENDER_KINDS: [&str; 3] = ["geometry", "shader", "compositor"];
/// The names a command line gives a version it does not write: refused in the `@target` of a text.
const ALIASES: [&str; 2] = ["latest", "lts"];
/// The targets of before the one `blender`, and what to write now.
const RENAMED: [(&str, &str); 5] = [
    ("blender-geometry", "blender"),
    ("blender-gp", "blender"),
    ("blender-shader", "blender"),
    ("blender-compositor", "blender"),
    ("gltf", "blender gltf"),
];

/// The bridges of the targets, by their path in `targets/` (that of the target's `bridges`, which
/// are relative to the target's file).
const BRIDGES: [(&str, &str); 1] = [(
    "blade/blender_interop.bn",
    include_str!("../../targets/blade/blender_interop.bn"),
)];

/// A ramp and curves are the value of a node's property (`color_ramp: Ramp(…)`), not nodes.
const DATA_CALLS: [&str; 3] = ["Ramp", "Curve", "Curves"];

/// Implicit inputs (`p: Vector = Position()`): a setting of the group's interface, not a node.
pub const IMPLICIT: [&str; 6] = [
    "ID",
    "Index",
    "InstanceTransform",
    "Normal",
    "Position",
    "SelfObject",
];
const ARITHMETIC: [&str; 4] = ["+", "-", "*", "/"];
const PRODUCTS: [&str; 5] = ["⋅", "×", "dot", "cross", "·"];
const COMPARISONS: [&str; 6] = ["<", "<=", ">", ">=", "==", "!="];
const LOGIC: [&str; 4] = ["and", "or", "xor", "not"];
// The formulas written as functions (python/base_node_blender/sugar.py)
const MATH_FUNCS: [&str; 28] = [
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "atan2",
    "sinh",
    "cosh",
    "tanh",
    "sqrt",
    "abs",
    "exp",
    "log",
    "pow",
    "min",
    "max",
    "floor",
    "ceil",
    "fract",
    "round",
    "trunc",
    "sign",
    "mod",
    "radians",
    "degrees",
    "smooth_min",
    "smooth_max",
];
const VECTOR_FUNCS: [&str; 16] = [
    "sin",
    "cos",
    "tan",
    "abs",
    "min",
    "max",
    "floor",
    "ceil",
    "fract",
    "sign",
    "mod",
    "length",
    "normalize",
    "dot",
    "cross",
    "distance",
];
const BOOL_FUNCS: [&str; 6] = ["xor", "xnor", "nand", "nor", "imply", "nimply"];

/// A node of a translator: its new name, and the inputs and settings whose names change.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum NodeRename {
    Name(String),
    Full {
        node: String,
        #[serde(default)]
        inputs: BTreeMap<String, String>,
        #[serde(default)]
        settings: BTreeMap<String, String>,
    },
}

impl NodeRename {
    pub fn node(&self) -> &str {
        match self {
            NodeRename::Name(n) => n,
            NodeRename::Full { node, .. } => node,
        }
    }

    /// The name of the named argument `arg` once translated.
    fn arg<'a>(&'a self, arg: &'a str) -> &'a str {
        match self {
            NodeRename::Name(_) => arg,
            NodeRename::Full {
                inputs, settings, ..
            } => inputs
                .get(arg)
                .or_else(|| settings.get(arg))
                .map(String::as_str)
                .unwrap_or(arg),
        }
    }
}

/// How a target takes a text of another target: its kinds, and for each node the node it becomes.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Translator {
    #[serde(default)]
    pub kinds: BTreeMap<String, String>,
    #[serde(default)]
    pub nodes: BTreeMap<String, NodeRename>,
}

/// What one kind of tree accepts, in a target that has several.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tree {
    #[serde(default)]
    pub types: Vec<String>,
    #[serde(default)]
    pub zones: Vec<String>,
    #[serde(default)]
    pub implicit: Vec<String>,
    #[serde(default)]
    pub nodes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Target {
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub kinds: Vec<String>,
    #[serde(default)]
    pub types: Vec<String>,
    #[serde(default)]
    pub zones: Vec<String>,
    #[serde(default)]
    pub implicit: Vec<String>,
    #[serde(default)]
    pub nodes: Vec<String>,
    #[serde(default)]
    pub translators: BTreeMap<String, Translator>,
    #[serde(default)]
    pub bridges: Vec<String>,
    /// The inputs of the nodes its rules name, in order: a positional argument finds its input here.
    #[serde(default)]
    pub inputs: BTreeMap<String, Vec<String>>,
    /// `Node.input` (or `Node.*`, its other inputs) -> the feeds it accepts (spec/targets.md, Rules).
    #[serde(default)]
    pub rules: BTreeMap<String, Vec<String>>,
    /// The outputs of the nodes its rules name, in order: a call taken whole is its first.
    #[serde(default)]
    pub outputs: BTreeMap<String, Vec<String>>,
    /// The settings its rules name, with their defaults: a call that does not write one has its
    /// default.
    #[serde(default)]
    pub settings: BTreeMap<String, BTreeMap<String, Option<String>>>,
    /// `Node.socket` of the colors and vectors: a multiply there is a Mix, a `*` with one a Vector
    /// Math.
    #[serde(default)]
    pub vectors: Vec<String>,
    /// Expressions the rules name as feeds, their placeholders the pattern's `inputs`.
    #[serde(default)]
    pub patterns: BTreeMap<String, Vec<String>>,
    /// The nodes the exporter computes when their inputs are values: a call of one on values is a
    /// value.
    #[serde(default)]
    pub folded: Vec<String>,
    /// Node groups the destination reads as nodes: the start of the group's name -> the node of
    /// the rules.
    #[serde(default)]
    pub groups: BTreeMap<String, String>,
    /// The nodes the destination reads one of: the last the material reaches.
    #[serde(default)]
    pub once: Vec<String>,
    /// Of a target that has several kinds of tree, what each accepts. A graph is checked against
    /// the tree of its kind, and the graphs it calls with it: they are built in that tree.
    #[serde(default)]
    pub trees: BTreeMap<String, Tree>,
    /// Of a variant of `blender`: the nodes of its kinds it does not accept, each with where that
    /// is said.
    #[serde(default)]
    pub without: BTreeMap<String, String>,
    /// A variant whose list is not settled yet.
    #[serde(default)]
    pub experimental: bool,
    /// Of a name that stands for several versions (`blender`): the target of each. A text fits
    /// when it fits each of them. Not a field of the JSON.
    #[serde(skip)]
    pub members: Vec<Target>,
}

impl Target {
    /// A target read from its JSON.
    pub fn from_json(json: &str) -> Result<Target, String> {
        serde_json::from_str(json).map_err(|e| e.to_string())
    }

    /// Whether it accepts one of `names`, of a kind of thing. Of a target with a tree per kind:
    /// the kinds a text's graph may be, those a called graph may be (it is built in the caller's
    /// tree), and for the rest what the tree of kind `tree` has, or any tree for a kind the target
    /// has no tree of.
    fn accepts(&self, what: &str, tree: &str, called: bool, names: &[String]) -> bool {
        let any = |list: &[String]| names.iter().any(|n| list.contains(n));
        if !self.trees.is_empty() {
            if what == "kind" {
                return if called {
                    names.iter().any(|n| BLENDER_KINDS.contains(&n.as_str()))
                } else {
                    any(&self.kinds)
                };
            }
            let of = |t: &Tree| match what {
                "type" => any(&t.types),
                "zone" => any(&t.zones),
                "implicit" => any(&t.implicit),
                _ => any(&t.nodes),
            };
            return match self.trees.get(tree) {
                Some(t) => of(t),
                None => self.trees.values().any(of),
            };
        }
        match what {
            "kind" => any(&self.kinds),
            "type" => any(&self.types),
            "zone" => any(&self.zones),
            "implicit" => any(&self.implicit),
            _ => any(&self.nodes),
        }
    }
}

/// `targets/blender.json`.
#[derive(Default, Deserialize)]
struct Declaration {
    #[serde(default)]
    lts: Vec<String>,
    #[serde(default)]
    promised: Vec<String>,
    #[serde(default)]
    variants: Vec<String>,
}

/// `targets/blender/<x.y>.json`: what one version of Blender reports, by kind of tree.
#[derive(Deserialize)]
struct Catalog {
    blender: String,
    trees: BTreeMap<String, Tree>,
}

/// The `blender` target: the versions there is a catalog of (the oldest first), those promised,
/// the LTS, the variants, and the target of each name a text may write.
struct Blender {
    versions: Vec<String>,
    promised: Vec<String>,
    lts: Vec<String>,
    variants: Vec<String>,
    names: Vec<String>,
    targets: Vec<Target>,
}

fn version_number(version: &str) -> Vec<u32> {
    version.split('.').filter_map(|x| x.parse().ok()).collect()
}

/// Whether `text` is a version of Blender as a catalog is named: `5.3`.
fn is_version(text: &str) -> bool {
    let digits = |x: &str| !x.is_empty() && x.chars().all(|c| c.is_ascii_digit());
    text.split_once('.')
        .is_some_and(|(a, b)| digits(a) && digits(b))
}

fn blender_file(name: &str) -> &'static str {
    BLENDER_FILES
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, json)| *json)
        .unwrap_or_else(|| panic!("no targets/blender/{name}.json"))
}

impl Blender {
    fn read() -> Blender {
        let d: Declaration = serde_json::from_str(DECLARATION)
            .unwrap_or_else(|e| panic!("targets/blender.json is not the blender target: {e}"));
        let by_number = |mut list: Vec<String>| {
            list.sort_by_key(|v| version_number(v));
            list
        };
        let versions = by_number(
            BLENDER_FILES
                .iter()
                .filter(|(n, _)| is_version(n))
                .map(|(n, _)| (*n).to_owned())
                .collect(),
        );
        let mut variants = d.variants;
        variants.sort();
        let mut b = Blender {
            versions,
            promised: by_number(d.promised),
            lts: by_number(d.lts),
            variants,
            names: Vec::new(),
            targets: Vec::new(),
        };
        b.names = std::iter::once(BLENDER.to_owned())
            .chain(b.versions.iter().map(|v| b.name(v)))
            .collect();
        let variants: Vec<Option<String>> = std::iter::once(None)
            .chain(b.variants.iter().cloned().map(Some))
            .collect();
        for variant in &variants {
            let variant = variant.as_deref();
            let one: Vec<(String, Target)> = b
                .versions
                .iter()
                .map(|v| (v.clone(), b.one(v, variant)))
                .collect();
            let members: Vec<Target> = one
                .iter()
                .filter(|(v, _)| b.promised.contains(v))
                .map(|(_, t)| t.clone())
                .collect();
            b.targets.push(b.group(variant, members));
            b.targets.extend(one.into_iter().map(|(_, t)| t));
        }
        b
    }

    /// A version as a text names it: an LTS says so.
    fn name(&self, version: &str) -> String {
        if self.lts.iter().any(|v| v == version) {
            format!("{BLENDER}@{version}-lts")
        } else {
            format!("{BLENDER}@{version}")
        }
    }

    /// The version `lts` or `latest` stands for today: the newest LTS, the newest catalog.
    fn alias(&self, word: &str) -> Option<&str> {
        let list = if word == "lts" {
            &self.lts
        } else {
            &self.versions
        };
        list.last().map(String::as_str)
    }

    fn variant(name: &str) -> Target {
        Target::from_json(blender_file(name))
            .unwrap_or_else(|e| panic!("targets/blender/{name}.json is not a variant: {e}"))
    }

    /// The target of one version, whole or of a variant.
    fn one(&self, version: &str, variant: Option<&str>) -> Target {
        let catalog: Catalog = serde_json::from_str(blender_file(version))
            .unwrap_or_else(|e| panic!("targets/blender/{version}.json is not a catalog: {e}"));
        let Some(variant) = variant else {
            return Target {
                name: self.name(version),
                description: format!("Every node of Blender {}, by kind of tree", catalog.blender),
                kinds: BLENDER_KINDS
                    .iter()
                    .filter(|k| catalog.trees.contains_key(**k))
                    .map(|k| (*k).to_owned())
                    .collect(),
                trees: catalog.trees,
                ..Target::default()
            };
        };
        let mut t = Blender::variant(variant);
        t.name = format!("{} {variant}", self.name(version));
        t.description = format!("{}, in Blender {}", t.description, catalog.blender);
        if !t.nodes.is_empty() {
            // A list of its own: the nodes of it this version has
            let kinds = t.kinds.clone();
            t.nodes.retain(|n| {
                kinds
                    .iter()
                    .filter_map(|k| catalog.trees.get(k))
                    .any(|tree| tree.nodes.contains(n))
            });
        } else {
            for k in &t.kinds {
                if let Some(tree) = catalog.trees.get(k) {
                    let mut tree = tree.clone();
                    tree.nodes.retain(|n| !t.without.contains_key(n));
                    t.trees.insert(k.clone(), tree);
                }
            }
        }
        t
    }

    /// The target of every promised version, whole or of a variant.
    fn group(&self, variant: Option<&str>, members: Vec<Target>) -> Target {
        let said = match variant {
            Some(v) => Blender::variant(v).description,
            None => "Every node of Blender, by kind of tree".to_owned(),
        };
        Target {
            name: match variant {
                Some(v) => format!("{BLENDER} {v}"),
                None => BLENDER.to_owned(),
            },
            description: format!(
                "{said}, in every version of Blender this version of Base Node promises: {}",
                self.promised.join(", ")
            ),
            kinds: members.first().map(|m| m.kinds.clone()).unwrap_or_default(),
            experimental: members.first().is_some_and(|m| m.experimental),
            members,
            ..Target::default()
        }
    }

    fn known(&self) -> String {
        if self.versions.is_empty() {
            "catalogs: none".to_owned()
        } else {
            format!("catalogs: {}", self.versions.join(", "))
        }
    }

    /// Why `blender@version words` names no target, none when it names one.
    fn refusal(&self, version: Option<&str>, words: &[&str]) -> Option<Refusal> {
        if words.len() > 1 {
            return Some(Refusal::Unknown(Some(format!(
                "one variant after the target, as '{BLENDER} {}'",
                words[0]
            ))));
        }
        if words
            .first()
            .is_some_and(|w| !self.variants.iter().any(|v| v == w))
        {
            return Some(Refusal::Unknown(None));
        }
        let version = version?;
        let number = if ALIASES.contains(&version) {
            match self.alias(version) {
                Some(n) => n,
                None => {
                    return Some(Refusal::Catalog(format!(
                        "no LTS of Blender in this version of Base Node ({})",
                        self.known()
                    )))
                }
            }
        } else {
            let number = version.strip_suffix("-lts").unwrap_or(version);
            if !is_version(number) {
                return Some(Refusal::Unknown(None));
            }
            number
        };
        if !self.versions.iter().any(|v| v == number) {
            return Some(Refusal::Catalog(format!(
                "no catalog for Blender {number} in this version of Base Node ({})",
                self.known()
            )));
        }
        if !ALIASES.contains(&version) && format!("{BLENDER}@{version}") != self.name(number) {
            let lts = if self.lts.iter().any(|v| v == number) {
                "an LTS"
            } else {
                "not an LTS"
            };
            return Some(Refusal::Unknown(Some(format!(
                "Blender {number} is {lts}: write '{}'",
                self.name(number)
            ))));
        }
        None
    }
}

/// Why a name names no target: it is unknown (with what to write, when that is known), or the
/// version it names has no catalog.
enum Refusal {
    Unknown(Option<String>),
    Catalog(String),
}

fn blender() -> &'static Blender {
    static ALL: OnceLock<Blender> = OnceLock::new();
    ALL.get_or_init(Blender::read)
}

/// The targets that are a file of their own: every one but `blender`.
fn others() -> &'static [Target] {
    static ALL: OnceLock<Vec<Target>> = OnceLock::new();
    ALL.get_or_init(|| {
        FILES
            .iter()
            .map(|(name, json)| {
                Target::from_json(json)
                    .unwrap_or_else(|e| panic!("targets/{name}.json is not a target: {e}"))
            })
            .collect()
    })
}

/// Every target a name may stand for.
fn targets() -> impl Iterator<Item = &'static Target> {
    others().iter().chain(blender().targets.iter())
}

fn sorted(mut names: Vec<&'static str>) -> Vec<&'static str> {
    names.sort();
    names
}

/// Every target, sorted: `blender` and each of its versions among them, without their variants.
pub fn target_names() -> Vec<&'static str> {
    sorted(
        others()
            .iter()
            .map(|t| t.name.as_str())
            .chain(blender().names.iter().map(String::as_str))
            .collect(),
    )
}

/// The variants of `blender`, sorted: a word after the target, as `blender gltf`.
pub fn variant_names() -> Vec<&'static str> {
    blender().variants.iter().map(String::as_str).collect()
}

/// Every name a text may promise, sorted: the targets, and `blender` with each variant.
pub fn promise_names() -> Vec<&'static str> {
    sorted(targets().map(|t| t.name.as_str()).collect())
}

/// The targets an inference tries, sorted: `blender` as the versions promised, whole and by
/// variant, and the others.
pub fn inferred_names() -> Vec<&'static str> {
    sorted(
        targets()
            .map(|t| t.name.as_str())
            .filter(|n| !n.contains('@'))
            .collect(),
    )
}

/// A target as it is written: a name, a version after `@`, words after a space. What they mean
/// is the target's to say.
fn spelling(name: &str) -> Option<(&str, Option<&str>, Vec<&str>)> {
    let word = |w: &str, more: &str| {
        !w.is_empty()
            && w.chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || more.contains(c))
    };
    let mut parts = name.split(' ');
    let head = parts.next()?;
    let words: Vec<&str> = parts.collect();
    if !words.iter().all(|w| word(w, "_-")) {
        return None;
    }
    let (name, version) = match head.split_once('@') {
        Some((n, v)) => (n, Some(v)),
        None => (head, None),
    };
    let bare = word(name, "_-") && !name.starts_with(['_', '-']);
    let versioned = version.is_none_or(|v| {
        !v.is_empty()
            && v.chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
    });
    (bare && versioned).then_some((name, version, words))
}

fn refusal(name: &str) -> Option<Refusal> {
    let mut hint = None;
    match spelling(name) {
        Some((BLENDER, version, words)) => match blender().refusal(version, &words) {
            Some(Refusal::Unknown(h)) => hint = h,
            other => return other,
        },
        Some((n, None, words)) if words.is_empty() && others().iter().any(|t| t.name == n) => {
            return None
        }
        _ => {}
    }
    if let Some((_, now)) = RENAMED.iter().find(|(old, _)| *old == name) {
        hint = Some(format!("'{name}' is now '{now}'"));
    }
    Some(Refusal::Unknown(hint))
}

/// The targets there are, as a message lists them, with what to write for `hint`.
fn listed(hint: Option<String>) -> String {
    let mut said = target_names().join(", ");
    if !blender().variants.is_empty() {
        said += &format!(
            "; variants of {BLENDER}, written after it: {}",
            blender().variants.join(", ")
        );
    }
    if let Some(hint) = hint {
        said += &format!("; {hint}");
    }
    said
}

/// Why a text may not promise `name` in its `@target`, none when it may: what follows
/// `@target '<name>': ` in the message. An alias is the command line's.
pub fn promise_refusal(name: &str) -> Option<String> {
    if let Some((BLENDER, Some(version), words)) = spelling(name) {
        if ALIASES.contains(&version) {
            let b = blender();
            let write = match b
                .alias(version)
                .filter(|n| b.versions.iter().any(|v| v == n))
            {
                Some(number) => {
                    let words: String = words.iter().map(|w| format!(" {w}")).collect();
                    format!(": write the version, '{}{words}'", b.name(number))
                }
                None => String::new(),
            };
            return Some(format!(
                "an alias, for a command line: the version it names changes with each release \
                 of Blender, and the promise of the text would change with it{write}"
            ));
        }
    }
    match refusal(name)? {
        Refusal::Unknown(hint) => Some(format!("one of {}", listed(hint))),
        Refusal::Catalog(why) => Some(why),
    }
}

/// A name that is not a target's.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnknownTarget(pub String);

impl fmt::Display for UnknownTarget {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match refusal(&self.0) {
            Some(Refusal::Catalog(why)) => write!(f, "target '{}': {why}", self.0),
            Some(Refusal::Unknown(hint)) => {
                write!(f, "unknown target '{}'; targets: {}", self.0, listed(hint))
            }
            None => write!(f, "unknown target '{}'; targets: {}", self.0, listed(None)),
        }
    }
}

impl std::error::Error for UnknownTarget {}

/// The target `name`: of `blender`, one version, every promised one, or the one an alias names.
pub fn load_target(name: &str) -> Result<&'static Target, UnknownTarget> {
    let mut wanted = name.to_owned();
    if let Some((BLENDER, Some(version), words)) = spelling(name) {
        if let Some(number) = ALIASES
            .contains(&version)
            .then(|| blender().alias(version))
            .flatten()
        {
            let words: String = words.iter().map(|w| format!(" {w}")).collect();
            wanted = format!("{}{words}", blender().name(number));
        }
    }
    targets()
        .find(|t| t.name == wanted)
        .ok_or_else(|| UnknownTarget(name.to_owned()))
}

/// The module a bridge is: its file name without `.bn`.
fn bridge_name(path: &str) -> &str {
    let file = path.rsplit('/').next().unwrap_or(path);
    file.strip_suffix(".bn").unwrap_or(file)
}

/// Something a text uses outside a target, where it is.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Issue {
    pub graph: String,
    /// kind, type, zone, implicit, node, graph
    pub what: String,
    pub name: String,
    pub line: usize,
    pub col: usize,
    pub target: String,
}

impl fmt::Display for Issue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Graph '{}': {} '{}' outside target '{}' (line {})",
            self.graph, self.what, self.name, self.target, self.line
        )
    }
}

/// What a graph needs of a target; one of `names` is enough (`+` is Math or Vector Math).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Use {
    pub what: &'static str,
    pub names: Vec<String>,
    pub line: usize,
    pub col: usize,
}

impl Use {
    fn new(what: &'static str, names: &[&str], line: usize, col: usize) -> Self {
        Use {
            what,
            names: names.iter().map(|n| (*n).to_owned()).collect(),
            line,
            col,
        }
    }

    pub fn name(&self) -> String {
        self.names.join(" or ")
    }
}

/// Finds module `name` of a `use` line, parsed; none when it is not found.
pub type Resolver<'a> = &'a dyn Fn(&str) -> Option<File>;

// ---- What a graph uses ----

#[derive(Clone, Copy, PartialEq, Eq)]
enum Found {
    Call,
    Op,
    Zone,
}

/// A call with a body is a zone when its name is one's; else a call no target knows.
fn zone_or_call(name: &str) -> Found {
    if crate::zones::call_word(name).is_some() {
        Found::Zone
    } else {
        Found::Call
    }
}

struct Walk(Vec<(Found, String, usize, usize)>);

impl Walk {
    fn push(&mut self, f: Found, name: &str, line: usize, col: usize) {
        self.0.push((f, name.to_owned(), line, col));
    }

    fn stmts(&mut self, body: &[Stmt]) {
        for s in body {
            self.stmt(s);
        }
    }

    fn stmt(&mut self, s: &Stmt) {
        match s {
            Stmt::Assign(a) => match &a.value {
                AssignValue::Expr(e) => self.expr(e),
                AssignValue::BodyCall(z) => {
                    self.push(zone_or_call(&z.name), &z.name, z.line, z.col);
                    self.args(&z.args);
                    self.stmts(&z.body);
                }
                AssignValue::NamelessGraph(z) => {
                    self.push(Found::Zone, "closure", z.line, z.col);
                    self.params(&z.params);
                    self.params(&z.outputs);
                    self.stmts(&z.body);
                }
            },
            Stmt::Return(r) => match &r.value {
                ReturnValue::Expr(e) => self.expr(e),
                ReturnValue::Record(rec) => self.args(&rec.fields),
            },
            Stmt::Frame(f) => self.stmts(&f.body),
        }
    }

    fn args(&mut self, args: &[Arg]) {
        for a in args {
            self.expr(&a.value);
            self.args(&a.options);
            if let Some(p) = &a.type_decl {
                self.param(p);
            }
        }
    }

    fn params(&mut self, params: &[Param]) {
        for p in params {
            self.param(p);
        }
    }

    fn param(&mut self, p: &Param) {
        if let Some(d) = &p.default {
            self.expr(d);
        }
        if let Some((lo, hi)) = &p.range {
            for e in [lo, hi].into_iter().flatten() {
                self.expr(e);
            }
        }
        self.args(&p.options);
    }

    fn expr(&mut self, e: &Expr) {
        match e {
            Expr::Call(c) => {
                self.push(Found::Call, &c.name, c.line, c.col);
                self.args(&c.args);
                if let Some(outs) = &c.outputs {
                    self.params(outs);
                }
            }
            Expr::BinOp(b) => {
                self.push(Found::Op, &b.op, b.line, b.col);
                self.expr(&b.left);
                self.expr(&b.right);
            }
            Expr::Neg(n) => {
                self.push(Found::Op, "-", n.line, n.col);
                self.expr(&n.value);
            }
            Expr::Not(n) => {
                self.push(Found::Op, "not", n.line, n.col);
                self.expr(&n.value);
            }
            Expr::Cond(c) => {
                self.push(Found::Op, "?", c.line, c.col);
                self.expr(&c.cond);
                self.expr(&c.then);
                self.expr(&c.orelse);
            }
            Expr::Pipe(p) => {
                self.expr(&p.left);
                self.expr(&p.call);
            }
            Expr::Member(m) => self.expr(&m.target),
            Expr::Tuple(t) => {
                for i in &t.items {
                    self.expr(i);
                }
            }
            Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
        }
    }
}

fn walk_body(body: &[Stmt]) -> Vec<(Found, String, usize, usize)> {
    let mut w = Walk(Vec::new());
    w.stmts(body);
    w.0
}

/// Names a call may give that are not nodes: the graphs of the text and what its uses import,
/// the modules it uses, and whether one imports every graph of its module.
struct Local {
    names: HashSet<String>,
    modules: HashSet<String>,
    every: bool,
}

/// A use of every graph of a module `find` finds imports its graphs; of one it does not find, any
/// name (`every`).
fn local_names(file: &File, find: &dyn Fn(&str) -> Option<Rc<File>>) -> Local {
    let mut names = HashSet::new();
    let mut modules = HashSet::new();
    let mut every = false;
    for g in &file.graphs {
        names.insert(g.name.clone());
        names.insert(key(&g.name));
    }
    for u in &file.uses {
        modules.insert(u.alias.clone().unwrap_or_else(|| u.name.clone()));
        modules.insert(u.name.clone());
        match &u.names {
            Some(ns) => names.extend(ns.iter().cloned()),
            None => match find(&u.name) {
                Some(m) => names.extend(m.graphs.iter().map(|g| key(&g.name))),
                None => every = true,
            },
        }
    }
    Local {
        names,
        modules,
        every,
    }
}

/// What `graph` of `file` needs of a target: its kind, types, implicit inputs, zones and nodes.
/// The modules it uses are looked for in the stdlib.
pub fn uses(graph: &Graph, file: &File) -> Vec<Use> {
    let modules = Modules::new(None);
    let local = local_names(file, &|n| modules.get(n));
    uses_of(graph, &local, &graph.kind)
}

/// The names the statements bind, in frames and zones too.
fn assigned(body: &[Stmt], out: &mut HashSet<String>) {
    for s in body {
        match s {
            Stmt::Assign(a) => {
                out.insert(a.name.clone());
                match &a.value {
                    AssignValue::Expr(_) => {}
                    AssignValue::BodyCall(z) => assigned(&z.body, out),
                    AssignValue::NamelessGraph(z) => assigned(&z.body, out),
                }
            }
            Stmt::Frame(f) => assigned(&f.body, out),
            Stmt::Return(_) => {}
        }
    }
}

/// What `graph` needs of a target. `tree` is the kind of the tree it is built in: a ternary is the
/// node of that tree.
fn uses_of(graph: &Graph, local: &Local, tree: &str) -> Vec<Use> {
    let mut out = vec![Use::new("kind", &[&graph.kind], graph.line, graph.col)];
    // The parser opens the panels: these are every input and output
    let params = &graph.params;
    for p in params.iter().chain(graph.outputs.iter()) {
        out.push(Use::new("type", &[&p.type_name], p.line, p.col));
    }
    for p in params {
        if let Some(Expr::Call(c)) = &p.default {
            if c.args.is_empty() && IMPLICIT.contains(&c.name.as_str()) {
                out.push(Use::new("implicit", &[&c.name], p.line, p.col));
            }
        }
    }
    // A call on a name the graph binds evaluates the closure it holds
    let mut bound = HashSet::new();
    assigned(&graph.body, &mut bound);
    for (found, name, line, col) in walk_body(&graph.body) {
        let n = name.as_str();
        match found {
            Found::Zone => out.push(Use::new("zone", &[n], line, col)),
            Found::Op => {
                let nodes: &[&str] = if ARITHMETIC.contains(&n) {
                    &["Math", "VectorMath"]
                } else if PRODUCTS.contains(&n) {
                    &["VectorMath"]
                } else if COMPARISONS.contains(&n) {
                    // Compare where the tree has one, else Math (a shader tree)
                    &["Compare", "Math"]
                } else if LOGIC.contains(&n) {
                    &["BooleanMath"]
                } else if n == "?" {
                    // A Switch where it chooses for each element, else a Mix by the condition
                    if tree == "geometry" {
                        &["Switch"]
                    } else {
                        &["Mix", "MixShader"]
                    }
                } else {
                    &[]
                };
                if !nodes.is_empty() {
                    out.push(Use::new("node", nodes, line, col));
                }
            }
            Found::Call => {
                if let Some((module, _)) = n.split_once("::") {
                    if !local.modules.contains(module) {
                        out.push(Use::new("node", &[n], line, col));
                    }
                } else if bound.contains(n) && !local.names.contains(n) {
                    out.push(Use::new("node", &["EvaluateClosure"], line, col));
                } else if local.names.contains(n) || local.every || DATA_CALLS.contains(&n) {
                    continue;
                } else if BOOL_FUNCS.contains(&n) {
                    out.push(Use::new("node", &["BooleanMath"], line, col));
                } else if MATH_FUNCS.contains(&n) || VECTOR_FUNCS.contains(&n) {
                    let nodes: Vec<&str> =
                        [("Math", &MATH_FUNCS[..]), ("VectorMath", &VECTOR_FUNCS[..])]
                            .iter()
                            .filter(|(_, d)| d.contains(&n))
                            .map(|(node, _)| *node)
                            .collect();
                    out.push(Use::new("node", &nodes, line, col));
                } else {
                    out.push(Use::new("node", &[n], line, col));
                }
            }
        }
    }
    out
}

/// The modules a check finds, each read once: the resolver's, the stdlib's, the bridges.
struct Modules<'a> {
    resolve: Option<Resolver<'a>>,
    found: RefCell<HashMap<String, Option<Rc<File>>>>,
    bridges: RefCell<HashMap<String, Option<Rc<File>>>>,
}

impl<'a> Modules<'a> {
    fn new(resolve: Option<Resolver<'a>>) -> Self {
        Modules {
            resolve,
            found: RefCell::new(HashMap::new()),
            bridges: RefCell::new(HashMap::new()),
        }
    }

    /// Module `name`: the resolver's, else the stdlib's.
    fn get(&self, name: &str) -> Option<Rc<File>> {
        self.found
            .borrow_mut()
            .entry(name.to_owned())
            .or_insert_with(|| {
                self.resolve
                    .and_then(|r| r(name))
                    .or_else(|| stdlib::module(name))
                    .map(Rc::new)
            })
            .clone()
    }

    /// The bridge `name` of `target`, none when it has none of that name.
    fn bridge(&self, target: &Target, name: &str) -> Option<Rc<File>> {
        let path = target.bridges.iter().find(|p| bridge_name(p) == name)?;
        self.bridges
            .borrow_mut()
            .entry(path.clone())
            .or_insert_with(|| {
                let (_, text) = BRIDGES.iter().find(|(p, _)| p == path)?;
                base_node::parse(text, path).ok().map(Rc::new)
            })
            .clone()
    }

    /// Module `name` as a check against `target` finds it: its bridge, else the resolver's or the
    /// stdlib's.
    fn find(&self, target: &Target, name: &str) -> Option<Rc<File>> {
        self.bridge(target, name).or_else(|| self.get(name))
    }
}

/// (its file, its index) for each graph of the text or of a module it uses that graph `at` calls.
fn callees(
    file: &Rc<File>,
    at: usize,
    target: &Target,
    modules: &Modules,
) -> Vec<(Rc<File>, usize)> {
    let called: HashSet<String> = walk_body(&file.graphs[at].body)
        .into_iter()
        .filter(|(f, ..)| *f == Found::Call)
        .map(|(_, n, ..)| n)
        .collect();
    let mut out = Vec::new();
    for (i, g) in file.graphs.iter().enumerate() {
        if i != at && (called.contains(&g.name) || called.contains(&key(&g.name))) {
            out.push((file.clone(), i));
        }
    }
    for u in &file.uses {
        let Some(m) = modules.find(target, &u.name) else {
            continue;
        };
        let prefix = u.alias.as_deref().unwrap_or(&u.name);
        for (i, g) in m.graphs.iter().enumerate() {
            let k = key(&g.name);
            let imported = u.names.as_ref().is_none_or(|ns| ns.contains(&k));
            if (imported && called.contains(&k)) || called.contains(&format!("{prefix}::{k}")) {
                out.push((m.clone(), i));
            }
        }
    }
    out
}

fn graph_issues_in(
    file: &Rc<File>,
    at: usize,
    target: &Target,
    modules: &Modules,
    seen: &HashSet<(usize, usize)>,
    tree: Option<&str>,
) -> Vec<Issue> {
    if !target.members.is_empty() {
        let per = target
            .members
            .iter()
            .map(|m| graph_issues_in(file, at, m, modules, seen, tree))
            .collect();
        return every(target, per);
    }
    let graph = &file.graphs[at];
    let local = local_names(file, &|n| modules.find(target, n));
    // The tree it is built in: its own, or its caller's
    let called = tree.is_some();
    let tree = tree.unwrap_or(&graph.kind);
    let mut out = Vec::new();
    for u in uses_of(graph, &local, tree) {
        if !target.accepts(u.what, tree, called, &u.names) {
            out.push(Issue {
                graph: graph.name.clone(),
                what: u.what.to_owned(),
                name: u.name(),
                line: u.line,
                col: u.col,
                target: target.name.clone(),
            });
        }
    }
    let read = inlined(file, at, target, modules);
    out.extend(link_issues_of(&read, Some(file), target, &local.names));
    let mut seen = seen.clone();
    seen.insert((Rc::as_ptr(file) as usize, at));
    for (f, i) in callees(file, at, target, modules) {
        if seen.contains(&(Rc::as_ptr(&f) as usize, i)) {
            continue;
        }
        // Its links are read where it is called, through the values the call gives
        let inner: Vec<Issue> = graph_issues_in(&f, i, target, modules, &seen, Some(tree))
            .into_iter()
            .filter(|i| i.what != "link")
            .collect();
        if let Some(first) = inner.first() {
            out.push(Issue {
                graph: graph.name.clone(),
                what: "graph".to_owned(),
                name: format!("{} ({} {})", key(&f.graphs[i].name), first.what, first.name),
                line: first.line,
                col: first.col,
                target: target.name.clone(),
            });
        }
    }
    out
}

/// The issues of the versions of `target`, each once: one that every version has is the
/// target's, one that some have is each of theirs.
fn every(target: &Target, per: Vec<Vec<Issue>>) -> Vec<Issue> {
    let same = |a: &Issue, b: &Issue| {
        (&a.graph, &a.what, &a.name, a.line, a.col) == (&b.graph, &b.what, &b.name, b.line, b.col)
    };
    let shared = |i: &Issue| per.iter().all(|issues| issues.iter().any(|j| same(i, j)));
    let mut out = Vec::new();
    for (n, issues) in per.iter().enumerate() {
        for i in issues {
            if !shared(i) {
                out.push(i.clone());
            } else if n == 0 {
                out.push(Issue {
                    target: target.name.clone(),
                    ..i.clone()
                });
            }
        }
    }
    out
}

fn issues_of(file: &Rc<File>, target: &Target, modules: &Modules) -> Vec<Issue> {
    (0..file.graphs.len())
        .flat_map(|i| graph_issues_in(file, i, target, modules, &HashSet::new(), None))
        .collect()
}

/// The Issues of graph `at` of `file` outside `target`, with those of the graphs it calls.
pub fn graph_issues(
    file: &File,
    at: usize,
    target: &Target,
    resolve: Option<Resolver>,
) -> Vec<Issue> {
    graph_issues_in(
        &Rc::new(file.clone()),
        at,
        target,
        &Modules::new(resolve),
        &HashSet::new(),
        None,
    )
}

/// The Issues of the text outside `target`: [] when every graph fits it.
pub fn check_target(file: &File, target: &str) -> Result<Vec<Issue>, UnknownTarget> {
    Ok(check_against(file, load_target(target)?, None))
}

/// The same, the modules the text uses found by `resolve` first, then in the stdlib.
pub fn check_target_with(
    file: &File,
    target: &str,
    resolve: Resolver,
) -> Result<Vec<Issue>, UnknownTarget> {
    Ok(check_against(file, load_target(target)?, Some(resolve)))
}

/// The Issues of the text outside a target of its own (`Target::from_json`).
pub fn check_against(file: &File, target: &Target, resolve: Option<Resolver>) -> Vec<Issue> {
    issues_of(&Rc::new(file.clone()), target, &Modules::new(resolve))
}

/// The kinds of tree of `target` every graph of the text builds in, as a graph of that kind calls
/// it: a text of math builds in a geometry tree and in the compositor, whatever its graphs are
/// declared as; one that scatters points, in a geometry tree only.
pub fn tree_kinds(file: &File, target: &str) -> Result<Vec<String>, UnknownTarget> {
    let target = load_target(target)?;
    let file = Rc::new(file.clone());
    let modules = Modules::new(None);
    let builds = |kind: &str| {
        (0..file.graphs.len()).all(|i| {
            graph_issues_in(&file, i, target, &modules, &HashSet::new(), Some(kind)).is_empty()
        })
    };
    Ok(target.kinds.iter().filter(|k| builds(k)).cloned().collect())
}

/// The Issues of the graphs that fit none of `targets` (a text may promise several, one per graph).
pub fn check_targets(file: &File, targets: &[&str]) -> Result<Vec<Issue>, UnknownTarget> {
    check_targets_in(file, targets, None)
}

/// The same, the modules the text uses found by `resolve` first, then in the stdlib.
pub fn check_targets_with(
    file: &File,
    targets: &[&str],
    resolve: Resolver,
) -> Result<Vec<Issue>, UnknownTarget> {
    check_targets_in(file, targets, Some(resolve))
}

fn check_targets_in(
    file: &File,
    targets: &[&str],
    resolve: Option<Resolver>,
) -> Result<Vec<Issue>, UnknownTarget> {
    let targets = targets
        .iter()
        .map(|t| load_target(t))
        .collect::<Result<Vec<_>, _>>()?;
    let file = Rc::new(file.clone());
    let modules = Modules::new(resolve);
    let mut out = Vec::new();
    for i in 0..file.graphs.len() {
        let per: Vec<Vec<Issue>> = targets
            .iter()
            .map(|t| graph_issues_in(&file, i, t, &modules, &HashSet::new(), None))
            .collect();
        if !per.is_empty() && per.iter().all(|p| !p.is_empty()) {
            // The first of the shortest, as Python's min
            let mut best = &per[0];
            for p in &per {
                if p.len() < best.len() {
                    best = p;
                }
            }
            out.extend(best.iter().cloned());
        }
    }
    Ok(out)
}

// ---- Rules: what may feed what ----

const TIMES: &str = "×";
/// The inputs of a Material Output, which a material's return feeds.
const MATERIAL_SOCKETS: [&str; 4] = ["surface", "volume", "displacement", "thickness"];
/// The inputs text names by a key of their own (python/base_node_blender/schema.py, INPUT_KEYS):
/// Blender's identifier, which a call may still write, is read as that key.
fn identifier_key<'a>(node: &str, name: &'a str) -> &'a str {
    match (node, name) {
        ("MixShader" | "AddShader", "Shader") => "a",
        ("MixShader" | "AddShader", "Shader_001") => "b",
        _ => name,
    }
}

/// The operation a formula writes (python/base_node_blender/sugar.py).
const BINOPS: [(&str, &str); 4] = [
    ("+", "ADD"),
    ("-", "SUBTRACT"),
    ("*", "MULTIPLY"),
    ("/", "DIVIDE"),
];
const MATH_OPS: [(&str, &str); 28] = [
    ("sin", "SINE"),
    ("cos", "COSINE"),
    ("tan", "TANGENT"),
    ("asin", "ARCSINE"),
    ("acos", "ARCCOSINE"),
    ("atan", "ARCTANGENT"),
    ("atan2", "ARCTAN2"),
    ("sinh", "SINH"),
    ("cosh", "COSH"),
    ("tanh", "TANH"),
    ("sqrt", "SQRT"),
    ("abs", "ABSOLUTE"),
    ("exp", "EXPONENT"),
    ("log", "LOGARITHM"),
    ("pow", "POWER"),
    ("min", "MINIMUM"),
    ("max", "MAXIMUM"),
    ("smooth_min", "SMOOTH_MIN"),
    ("smooth_max", "SMOOTH_MAX"),
    ("floor", "FLOOR"),
    ("ceil", "CEIL"),
    ("fract", "FRACT"),
    ("round", "ROUND"),
    ("trunc", "TRUNC"),
    ("sign", "SIGN"),
    ("mod", "MODULO"),
    ("radians", "RADIANS"),
    ("degrees", "DEGREES"),
];
const VECTOR_OPS: [(&str, &str); 16] = [
    ("sin", "SINE"),
    ("cos", "COSINE"),
    ("tan", "TANGENT"),
    ("abs", "ABSOLUTE"),
    ("min", "MINIMUM"),
    ("max", "MAXIMUM"),
    ("floor", "FLOOR"),
    ("ceil", "CEIL"),
    ("fract", "FRACTION"),
    ("sign", "SIGN"),
    ("mod", "MODULO"),
    ("length", "LENGTH"),
    ("normalize", "NORMALIZE"),
    ("dot", "DOT_PRODUCT"),
    ("cross", "CROSS_PRODUCT"),
    ("distance", "DISTANCE"),
];

fn op_of(table: &[(&str, &'static str)], name: &str) -> Option<&'static str> {
    table.iter().find(|(k, _)| *k == name).map(|(_, v)| *v)
}

/// A feed of a rule as (core, the factors around it): `ImageTexture × constant` ->
/// ("ImageTexture", ["constant"]).
fn pattern(text: &str) -> (&str, Vec<&str>) {
    let mut terms = text.split(TIMES).map(str::trim);
    let core = terms.next().unwrap_or("");
    (core, terms.collect())
}

/// The expression a pattern of a target writes, parsed.
fn expression(text: &str) -> Option<Expr> {
    let src = format!("shader graph pattern() -> Float {{\n  return {text}\n}}\n");
    let file = base_node::parse(&src, "<pattern>").ok()?;
    match file.graphs.first()?.body.last()? {
        Stmt::Return(r) => match &r.value {
            ReturnValue::Expr(e) => Some(e.clone()),
            ReturnValue::Record(_) => None,
        },
        _ => None,
    }
}

/// The node a formula writes, by its operator.
fn formula(op: &str) -> &'static str {
    if ARITHMETIC.contains(&op) {
        "Math"
    } else if PRODUCTS.contains(&op) {
        "VectorMath"
    } else if COMPARISONS.contains(&op) {
        "Compare"
    } else {
        "BooleanMath"
    }
}

/// Whether a feed is a number, `true` or `false`: that value, or an input left to its default.
fn literal(t: &str) -> bool {
    t == "true" || t == "false" || t.parse::<f64>().is_ok()
}

/// Whether a rule on a setting takes that value: one of its feeds, or `any`.
fn takes(feeds: &[String], word: &str) -> bool {
    feeds.iter().any(|f| f == "any" || same_word(f, word))
}

/// The node of the rules a group of that name is read as, none for another group.
fn group_node<'t>(name: &str, groups: &'t BTreeMap<String, String>) -> Option<&'t str> {
    groups
        .iter()
        .find(|(start, _)| name.to_lowercase().starts_with(&start.to_lowercase()))
        .map(|(_, node)| node.as_str())
}

/// The value of a number literal, negated or not.
fn number(e: &Expr) -> Option<f64> {
    match e {
        Expr::Number(n) => Some(n.value),
        Expr::Neg(n) => match &*n.value {
            Expr::Number(n) => Some(-n.value),
            _ => None,
        },
        _ => None,
    }
}

fn same_word(a: &str, b: &str) -> bool {
    a.to_lowercase() == b.to_lowercase()
}

/// What feeds an input: an expression of the text, the result of a zone, or the default of an
/// input the call does not give (a constant).
#[derive(Clone, Copy)]
enum Value<'a> {
    Default,
    Zone,
    Expr(&'a Expr),
}

/// A call of a graph's body, the value piped into it, and the call as a value.
type CallAt<'a> = (&'a Call, Option<&'a Expr>, &'a Expr);

/// Every call of a graph's body, in the order of the text.
struct Calls<'a>(Vec<CallAt<'a>>);

impl<'a> Calls<'a> {
    fn stmts(&mut self, body: &'a [Stmt]) {
        for s in body {
            match s {
                Stmt::Assign(a) => match &a.value {
                    AssignValue::Expr(e) => self.expr(e),
                    AssignValue::BodyCall(z) => {
                        self.args(&z.args);
                        self.stmts(&z.body);
                    }
                    AssignValue::NamelessGraph(z) => {
                        self.params(&z.params);
                        self.params(&z.outputs);
                        self.stmts(&z.body);
                    }
                },
                Stmt::Return(r) => match &r.value {
                    ReturnValue::Expr(e) => self.expr(e),
                    ReturnValue::Record(rec) => self.args(&rec.fields),
                },
                Stmt::Frame(f) => self.stmts(&f.body),
            }
        }
    }

    fn args(&mut self, args: &'a [Arg]) {
        for a in args {
            self.expr(&a.value);
            self.args(&a.options);
            if let Some(p) = &a.type_decl {
                self.param(p);
            }
        }
    }

    fn params(&mut self, params: &'a [Param]) {
        for p in params {
            self.param(p);
        }
    }

    fn param(&mut self, p: &'a Param) {
        if let Some(d) = &p.default {
            self.expr(d);
        }
        self.args(&p.options);
    }

    fn call(&mut self, c: &'a Call, piped: Option<&'a Expr>, whole: &'a Expr) {
        self.0.push((c, piped, whole));
        self.args(&c.args);
        if let Some(outs) = &c.outputs {
            self.params(outs);
        }
    }

    fn expr(&mut self, e: &'a Expr) {
        match e {
            Expr::Call(c) => self.call(c, None, e),
            Expr::Pipe(p) => {
                self.expr(&p.left);
                let call = match &*p.call {
                    Expr::Member(m) => &*m.target,
                    other => other,
                };
                match call {
                    Expr::Call(c) => self.call(c, Some(&p.left), e),
                    _ => self.expr(&p.call),
                }
            }
            Expr::BinOp(b) => {
                self.expr(&b.left);
                self.expr(&b.right);
            }
            Expr::Neg(n) => self.expr(&n.value),
            Expr::Not(n) => self.expr(&n.value),
            Expr::Cond(c) => {
                self.expr(&c.cond);
                self.expr(&c.then);
                self.expr(&c.orelse);
            }
            Expr::Member(m) => self.expr(&m.target),
            Expr::Tuple(t) => {
                for i in &t.items {
                    self.expr(i);
                }
            }
            Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
        }
    }
}

/// The names an expression reads.
fn refs<'a>(e: &'a Expr, out: &mut Vec<&'a Expr>) {
    match e {
        Expr::Ref(_) => out.push(e),
        Expr::Call(c) => {
            for a in &c.args {
                refs(&a.value, out);
            }
        }
        Expr::Pipe(p) => {
            refs(&p.left, out);
            refs(&p.call, out);
        }
        Expr::BinOp(b) => {
            refs(&b.left, out);
            refs(&b.right, out);
        }
        Expr::Neg(n) => refs(&n.value, out),
        Expr::Not(n) => refs(&n.value, out),
        Expr::Cond(c) => {
            refs(&c.cond, out);
            refs(&c.then, out);
            refs(&c.orelse, out);
        }
        Expr::Member(m) => refs(&m.target, out),
        Expr::Tuple(t) => {
            for i in &t.items {
                refs(i, out);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) => {}
    }
}

fn call_id(c: &Call) -> usize {
    c as *const Call as usize
}

/// A node as a feed: its name, the output taken, and its arguments (input name or none, value).
type Node<'a> = (String, Option<&'a str>, Vec<(Option<&'a str>, Value<'a>)>);

/// What a match found: the values its placeholders hold, and the calls its patterns write.
#[derive(Clone, Default)]
struct State<'a> {
    held: HashMap<String, Value<'a>>,
    eaten: HashSet<usize>,
}

/// What feeds the inputs of one graph's nodes, read against the rules of a target.
struct Links<'a> {
    target: &'a Target,
    local: &'a HashSet<String>,
    /// A name the graph binds: the expression it holds, none for the result of a zone
    values: HashMap<&'a str, Option<&'a Expr>>,
    /// The type of each parameter, by its name and its key
    params: HashMap<String, &'a str>,
    vectors: HashSet<String>,
    /// The expressions of each pattern, parsed
    patterns: &'a HashMap<String, Vec<Expr>>,
}

fn bound<'a>(body: &'a [Stmt], out: &mut HashMap<&'a str, Option<&'a Expr>>) {
    for s in body {
        match s {
            Stmt::Assign(a) => match &a.value {
                AssignValue::Expr(e) => {
                    out.insert(&a.name, Some(e));
                }
                AssignValue::BodyCall(z) => {
                    out.insert(&a.name, None);
                    bound(&z.body, out);
                }
                AssignValue::NamelessGraph(z) => {
                    out.insert(&a.name, None);
                    bound(&z.body, out);
                }
            },
            Stmt::Frame(f) => bound(&f.body, out),
            Stmt::Return(_) => {}
        }
    }
}

fn get<'a>(given: &[(String, Value<'a>)], k: &str) -> Option<Value<'a>> {
    given.iter().find(|(n, _)| n == k).map(|(_, v)| *v)
}

impl<'a> Links<'a> {
    /// The value, through the names it goes by.
    fn follow(&self, v: Value<'a>) -> Value<'a> {
        let mut v = v;
        for _ in 0..64 {
            let Value::Expr(Expr::Ref(r)) = v else {
                break;
            };
            match self.values.get(r.name.as_str()) {
                Some(Some(e)) => v = Value::Expr(e),
                Some(None) => v = Value::Zone,
                None => break,
            }
        }
        v
    }

    /// Whether the value is a value rather than a link: a literal, a parameter, an input left to
    /// its default.
    fn constant(&self, v: Value<'a>) -> bool {
        if let Value::Default = v {
            return true;
        }
        match self.follow(v) {
            Value::Default => true,
            Value::Zone => false,
            Value::Expr(e) => match e {
                Expr::Number(_) | Expr::String(_) | Expr::Bool(_) => true,
                // A parameter, or a setting's value such as MULTIPLY
                Expr::Ref(r) => !self.values.contains_key(r.name.as_str()),
                Expr::Tuple(t) => t.items.iter().all(|i| self.constant(Value::Expr(i))),
                Expr::Neg(n) => self.constant(Value::Expr(&n.value)),
                // The exporter computes a node it folds whose inputs are values
                _ => self.node(v).is_some_and(|(node, _, args)| {
                    self.target.folded.contains(&node)
                        && args.iter().all(|(_, a)| self.constant(*a))
                }),
            },
        }
    }

    fn name(&self, c: &Call) -> String {
        let n = c.name.as_str();
        if self.local.contains(n) || n.contains("::") {
            n.to_owned()
        } else if BOOL_FUNCS.contains(&n) {
            "BooleanMath".to_owned()
        } else if MATH_FUNCS.contains(&n) {
            "Math".to_owned()
        } else if VECTOR_FUNCS.contains(&n) {
            "VectorMath".to_owned()
        } else {
            n.to_owned()
        }
    }

    fn call_args(c: &'a Call) -> impl Iterator<Item = (Option<&'a str>, Value<'a>)> {
        c.args
            .iter()
            .map(|a| (a.name.as_deref(), Value::Expr(&a.value)))
    }

    /// The node that makes the value, none when no node makes it.
    fn node(&self, v: Value<'a>) -> Option<Node<'a>> {
        let Value::Expr(e) = self.follow(v) else {
            return None;
        };
        let (e, socket) = match e {
            Expr::Member(m) => match self.follow(Value::Expr(&m.target)) {
                Value::Expr(t) => (t, Some(m.socket.as_str())),
                _ => return None,
            },
            other => (other, None),
        };
        match e {
            Expr::Pipe(p) => {
                let (call, socket) = match &*p.call {
                    Expr::Member(m) => (&*m.target, Some(m.socket.as_str())),
                    other => (other, socket),
                };
                let Expr::Call(c) = call else {
                    return None;
                };
                let mut args = vec![(None, Value::Expr(&p.left))];
                args.extend(Self::call_args(c));
                Some((self.name(c), socket, args))
            }
            Expr::Call(c) => Some((self.name(c), socket, Self::call_args(c).collect())),
            Expr::BinOp(b) => {
                let (l, r) = (Value::Expr(&b.left), Value::Expr(&b.right));
                let mut node = formula(&b.op);
                if node == "Math" && (self.vector(l) || self.vector(r)) {
                    node = "VectorMath";
                }
                Some((node.to_owned(), socket, vec![(None, l), (None, r)]))
            }
            Expr::Neg(n) => {
                let v = Value::Expr(&n.value);
                let node = if self.vector(v) { "VectorMath" } else { "Math" };
                Some((node.to_owned(), socket, vec![(None, v)]))
            }
            Expr::Not(n) => Some((
                "BooleanMath".to_owned(),
                socket,
                vec![(None, Value::Expr(&n.value))],
            )),
            _ => None,
        }
    }

    /// (input, value) of a call: a positional argument takes the input of its place in `inputs`.
    fn given(
        &self,
        node: &str,
        args: &[(Option<&'a str>, Value<'a>)],
    ) -> Vec<(&'a str, Value<'a>)> {
        let order: &'a [String] = self
            .target
            .inputs
            .get(node)
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let mut out = Vec::new();
        for (i, (n, v)) in args.iter().enumerate() {
            match n {
                Some(n) => out.push((identifier_key(node, n), *v)),
                None => {
                    if let Some(o) = order.get(i) {
                        out.push((o.as_str(), *v));
                    }
                }
            }
        }
        out
    }

    fn lowered(
        &self,
        node: &str,
        args: &[(Option<&'a str>, Value<'a>)],
    ) -> Vec<(String, Value<'a>)> {
        let mut out: Vec<(String, Value<'a>)> = Vec::new();
        for (k, v) in self.given(node, args) {
            let k = k.to_lowercase();
            // As a dict: a name given twice keeps its place and takes the last value
            match out.iter_mut().find(|(n, _)| *n == k) {
                Some(slot) => slot.1 = v,
                None => out.push((k, v)),
            }
        }
        out
    }

    /// The value of a setting as written (`MULTIPLY`, `"UV"`), none when it is not one.
    fn word(&self, v: Value<'a>) -> Option<String> {
        match self.follow(v) {
            Value::Expr(Expr::Ref(r)) => Some(r.name.clone()),
            Value::Expr(Expr::String(s)) => Some(s.value.clone()),
            Value::Expr(Expr::Number(n)) => Some(format!("{:?}", n.value)),
            Value::Expr(Expr::Bool(b)) => Some(b.value.to_string()),
            _ => None,
        }
    }

    /// The value of setting `name` of a call: given, or its default.
    fn setting(&self, node: &str, given: &[(String, Value<'a>)], name: &str) -> Option<String> {
        match get(given, name) {
            Some(v) => self.word(v),
            None => self.target.settings.get(node)?.get(name).cloned().flatten(),
        }
    }

    /// The operation of a Math or Vector Math: its formula's (`*`, `round`), else its setting.
    fn operation(&self, v: Value<'a>, node: &str, given: &[(String, Value<'a>)]) -> Option<String> {
        let mut f = self.follow(v);
        if let Value::Expr(Expr::Member(m)) = f {
            f = self.follow(Value::Expr(&m.target));
        }
        match f {
            Value::Expr(Expr::BinOp(b)) if op_of(&BINOPS, &b.op).is_some() => {
                op_of(&BINOPS, &b.op).map(str::to_owned)
            }
            Value::Expr(Expr::Call(c)) if node == "Math" && op_of(&MATH_OPS, &c.name).is_some() => {
                op_of(&MATH_OPS, &c.name).map(str::to_owned)
            }
            Value::Expr(Expr::Call(c))
                if node == "VectorMath" && op_of(&VECTOR_OPS, &c.name).is_some() =>
            {
                op_of(&VECTOR_OPS, &c.name).map(str::to_owned)
            }
            _ => self.setting(node, given, "operation"),
        }
    }

    fn one(&self, v: Option<Value<'a>>) -> bool {
        match v {
            None => true,
            Some(v) => matches!(self.follow(v), Value::Expr(Expr::Number(n)) if n.value == 1.0),
        }
    }

    /// Whether the value holds a color or a vector, which a `*` takes to a Vector Math.
    fn vector(&self, v: Value<'a>) -> bool {
        let Value::Expr(f) = self.follow(v) else {
            return false;
        };
        match f {
            Expr::Tuple(_) => return true,
            Expr::Ref(r) => {
                return matches!(self.params.get(&r.name), Some(&"Color") | Some(&"Vector"))
            }
            Expr::BinOp(b) => {
                return !["⋅", "·", "dot"].contains(&b.op.as_str())
                    && (self.vector(Value::Expr(&b.left)) || self.vector(Value::Expr(&b.right)))
            }
            Expr::Neg(n) => return self.vector(Value::Expr(&n.value)),
            _ => {}
        }
        let Some((node, socket, _)) = self.node(v) else {
            return false;
        };
        let socket = socket.unwrap_or_else(|| self.first(&node));
        self.vectors
            .contains(&format!("{node}.{socket}").to_lowercase())
    }

    /// The output a call taken whole gives: its first.
    fn first(&self, node: &str) -> &'a str {
        self.target
            .outputs
            .get(node)
            .and_then(|o| o.first())
            .map(String::as_str)
            .unwrap_or("")
    }

    /// Whether input `inp` of `node` (or placeholder of a pattern) is a color or a vector.
    fn color(&self, node: &str, inp: &str) -> bool {
        self.vectors
            .contains(&format!("{node}.{inp}").to_lowercase())
    }

    /// The two values the value multiplies as the exporter reads it on an input of that type,
    /// none when it is not: on a color input a Mix whose data_type is RGBA (written, or taken from
    /// a tuple of 4), blend_type MULTIPLY and factor 1; on a number input a Math whose operation
    /// is MULTIPLY, the `*` formula of two numbers or the node.
    fn multiply(&self, v: Value<'a>, color: bool) -> Option<(Value<'a>, Value<'a>)> {
        if let Value::Default = v {
            return None;
        }
        if let Value::Expr(Expr::BinOp(b)) = self.follow(v) {
            let (l, r) = (Value::Expr(&b.left), Value::Expr(&b.right));
            return (b.op == "*" && !color && !self.vector(l) && !self.vector(r)).then_some((l, r));
        }
        let (node, _, args) = self.node(v)?;
        let given = self.lowered(&node, &args);
        let (a, b) = if !color
            && node == "Math"
            && self.operation(v, &node, &given).as_deref() == Some("MULTIPLY")
        {
            ("value", "value_001")
        } else if color
            && node == "Mix"
            && self.setting(&node, &given, "blend_type").as_deref() == Some("MULTIPLY")
            && self.one(get(&given, "factor"))
            && self.rgba(&node, &given)
        {
            ("a", "b")
        } else {
            return None;
        };
        let operand = |k: &str| get(&given, k).unwrap_or(Value::Default);
        Some((operand(a), operand(b)))
    }

    /// Whether a Mix mixes colors: its data_type, or a tuple of 4 among its inputs.
    fn rgba(&self, node: &str, given: &[(String, Value<'a>)]) -> bool {
        if get(given, "data_type").is_some() {
            return self.setting(node, given, "data_type").as_deref() == Some("RGBA");
        }
        given.iter().any(|(k, v)| {
            ["factor", "a", "b"].contains(&k.as_str())
                && matches!(self.follow(*v), Value::Expr(Expr::Tuple(t)) if t.items.len() == 4)
        })
    }

    // -- Matching a feed

    /// Whether one of `feeds` takes the value; `st` keeps what the one that does found.
    fn accepts(&self, v: Value<'a>, feeds: &[String], color: bool, st: &mut State<'a>) -> bool {
        for p in feeds {
            let mut trial = st.clone();
            let (core, around) = pattern(p);
            if self.matches(v, core, &around, color, &mut trial) {
                *st = trial;
                return true;
            }
        }
        false
    }

    /// Whether the value is `core` multiplied by each of `around`, peeled one at a time from the
    /// outside.
    fn matches(
        &self,
        v: Value<'a>,
        core: &str,
        around: &[&str],
        color: bool,
        st: &mut State<'a>,
    ) -> bool {
        if around.is_empty() {
            return self.term(v, core, color, st);
        }
        let Some((x, y)) = self.multiply(v, color) else {
            return false;
        };
        for (i, t) in around.iter().enumerate() {
            let mut rest = around.to_vec();
            rest.remove(i);
            if (self.term(x, t, color, st) && self.matches(y, core, &rest, color, st))
                || (self.term(y, t, color, st) && self.matches(x, core, &rest, color, st))
            {
                return true;
            }
        }
        false
    }

    /// Whether the value is `constant`, `any`, a tuple, a pattern, `Node` (any of its outputs) or
    /// `Node.output`.
    fn term(&self, v: Value<'a>, t: &str, _color: bool, st: &mut State<'a>) -> bool {
        if t == "constant" {
            return self.constant(v);
        }
        if t == "any" {
            self.eat(v, st);
            return true;
        }
        if t.starts_with('(') {
            let items: Vec<&str> = t
                .trim_matches(|c| c == '(' || c == ')')
                .split(',')
                .map(str::trim)
                .collect();
            return self.tuple_of(v, &items);
        }
        if let Some(n) = t.strip_prefix('≠') {
            // A value other than this number
            return !matches!(v, Value::Default) && self.constant(v) && !self.literal(v, n.trim());
        }
        if t == "named" {
            // A value of its own name: a named constant is a Value node
            return matches!(v, Value::Expr(Expr::Ref(r)) if self.values.contains_key(r.name.as_str()))
                && matches!(self.follow(v), Value::Expr(e) if number(e).is_some());
        }
        if literal(t) {
            return matches!(v, Value::Default) || self.literal(v, t);
        }
        if self.patterns.contains_key(t) {
            return self.pattern(v, t, st);
        }
        let (name, out) = t.split_once('.').unwrap_or((t, ""));
        match self.node(v) {
            Some((n, socket, _)) => {
                n == name
                    && (out.is_empty()
                        || same_word(socket.unwrap_or_else(|| self.first(name)), out))
            }
            None => false,
        }
    }

    /// Whether the value is the number (or `true`, `false`) written `t`.
    fn literal(&self, v: Value<'a>, t: &str) -> bool {
        let Value::Expr(f) = self.follow(v) else {
            return false;
        };
        if t == "true" || t == "false" {
            return matches!(f, Expr::Bool(b) if b.value == (t == "true"));
        }
        match (number(f), t.parse::<f64>()) {
            (Some(n), Ok(w)) => (n - w).abs() <= 1e-4,
            _ => false,
        }
    }

    /// Whether the value is a tuple whose items are these numbers or constants; an input left to
    /// its default is.
    fn tuple_of(&self, v: Value<'a>, items: &[&str]) -> bool {
        if let Value::Default = v {
            return true;
        }
        let Value::Expr(Expr::Tuple(t)) = self.follow(v) else {
            return false;
        };
        if t.items.len() != items.len() {
            return false;
        }
        t.items.iter().zip(items).all(|(i, want)| {
            if *want == "constant" {
                return self.constant(Value::Expr(i));
            }
            let got = match self.follow(Value::Expr(i)) {
                Value::Expr(e) => number(e),
                _ => None,
            };
            match (got, want.parse::<f64>()) {
                (Some(g), Ok(w)) => (g - w).abs() <= 1e-4,
                _ => false,
            }
        })
    }

    fn pattern(&self, v: Value<'a>, name: &str, st: &mut State<'a>) -> bool {
        for p in &self.patterns[name] {
            let mut trial = st.clone();
            if self.shape(v, p, name, &mut trial) {
                *st = trial;
                return true;
            }
        }
        false
    }

    /// Whether the values of several inputs of a call have together the shape of one of the
    /// patterns `feeds` name, written as tuples.
    fn group(&self, values: &[Value<'a>], feeds: &[String], st: &mut State<'a>) -> bool {
        for f in feeds {
            let Some(written) = self.patterns.get(f.as_str()) else {
                continue;
            };
            for p in written {
                let Expr::Tuple(t) = p else {
                    continue;
                };
                if t.items.len() != values.len() {
                    continue;
                }
                let mut trial = st.clone();
                if values
                    .iter()
                    .zip(&t.items)
                    .all(|(v, q)| self.shape(*v, q, f, &mut trial))
                {
                    *st = trial;
                    return true;
                }
            }
        }
        false
    }

    /// Whether the value has the shape of `p`, an expression of pattern `name` whose placeholders
    /// are its inputs. A placeholder takes any value its rule (`Pattern.placeholder`) accepts, the
    /// same wherever it appears; a call of the pattern is a call of that node, its inputs and
    /// settings as written.
    fn shape(&self, v: Value<'a>, p: &'a Expr, name: &str, st: &mut State<'a>) -> bool {
        if let Expr::Ref(r) = p {
            if self
                .target
                .inputs
                .get(name)
                .is_some_and(|h| h.contains(&r.name))
            {
                if let Some(held) = st.held.get(&r.name).copied() {
                    return self.same(v, held);
                }
                st.held.insert(r.name.clone(), v);
                return match self.target.rules.get(&format!("{name}.{}", r.name)) {
                    None => true,
                    Some(feeds) => self.accepts(v, feeds, self.color(name, &r.name), st),
                };
            }
        }
        if let Value::Default = v {
            return false;
        }
        let Value::Expr(f) = self.follow(v) else {
            return false;
        };
        if let Some(want) = number(p) {
            return number(f).is_some_and(|got| (got - want).abs() <= 1e-4);
        }
        match p {
            Expr::Ref(r) => {
                return self
                    .word(Value::Expr(f))
                    .is_some_and(|w| same_word(&w, &r.name))
            }
            Expr::Tuple(t) => {
                let Expr::Tuple(ft) = f else {
                    return false;
                };
                return ft.items.len() == t.items.len()
                    && ft
                        .items
                        .iter()
                        .zip(&t.items)
                        .all(|(x, q)| self.shape(Value::Expr(x), q, name, st));
            }
            Expr::Member(m) => {
                let Expr::Member(fm) = f else {
                    return false;
                };
                return same_word(&fm.socket, &m.socket)
                    && self.shape(Value::Expr(&fm.target), &m.target, name, st);
            }
            _ => {}
        }
        // The node a pattern writes, read without the names of the text: a formula of it is a Math
        let (pnode, pargs): (String, Vec<(Option<&'a str>, Value<'a>)>) = match p {
            Expr::Call(c) => (self.name(c), Self::call_args(c).collect()),
            Expr::BinOp(b) => (
                formula(&b.op).to_owned(),
                vec![(None, Value::Expr(&b.left)), (None, Value::Expr(&b.right))],
            ),
            _ => return false,
        };
        let Some((node, socket, args)) = self.node(Value::Expr(f)) else {
            return false;
        };
        if socket.is_some() || node != pnode {
            return false;
        }
        let given = self.lowered(&node, &args);
        let written = self.lowered(&node, &pargs);
        if (node == "Math" || node == "VectorMath")
            && self.operation(Value::Expr(p), &node, &written)
                != self.operation(Value::Expr(f), &node, &given)
        {
            return false;
        }
        let inputs: Vec<String> = self
            .target
            .inputs
            .get(&node)
            .map(|i| i.iter().map(|s| s.to_lowercase()).collect())
            .unwrap_or_default();
        for (k, pv) in &written {
            if k == "operation" {
                continue;
            }
            if !inputs.contains(k) {
                let have = self.setting(&node, &given, k).unwrap_or_default();
                let want = self.word(*pv).unwrap_or_default();
                if !same_word(&have, &want) {
                    return false;
                }
            } else {
                let Value::Expr(q) = pv else {
                    return false;
                };
                if !self.shape(get(&given, k).unwrap_or(Value::Default), q, name, st) {
                    return false;
                }
            }
        }
        let call = match f {
            Expr::Pipe(pp) => match &*pp.call {
                Expr::Member(m) => &*m.target,
                other => other,
            },
            other => other,
        };
        if let Expr::Call(c) = call {
            st.eaten.insert(call_id(c));
        }
        true
    }

    /// Whether two values a placeholder takes are one: the same node, or equal numbers.
    fn same(&self, a: Value<'a>, b: Value<'a>) -> bool {
        match (self.follow(a), self.follow(b)) {
            (Value::Default, Value::Default) => true,
            (Value::Expr(x), Value::Expr(y)) => {
                if std::ptr::eq(x, y) {
                    return true;
                }
                if let (Expr::Member(mx), Expr::Member(my)) = (x, y) {
                    return mx.socket == my.socket
                        && self.same(Value::Expr(&mx.target), Value::Expr(&my.target));
                }
                matches!((number(x), number(y)), (Some(p), Some(q)) if p == q)
            }
            _ => false,
        }
    }

    /// Every call the value makes: a placeholder the exporter does not read speaks for them.
    fn eat(&self, v: Value<'a>, st: &mut State<'a>) {
        let mut todo = vec![v];
        let mut seen = HashSet::new();
        while let Some(v) = todo.pop() {
            let Value::Expr(e) = self.follow(v) else {
                continue;
            };
            if !seen.insert(e as *const Expr as usize) {
                continue;
            }
            let mut found = Calls(Vec::new());
            found.expr(e);
            st.eaten.extend(found.0.iter().map(|(c, ..)| call_id(c)));
            let mut names = Vec::new();
            refs(e, &mut names);
            todo.extend(names.into_iter().map(Value::Expr));
        }
    }

    /// The calls the expression makes, through the names it reads, in the order of their inputs:
    /// each once.
    fn reach(&self, e: &'a Expr, out: &mut Vec<&'a Call>, seen: &mut HashSet<&'a str>) {
        match e {
            Expr::Ref(r) => {
                if let Some(v) = self.values.get(r.name.as_str()) {
                    if seen.insert(r.name.as_str()) {
                        if let Some(v) = v {
                            self.reach(v, out, seen);
                        }
                    }
                }
            }
            Expr::Call(c) => {
                if !out.iter().any(|o| std::ptr::eq(*o, c)) {
                    out.push(c);
                }
                for a in &c.args {
                    self.reach(&a.value, out, seen);
                }
            }
            Expr::Pipe(p) => {
                self.reach(&p.left, out, seen);
                self.reach(&p.call, out, seen);
            }
            Expr::BinOp(b) => {
                self.reach(&b.left, out, seen);
                self.reach(&b.right, out, seen);
            }
            Expr::Neg(n) => self.reach(&n.value, out, seen),
            Expr::Not(n) => self.reach(&n.value, out, seen),
            Expr::Cond(c) => {
                self.reach(&c.cond, out, seen);
                self.reach(&c.then, out, seen);
                self.reach(&c.orelse, out, seen);
            }
            Expr::Member(m) => self.reach(&m.target, out, seen),
            Expr::Tuple(t) => {
                for i in &t.items {
                    self.reach(i, out, seen);
                }
            }
            Expr::Number(_) | Expr::String(_) | Expr::Bool(_) => {}
        }
    }

    // -- What the issue says

    /// What feeds an input, in short: `constant`, `NoiseTexture`, `Math(ImageTexture, ImageTexture)`.
    fn describe(&self, v: Value<'a>) -> String {
        if self.constant(v) {
            return "constant".to_owned();
        }
        let Some((node, _, args)) = self.node(v) else {
            return self.opaque(v);
        };
        let inner: Vec<String> = args
            .iter()
            .filter(|(_, a)| !self.constant(*a))
            .map(|(_, a)| self.short(*a))
            .collect();
        if inner.is_empty() {
            node
        } else {
            format!("{node}({})", inner.join(", "))
        }
    }

    fn short(&self, v: Value<'a>) -> String {
        match self.node(v) {
            Some((n, ..)) => n,
            None => self.opaque(v),
        }
    }

    fn opaque(&self, v: Value<'a>) -> String {
        if let Value::Expr(Expr::Ref(r)) = v {
            return r.name.clone();
        }
        match self.follow(v) {
            Value::Expr(Expr::Tuple(_)) => "tuple".to_owned(),
            _ => "value".to_owned(),
        }
    }
}

/// Whether the settings of a graph make it a material's own tree: `shader(material: true)`.
fn is_material(settings: &[Arg]) -> bool {
    settings.iter().any(|a| {
        a.name.as_deref() == Some("material") && matches!(&a.value, Expr::Bool(b) if b.value)
    })
}

/// The Material Output a material's return feeds, as a call; none for a graph that is not a
/// material. A `shader(material: true)` graph is a material, and so is a shader graph of the text
/// no other calls whose first output is a Shader: its outputs go by name, the first Shader to
/// Surface when none is named so.
fn material_output(graph: &Graph, file: Option<&File>) -> Option<Expr> {
    if graph.kind != "shader" {
        return None;
    }
    let outs = &graph.outputs;
    if !is_material(&graph.settings) {
        let file = file?;
        if outs.first()?.type_name != "Shader" {
            return None;
        }
        let mut called = HashSet::new();
        for g in &file.graphs {
            if g.name != graph.name {
                for (what, n, ..) in walk_body(&g.body) {
                    if what == Found::Call {
                        called.insert(n);
                    }
                }
            }
        }
        if called.contains(&graph.name) || called.contains(&key(&graph.name)) {
            return None;
        }
    }
    let ret = graph.body.iter().rev().find_map(|s| match s {
        Stmt::Return(r) => Some(r),
        _ => None,
    })?;
    let mut given: Vec<(String, Expr)> = match &ret.value {
        ReturnValue::Record(rec) => rec
            .fields
            .iter()
            .map(|a| (a.name.clone().unwrap_or_default(), a.value.clone()))
            .collect(),
        ReturnValue::Expr(e) => vec![(
            outs.first()
                .map(|p| p.name.clone())
                .unwrap_or_else(|| "surface".to_owned()),
            e.clone(),
        )],
    };
    if !given.iter().any(|(n, _)| n.to_lowercase() == "surface") {
        let shader = |n: &str| {
            outs.iter()
                .any(|p| key(&p.name) == n && p.type_name == "Shader")
        };
        if let Some(first) = given.iter().position(|(n, _)| shader(n)) {
            given[first].0 = "surface".to_owned();
        }
    }
    let args = given
        .into_iter()
        .filter(|(n, _)| MATERIAL_SOCKETS.contains(&n.to_lowercase().as_str()))
        .map(|(n, value)| Arg {
            name: Some(n.to_lowercase()),
            value,
            line: ret.line,
            col: ret.col,
            options: Vec::new(),
            type_decl: None,
            alias: None,
        })
        .collect();
    Some(Expr::Call(Call {
        name: "MaterialOutput".to_owned(),
        args,
        line: ret.line,
        col: ret.col,
        outputs: None,
        single_output: false,
        type_args: None,
    }))
}

/// The graphs a call may name: name -> (its file, its index).
type Graphs = HashMap<String, (Rc<File>, usize)>;

/// What reads a graph through the graphs it calls: a call to a graph of the text or of a module
/// it uses becomes that graph's body, its parameters the values the call gives, at the line of
/// the call. Blender's exporter reads through a group as through the nodes it holds.
struct Inline<'m, 'r> {
    target: &'m Target,
    modules: &'m Modules<'r>,
    hoisted: Vec<Stmt>,
    count: usize,
    finders: HashMap<usize, Rc<Graphs>>,
}

impl Inline<'_, '_> {
    /// name -> (its file, its index) for the graphs a call of `file` may name: its own, and its
    /// modules'.
    fn finder(&mut self, file: &Rc<File>) -> Rc<Graphs> {
        let id = Rc::as_ptr(file) as usize;
        if let Some(f) = self.finders.get(&id) {
            return f.clone();
        }
        let mut found: HashMap<String, (Rc<File>, usize)> = HashMap::new();
        for (i, g) in file.graphs.iter().enumerate() {
            found.insert(g.name.clone(), (file.clone(), i));
            found.insert(key(&g.name), (file.clone(), i));
        }
        for u in &file.uses {
            let Some(m) = self.modules.find(self.target, &u.name) else {
                continue;
            };
            let prefix = u.alias.as_deref().unwrap_or(&u.name);
            for (i, g) in m.graphs.iter().enumerate() {
                let k = key(&g.name);
                found.insert(format!("{prefix}::{k}"), (m.clone(), i));
                if u.names.as_ref().is_none_or(|ns| ns.contains(&k)) {
                    found.entry(k).or_insert((m.clone(), i));
                }
            }
        }
        let found = Rc::new(found);
        self.finders.insert(id, found.clone());
        found
    }

    fn stmts(&mut self, body: &mut [Stmt], f: &Rc<File>, depth: usize) {
        for s in body {
            match s {
                Stmt::Assign(a) => match &mut a.value {
                    AssignValue::Expr(e) => self.expr(e, f, depth),
                    AssignValue::BodyCall(z) => {
                        self.args(&mut z.args, f, depth);
                        self.stmts(&mut z.body, f, depth);
                    }
                    AssignValue::NamelessGraph(z) => self.stmts(&mut z.body, f, depth),
                },
                Stmt::Return(r) => match &mut r.value {
                    ReturnValue::Expr(e) => self.expr(e, f, depth),
                    ReturnValue::Record(rec) => self.args(&mut rec.fields, f, depth),
                },
                Stmt::Frame(fr) => self.stmts(&mut fr.body, f, depth),
            }
        }
    }

    fn args(&mut self, args: &mut [Arg], f: &Rc<File>, depth: usize) {
        for a in args {
            self.expr(&mut a.value, f, depth);
            self.args(&mut a.options, f, depth);
        }
    }

    fn graph_call(&mut self, e: &Expr, f: &Rc<File>) -> bool {
        matches!(e, Expr::Call(c) if self.finder(f).contains_key(&c.name))
    }

    fn pipe_call(&mut self, p: &base_node::ast::Pipe, f: &Rc<File>) -> bool {
        match &*p.call {
            Expr::Member(m) => self.graph_call(&m.target, f),
            other => self.graph_call(other, f),
        }
    }

    fn expr(&mut self, e: &mut Expr, f: &Rc<File>, depth: usize) {
        let replaced = match e {
            Expr::Member(m) if self.graph_call(&m.target, f) => {
                let socket = m.socket.clone();
                let Expr::Call(c) = &mut *m.target else {
                    unreachable!()
                };
                self.args(&mut c.args, f, depth);
                let c = c.clone();
                self.expand(&c, None, Some(&socket), f, depth)
            }
            Expr::Pipe(p) => {
                let (call, socket) = match &*p.call {
                    Expr::Member(m) => (&*m.target, Some(m.socket.clone())),
                    other => (other, None),
                };
                if self.graph_call(call, f) {
                    self.expr(&mut p.left, f, depth);
                    let call = match &mut *p.call {
                        Expr::Member(m) => &mut *m.target,
                        other => other,
                    };
                    let Expr::Call(c) = call else { unreachable!() };
                    self.args(&mut c.args, f, depth);
                    let c = c.clone();
                    let left = (*p.left).clone();
                    self.expand(&c, Some(left), socket.as_deref(), f, depth)
                } else {
                    None
                }
            }
            Expr::Call(c) if self.finder(f).contains_key(&c.name) => {
                self.args(&mut c.args, f, depth);
                let c = c.clone();
                self.expand(&c, None, None, f, depth)
            }
            _ => None,
        };
        if let Some(r) = replaced {
            *e = r;
            return;
        }
        match e {
            // A call to a graph whose body gives nothing stays as it is
            Expr::Call(c) if self.finder(f).contains_key(&c.name) => {}
            Expr::Member(m) if self.graph_call(&m.target, f) => {}
            Expr::Pipe(p) if self.pipe_call(p, f) => {}
            Expr::Call(c) => self.args(&mut c.args, f, depth),
            Expr::Pipe(p) => {
                self.expr(&mut p.left, f, depth);
                self.expr(&mut p.call, f, depth);
            }
            Expr::BinOp(b) => {
                self.expr(&mut b.left, f, depth);
                self.expr(&mut b.right, f, depth);
            }
            Expr::Neg(n) => self.expr(&mut n.value, f, depth),
            Expr::Not(n) => self.expr(&mut n.value, f, depth),
            Expr::Cond(c) => {
                self.expr(&mut c.cond, f, depth);
                self.expr(&mut c.then, f, depth);
                self.expr(&mut c.orelse, f, depth);
            }
            Expr::Member(m) => self.expr(&mut m.target, f, depth),
            Expr::Tuple(t) => {
                for i in &mut t.items {
                    self.expr(i, f, depth);
                }
            }
            Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
        }
    }

    fn expand(
        &mut self,
        call: &Call,
        piped: Option<Expr>,
        socket: Option<&str>,
        f: &Rc<File>,
        depth: usize,
    ) -> Option<Expr> {
        let (cf, at) = self.finder(f).get(&call.name).cloned()?;
        if depth > 16 {
            return None;
        }
        let callee = &cf.graphs[at];
        self.count += 1;
        let n = self.count;
        let mut positional: Vec<Expr> = piped.into_iter().collect();
        positional.extend(
            call.args
                .iter()
                .filter(|a| a.name.is_none())
                .map(|a| a.value.clone()),
        );
        let named: HashMap<&str, &Expr> = call
            .args
            .iter()
            .filter_map(|a| a.name.as_deref().map(|k| (k, &a.value)))
            .collect();
        let node = group_node(&callee.name, &self.target.groups);
        let read: &[String] = node
            .and_then(|n| self.target.inputs.get(n))
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let mut values: HashMap<String, Expr> = HashMap::new();
        let mut args = Vec::new();
        for (i, p) in callee.params.iter().enumerate() {
            let k = key(&p.name);
            let given = named
                .get(k.as_str())
                .or_else(|| named.get(p.name.as_str()))
                .map(|v| (*v).clone())
                .or_else(|| positional.get(i).cloned());
            if node.is_some() {
                let v = given.or_else(|| p.default.clone()).unwrap_or(Expr::Number(
                    base_node::ast::Number {
                        value: 0.0,
                        is_int: false,
                        line: call.line,
                        col: call.col,
                    },
                ));
                let name = if read.contains(&p.name) {
                    p.name.clone()
                } else {
                    format!("{} (not read)", p.name)
                };
                args.push(Arg {
                    name: Some(name),
                    value: v,
                    line: call.line,
                    col: call.col,
                    options: Vec::new(),
                    type_decl: None,
                    alias: None,
                });
                continue;
            }
            let v = given.or_else(|| p.default.clone()).unwrap_or_else(|| {
                Expr::Ref(base_node::ast::Ref {
                    name: format!("{k}@{n}"),
                    line: call.line,
                    col: call.col,
                })
            });
            values.insert(p.name.clone(), v.clone());
            values.insert(k, v);
        }
        if let Some(node) = node {
            return Some(Expr::Call(Call {
                name: node.to_owned(),
                args,
                line: call.line,
                col: call.col,
                outputs: None,
                single_output: false,
                type_args: None,
            }));
        }
        let mut names = HashSet::new();
        assigned(&callee.body, &mut names);
        let names: HashMap<String, String> = names
            .into_iter()
            .map(|a| (a.clone(), format!("{a}@{n}")))
            .collect();
        let mut body = callee.body.clone();
        relocate_stmts(&mut body, call.line, call.col);
        substitute_stmts(&mut body, &names, &values);
        self.stmts(&mut body, &cf, depth + 1);
        let at_ret = body.iter().rposition(|s| matches!(s, Stmt::Return(_)));
        let ret = at_ret.map(|i| body.remove(i));
        self.hoisted.extend(body);
        let Some(Stmt::Return(ret)) = ret else {
            return None;
        };
        match ret.value {
            ReturnValue::Record(rec) => {
                let pick = rec.fields.iter().position(|a| {
                    socket.is_some_and(|s| a.name.as_deref().is_some_and(|n| same_word(n, s)))
                });
                rec.fields
                    .into_iter()
                    .nth(pick.unwrap_or(0))
                    .map(|a| a.value)
            }
            ReturnValue::Expr(e) => Some(e),
        }
    }
}

fn relocate_stmts(body: &mut [Stmt], line: usize, col: usize) {
    let mut each = |e: &mut Expr| relocate(e, line, col);
    for_exprs(body, &mut each);
}

fn relocate(e: &mut Expr, line: usize, col: usize) {
    match e {
        Expr::Call(c) => {
            c.line = line;
            c.col = col;
            for a in &mut c.args {
                relocate(&mut a.value, line, col);
            }
        }
        Expr::Pipe(p) => {
            relocate(&mut p.left, line, col);
            relocate(&mut p.call, line, col);
        }
        Expr::BinOp(b) => {
            relocate(&mut b.left, line, col);
            relocate(&mut b.right, line, col);
        }
        Expr::Neg(n) => relocate(&mut n.value, line, col),
        Expr::Not(n) => relocate(&mut n.value, line, col),
        Expr::Cond(c) => {
            relocate(&mut c.cond, line, col);
            relocate(&mut c.then, line, col);
            relocate(&mut c.orelse, line, col);
        }
        Expr::Member(m) => relocate(&mut m.target, line, col),
        Expr::Tuple(t) => {
            for i in &mut t.items {
                relocate(i, line, col);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
    }
}

/// The names a graph's body binds renamed, its parameters replaced by the values a call gives.
fn substitute_stmts(
    body: &mut [Stmt],
    names: &HashMap<String, String>,
    values: &HashMap<String, Expr>,
) {
    rename_assigns(body, names);
    let mut each = |e: &mut Expr| substitute(e, names, values);
    for_exprs(body, &mut each);
}

fn rename_assigns(body: &mut [Stmt], names: &HashMap<String, String>) {
    for s in body {
        match s {
            Stmt::Assign(a) => {
                if let Some(n) = names.get(&a.name) {
                    a.name = n.clone();
                }
                match &mut a.value {
                    AssignValue::Expr(_) => {}
                    AssignValue::BodyCall(z) => rename_assigns(&mut z.body, names),
                    AssignValue::NamelessGraph(z) => rename_assigns(&mut z.body, names),
                }
            }
            Stmt::Frame(f) => rename_assigns(&mut f.body, names),
            Stmt::Return(_) => {}
        }
    }
}

fn substitute(e: &mut Expr, names: &HashMap<String, String>, values: &HashMap<String, Expr>) {
    match e {
        Expr::Ref(r) => {
            if let Some(n) = names.get(&r.name) {
                r.name = n.clone();
            } else if let Some(v) = values.get(&r.name) {
                *e = v.clone();
            }
        }
        Expr::Call(c) => {
            for a in &mut c.args {
                substitute(&mut a.value, names, values);
            }
        }
        Expr::Pipe(p) => {
            substitute(&mut p.left, names, values);
            substitute(&mut p.call, names, values);
        }
        Expr::BinOp(b) => {
            substitute(&mut b.left, names, values);
            substitute(&mut b.right, names, values);
        }
        Expr::Neg(n) => substitute(&mut n.value, names, values),
        Expr::Not(n) => substitute(&mut n.value, names, values),
        Expr::Cond(c) => {
            substitute(&mut c.cond, names, values);
            substitute(&mut c.then, names, values);
            substitute(&mut c.orelse, names, values);
        }
        Expr::Member(m) => substitute(&mut m.target, names, values),
        Expr::Tuple(t) => {
            for i in &mut t.items {
                substitute(i, names, values);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) => {}
    }
}

/// Each expression the statements hold at their top: values, counts, states, returns.
fn for_exprs(body: &mut [Stmt], each: &mut dyn FnMut(&mut Expr)) {
    fn args(a: &mut [Arg], each: &mut dyn FnMut(&mut Expr)) {
        for x in a {
            each(&mut x.value);
            args(&mut x.options, each);
        }
    }
    for s in body {
        match s {
            Stmt::Assign(a) => match &mut a.value {
                AssignValue::Expr(e) => each(e),
                AssignValue::BodyCall(z) => {
                    args(&mut z.args, each);
                    for_exprs(&mut z.body, each);
                }
                AssignValue::NamelessGraph(z) => for_exprs(&mut z.body, each),
            },
            Stmt::Return(r) => match &mut r.value {
                ReturnValue::Expr(e) => each(e),
                ReturnValue::Record(rec) => args(&mut rec.fields, each),
            },
            Stmt::Frame(f) => for_exprs(&mut f.body, each),
        }
    }
}

/// Graph `at` of `file` read through the graphs it calls.
fn inlined(file: &Rc<File>, at: usize, target: &Target, modules: &Modules) -> Graph {
    let mut graph = file.graphs[at].clone();
    let mut inline = Inline {
        target,
        modules,
        hoisted: Vec::new(),
        count: 0,
        finders: HashMap::new(),
    };
    inline.stmts(&mut graph.body, file, 0);
    let mut body = std::mem::take(&mut inline.hoisted);
    body.append(&mut graph.body);
    graph.body = body;
    graph
}

/// The links of graph `at` of `file` the rules of `target` refuse, as Issues `what = "link"` at
/// the line of the call. A call to a graph of the text is read through, as Blender's exporter
/// reads through a group, and a material's return feeds its Material Output. A target without
/// rules refuses none.
pub fn link_issues(file: &File, at: usize, target: &Target) -> Vec<Issue> {
    if !target.members.is_empty() {
        let per = target
            .members
            .iter()
            .map(|m| link_issues(file, at, m))
            .collect();
        return every(target, per);
    }
    let modules = Modules::new(None);
    let local = local_names(file, &|n| modules.find(target, n));
    let file = Rc::new(file.clone());
    let graph = inlined(&file, at, target, &modules);
    link_issues_of(&graph, Some(&file), target, &local.names)
}

/// The rules of a target by node: {input: (input as written, feeds)}, [(inputs, feeds)] of the
/// rules on several inputs together, and the feeds of the rules on a call as a whole.
type Split<'t> = (
    HashMap<&'t str, HashMap<String, (&'t str, &'t [String])>>,
    HashMap<&'t str, Vec<(Vec<String>, &'t [String])>>,
    HashMap<&'t str, &'t [String]>,
);

fn split(rules: &BTreeMap<String, Vec<String>>) -> Split<'_> {
    let (mut one, mut many, mut whole) = (HashMap::new(), HashMap::new(), HashMap::new());
    for (k, feeds) in rules {
        match k.split_once('.') {
            None => {
                whole.insert(k.as_str(), feeds.as_slice());
            }
            Some((node, input)) if input.contains('+') => {
                let inputs = input.split('+').map(|i| i.trim().to_lowercase()).collect();
                many.entry(node)
                    .or_insert_with(Vec::new)
                    .push((inputs, feeds.as_slice()));
            }
            Some((node, input)) => {
                one.entry(node)
                    .or_insert_with(HashMap::new)
                    .insert(input.to_lowercase(), (input, feeds.as_slice()));
            }
        }
    }
    (one, many, whole)
}

/// What `==` and `!=` give Math's Compare as its Epsilon: the Epsilon of a new Compare node.
const EPSILON: f64 = 0.001;

/// A comparison of numbers in a tree with no Compare node: Math's operation, and whether the
/// result is taken from 1 (`a >= b` is `1 - (a < b)`).
const MATH_COMPARE: [(&str, &str, bool); 6] = [
    (">", "GREATER_THAN", false),
    ("<", "LESS_THAN", false),
    (">=", "LESS_THAN", true),
    ("<=", "GREATER_THAN", true),
    ("==", "COMPARE", false),
    ("!=", "COMPARE", true),
];

/// Every comparison of `e` as the Math nodes it writes in a tree with no Compare node:
/// `a >= b` is `1.0 - Math(a, b, operation: LESS_THAN)`.
fn math_comparisons(e: &mut Expr) {
    match e {
        Expr::Call(c) => {
            for a in &mut c.args {
                math_comparisons(&mut a.value);
            }
        }
        Expr::Pipe(p) => {
            math_comparisons(&mut p.left);
            math_comparisons(&mut p.call);
        }
        Expr::BinOp(b) => {
            math_comparisons(&mut b.left);
            math_comparisons(&mut b.right);
        }
        Expr::Neg(n) => math_comparisons(&mut n.value),
        Expr::Not(n) => math_comparisons(&mut n.value),
        Expr::Cond(c) => {
            math_comparisons(&mut c.cond);
            math_comparisons(&mut c.then);
            math_comparisons(&mut c.orelse);
        }
        Expr::Member(m) => math_comparisons(&mut m.target),
        Expr::Tuple(t) => {
            for i in &mut t.items {
                math_comparisons(i);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
    }
    let Expr::BinOp(b) = e else {
        return;
    };
    let Some(&(_, operation, negated)) = MATH_COMPARE.iter().find(|(op, ..)| *op == b.op) else {
        return;
    };
    let (line, col) = (b.line, b.col);
    let number = |value: f64| {
        Expr::Number(base_node::ast::Number {
            value,
            is_int: false,
            line,
            col,
        })
    };
    let arg = |name: Option<&str>, value: Expr| Arg {
        name: name.map(str::to_owned),
        value,
        line,
        col,
        options: Vec::new(),
        type_decl: None,
        alias: None,
    };
    let mut args = vec![arg(None, (*b.left).clone()), arg(None, (*b.right).clone())];
    if operation == "COMPARE" {
        args.push(arg(None, number(EPSILON)));
    }
    let setting = Expr::Ref(base_node::ast::Ref {
        name: operation.to_owned(),
        line,
        col,
    });
    args.push(arg(Some("operation"), setting));
    let call = Expr::Call(Call {
        name: "Math".to_owned(),
        args,
        line,
        col,
        outputs: None,
        single_output: false,
        type_args: None,
    });
    *e = if negated {
        Expr::BinOp(base_node::ast::BinOp {
            op: "-".to_owned(),
            left: Box::new(number(1.0)),
            right: Box::new(call),
            line,
            col,
        })
    } else {
        call
    };
}

/// The link issues of a graph. In a target with no Compare node, its comparisons are read as
/// the Math nodes they write there.
fn link_issues_of(
    graph: &Graph,
    file: Option<&File>,
    target: &Target,
    local: &HashSet<String>,
) -> Vec<Issue> {
    if target.rules.is_empty() {
        return Vec::new();
    }
    let mut graph = graph.clone();
    let geometry = graph.kind == "geometry";
    for_exprs(&mut graph.body, &mut |e| ternaries(e, geometry));
    if !target.nodes.iter().any(|n| n == "Compare") {
        for_exprs(&mut graph.body, &mut |e| math_comparisons(e));
    }
    link_issues_in(&graph, file, target, local)
}

/// Every ternary of `e` as the node it writes: a Switch where it chooses for each element, in a
/// geometry tree, else a Mix by the condition (a Mix Shader's branches are not told from a Mix's here).
fn ternaries(e: &mut Expr, geometry: bool) {
    match e {
        Expr::Call(c) => {
            for a in &mut c.args {
                ternaries(&mut a.value, geometry);
            }
        }
        Expr::Pipe(p) => {
            ternaries(&mut p.left, geometry);
            ternaries(&mut p.call, geometry);
        }
        Expr::BinOp(b) => {
            ternaries(&mut b.left, geometry);
            ternaries(&mut b.right, geometry);
        }
        Expr::Neg(n) => ternaries(&mut n.value, geometry),
        Expr::Not(n) => ternaries(&mut n.value, geometry),
        Expr::Cond(c) => {
            ternaries(&mut c.cond, geometry);
            ternaries(&mut c.then, geometry);
            ternaries(&mut c.orelse, geometry);
        }
        Expr::Member(m) => ternaries(&mut m.target, geometry),
        Expr::Tuple(t) => {
            for i in &mut t.items {
                ternaries(i, geometry);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
    }
    let Expr::Cond(c) = e else {
        return;
    };
    let (line, col) = (c.line, c.col);
    let (name, keys) = if geometry {
        ("Switch", ["switch", "false_", "true_"])
    } else {
        ("Mix", ["factor", "a", "b"])
    };
    let values = [(*c.cond).clone(), (*c.orelse).clone(), (*c.then).clone()];
    let args = keys
        .iter()
        .zip(values)
        .map(|(k, value)| Arg {
            name: Some((*k).to_owned()),
            value,
            line,
            col,
            options: Vec::new(),
            type_decl: None,
            alias: None,
        })
        .collect();
    *e = Expr::Call(Call {
        name: name.to_owned(),
        args,
        line,
        col,
        outputs: None,
        single_output: false,
        type_args: None,
    });
}

fn link_issues_in(
    graph: &Graph,
    file: Option<&File>,
    target: &Target,
    local: &HashSet<String>,
) -> Vec<Issue> {
    let (one, many, whole) = split(&target.rules);
    let patterns: HashMap<String, Vec<Expr>> = target
        .patterns
        .iter()
        .map(|(k, v)| (k.clone(), v.iter().filter_map(|t| expression(t)).collect()))
        .collect();
    let output = material_output(graph, file);
    let mut values = HashMap::new();
    bound(&graph.body, &mut values);
    let mut params = HashMap::new();
    for p in &graph.params {
        params.insert(p.name.clone(), p.type_name.as_str());
        params.insert(key(&p.name), p.type_name.as_str());
    }
    let links = Links {
        target,
        local,
        values,
        params,
        vectors: target.vectors.iter().map(|v| v.to_lowercase()).collect(),
        patterns: &patterns,
    };
    let mut calls = Calls(Vec::new());
    calls.stmts(&graph.body);
    if let Some(e @ Expr::Call(c)) = &output {
        calls.0.push((c, None, e));
    }
    let issue = |c: &Call, name: String| Issue {
        graph: graph.name.clone(),
        what: "link".to_owned(),
        name,
        line: c.line,
        col: c.col,
        target: target.name.clone(),
    };
    // The value of `Node.input`: that input of the first call to `Node`, nothing (a zone's
    // result, which nothing takes) without one
    let elsewhere = |node: &str, input: &str| -> Value {
        let Some((c, ..)) = calls.0.iter().find(|(c, ..)| c.name.to_lowercase() == node) else {
            return Value::Zone;
        };
        let args: Vec<(Option<&str>, Value)> = Links::call_args(c).collect();
        get(&links.lowered(&c.name, &args), input).unwrap_or(Value::Default)
    };
    // A call some rule takes as a whole speaks for the calls its pattern writes
    let mut eaten = HashSet::new();
    let mut fits = HashMap::new();
    for (c, _, e) in &calls.0 {
        if let Some(feeds) = whole.get(c.name.as_str()) {
            if local.contains(&c.name) {
                continue;
            }
            let mut st = State::default();
            let ok = links.accepts(Value::Expr(e), feeds, false, &mut st);
            fits.insert(call_id(c), ok);
            if ok {
                st.eaten.remove(&call_id(c));
                eaten.extend(st.eaten);
            }
        }
    }
    let mut out = Vec::new();
    for (c, piped, e) in &calls.0 {
        if local.contains(&c.name) {
            continue;
        }
        if fits.get(&call_id(c)) == Some(&false) {
            out.push((call_id(c), issue(c, links.describe(Value::Expr(e)))));
            continue;
        }
        let Some(mine) = one.get(c.name.as_str()) else {
            continue;
        };
        let mut st = State::default();
        let mut args: Vec<(Option<&str>, Value)> =
            piped.map(|p| (None, Value::Expr(p))).into_iter().collect();
        args.extend(Links::call_args(c));
        let given = links.given(&c.name, &args);
        let settings: BTreeMap<String, &Option<String>> = target
            .settings
            .get(&c.name)
            .map(|s| s.iter().map(|(k, d)| (k.to_lowercase(), d)).collect())
            .unwrap_or_default();
        let mut refused: Vec<(String, String)> = Vec::new();
        for (input, v) in &given {
            let Some((name, feeds)) = mine.get(&input.to_lowercase()).or_else(|| mine.get("*"))
            else {
                continue;
            };
            if settings.contains_key(&input.to_lowercase()) && *name != "*" {
                match links.word(*v) {
                    Some(w) if takes(feeds, &w) => {}
                    Some(w) => refused.push(((*input).to_owned(), w)),
                    None => refused.push(((*input).to_owned(), links.describe(*v))),
                }
            } else if !links.accepts(*v, feeds, links.color(&c.name, input), &mut st) {
                let label = if *name == "*" { *input } else { *name };
                refused.push((label.to_owned(), links.describe(*v)));
            }
        }
        let written: HashSet<String> = given.iter().map(|(i, _)| i.to_lowercase()).collect();
        for (s, default) in &settings {
            if let Some((name, feeds)) = mine.get(s) {
                if !written.contains(s) && !default.as_deref().is_some_and(|d| takes(feeds, d)) {
                    let what = default.as_deref().unwrap_or("none").to_owned();
                    refused.push(((*name).to_owned(), what));
                }
            }
        }
        let values: HashMap<String, Value> =
            given.iter().map(|(i, v)| (i.to_lowercase(), *v)).collect();
        for (inputs, feeds) in many.get(c.name.as_str()).into_iter().flatten() {
            let together: Vec<Value> = inputs
                .iter()
                .map(|i| match i.split_once('.') {
                    Some((node, input)) => elsewhere(node, input),
                    None => values.get(i).copied().unwrap_or(Value::Default),
                })
                .collect();
            if refused
                .iter()
                .any(|(r, _)| inputs.contains(&r.to_lowercase()))
                && links.group(&together, feeds, &mut st)
            {
                refused.retain(|(r, _)| !inputs.contains(&r.to_lowercase()));
            }
        }
        eaten.extend(st.eaten);
        for (input, what) in refused {
            out.push((call_id(c), issue(c, format!("{}.{input} ← {what}", c.name))));
        }
    }
    let mut out: Vec<Issue> = out
        .into_iter()
        .filter(|(k, _)| !eaten.contains(k))
        .map(|(_, i)| i)
        .collect();
    // Of a node the destination reads once, it reads the last the material reaches, inputs in order
    if let Some(e) = &output {
        let mut reached = Vec::new();
        links.reach(e, &mut reached, &mut HashSet::new());
        for node in &target.once {
            let reach: Vec<&Call> = reached
                .iter()
                .filter(|c| &c.name == node && !eaten.contains(&call_id(c)))
                .copied()
                .collect();
            for c in reach.iter().take(reach.len().saturating_sub(1)) {
                out.push(issue(c, format!("{node} (not the one read)")));
            }
        }
    }
    out
}

// ---- Translators ----

/// Why the text, fitting `source`, does not reach `target` through its translator; none when
/// `target` has no translator from `source`.
///
/// A node the translator sends to a bridge (`module::graph`) reaches `target` when the target has
/// that graph and it fits the target.
pub fn translation_issues(
    file: &File,
    source: &str,
    target: &str,
) -> Result<Option<Vec<Issue>>, UnknownTarget> {
    let t = load_target(target)?;
    if !t.translators.contains_key(source) {
        return Ok(None);
    }
    let source = load_target(source)?;
    let file = Rc::new(file.clone());
    Ok(translation_issues_in(&file, source, t, &Modules::new(None)))
}

fn translation_issues_in(
    file: &Rc<File>,
    source: &Target,
    t: &Target,
    modules: &Modules,
) -> Option<Vec<Issue>> {
    let tr = t.translators.get(&source.name)?;
    let issues = issues_of(file, source, modules);
    if !issues.is_empty() {
        return Some(issues);
    }
    let local = local_names(file, &|n| modules.find(source, n));
    let issue = |g: &Graph, what: &str, name: String, u: &Use| Issue {
        graph: g.name.clone(),
        what: what.to_owned(),
        name,
        line: u.line,
        col: u.col,
        target: t.name.clone(),
    };
    let mut out = Vec::new();
    for g in &file.graphs {
        for u in uses_of(g, &local, &g.kind) {
            let ok = match u.what {
                "kind" => tr.kinds.contains_key(&g.kind) || t.kinds.contains(&g.kind),
                "node" => match u.names.iter().find_map(|n| tr.nodes.get(n)) {
                    None => false,
                    Some(to) if to.node().contains("::") => {
                        match bridge_issues(to.node(), t, modules) {
                            None => false,
                            Some(inner) => {
                                if let Some(first) = inner.first() {
                                    let name =
                                        format!("{} ({} {})", to.node(), first.what, first.name);
                                    out.push(issue(g, "graph", name, &u));
                                }
                                true
                            }
                        }
                    }
                    Some(_) => true,
                },
                what => t.accepts(what, &g.kind, false, &u.names),
            };
            if !ok {
                out.push(issue(g, u.what, u.name(), &u));
            }
        }
    }
    Some(out)
}

/// The Issues of the bridge graph `module::graph` of `target` outside it; none when the target has
/// no such graph.
fn bridge_issues(name: &str, target: &Target, modules: &Modules) -> Option<Vec<Issue>> {
    let (module, k) = name.split_once("::")?;
    let m = modules.bridge(target, module)?;
    let at = m.graphs.iter().position(|g| key(&g.name) == k)?;
    Some(graph_issues_in(
        &m,
        at,
        target,
        modules,
        &HashSet::new(),
        None,
    ))
}

/// Whether a check against `target` follows the module `name` of a `use`: a bridge of the target
/// or a stdlib module.
pub fn follows(target: &Target, name: &str) -> bool {
    Modules::new(None).find(target, name).is_some()
}

/// Whether `name` (`module::graph`) is a graph of a bridge of `target`.
pub fn is_bridge(target: &Target, name: &str) -> bool {
    bridge_issues(name, target, &Modules::new(None)).is_some()
}

/// A copy of the text for `target`: kinds and nodes renamed by its translator from `source`.
///
/// A node sent to a bridge becomes a call of its module (`blender_interop::kuwahara`), and the text
/// uses the module, once. Fails with the issues, a line each, when the text does not reach
/// `target` that way.
pub fn translate(file: &File, source: &str, target: &str) -> Result<File, String> {
    let issues = translation_issues(file, source, target)
        .map_err(|e| e.to_string())?
        .ok_or_else(|| format!("target '{target}' has no translator from '{source}'"))?;
    if !issues.is_empty() {
        return Err(issues
            .iter()
            .map(|i| i.to_string())
            .collect::<Vec<_>>()
            .join("\n"));
    }
    let tr = &load_target(target).expect("checked above").translators[source];
    let mut out = file.clone();
    let mut bridged = Vec::new();
    for g in &mut out.graphs {
        if let Some(k) = tr.kinds.get(&g.kind) {
            g.kind = k.clone();
        }
        rename_stmts(&mut g.body, tr, &mut bridged);
    }
    for module in bridged {
        let used = out
            .uses
            .iter()
            .any(|u| u.name == module && u.alias.as_ref().is_none_or(|a| *a == module));
        if !used {
            out.uses.push(UseLine {
                name: module,
                alias: None,
                names: None,
                source: None,
                line: 0,
                col: 0,
            });
        }
    }
    Ok(out)
}

/// The modules of the bridges the renamed calls call, in the order of the text.
type Bridged = Vec<String>;

fn rename_stmts(body: &mut [Stmt], tr: &Translator, bridged: &mut Bridged) {
    for s in body {
        match s {
            Stmt::Assign(a) => match &mut a.value {
                AssignValue::Expr(e) => rename_expr(e, tr, bridged),
                AssignValue::BodyCall(z) => {
                    rename_args(&mut z.args, tr, bridged);
                    rename_stmts(&mut z.body, tr, bridged);
                }
                AssignValue::NamelessGraph(z) => rename_stmts(&mut z.body, tr, bridged),
            },
            Stmt::Return(r) => match &mut r.value {
                ReturnValue::Expr(e) => rename_expr(e, tr, bridged),
                ReturnValue::Record(rec) => rename_args(&mut rec.fields, tr, bridged),
            },
            Stmt::Frame(f) => rename_stmts(&mut f.body, tr, bridged),
        }
    }
}

fn rename_args(args: &mut [Arg], tr: &Translator, bridged: &mut Bridged) {
    for a in args {
        rename_expr(&mut a.value, tr, bridged);
    }
}

fn rename_expr(e: &mut Expr, tr: &Translator, bridged: &mut Bridged) {
    match e {
        Expr::Call(c) => {
            if let Some(r) = tr.nodes.get(&c.name) {
                c.name = r.node().to_owned();
                if let Some((module, _)) = c.name.split_once("::") {
                    if !bridged.iter().any(|b| b == module) {
                        bridged.push(module.to_owned());
                    }
                }
                for a in &mut c.args {
                    if let Some(n) = &a.name {
                        a.name = Some(r.arg(n).to_owned());
                    }
                }
            }
            rename_args(&mut c.args, tr, bridged);
        }
        Expr::BinOp(b) => {
            rename_expr(&mut b.left, tr, bridged);
            rename_expr(&mut b.right, tr, bridged);
        }
        Expr::Neg(n) => rename_expr(&mut n.value, tr, bridged),
        Expr::Not(n) => rename_expr(&mut n.value, tr, bridged),
        Expr::Cond(c) => {
            rename_expr(&mut c.cond, tr, bridged);
            rename_expr(&mut c.then, tr, bridged);
            rename_expr(&mut c.orelse, tr, bridged);
        }
        Expr::Pipe(p) => {
            rename_expr(&mut p.left, tr, bridged);
            rename_expr(&mut p.call, tr, bridged);
        }
        Expr::Member(m) => rename_expr(&mut m.target, tr, bridged),
        Expr::Tuple(t) => {
            for i in &mut t.items {
                rename_expr(i, tr, bridged);
            }
        }
        Expr::Number(_) | Expr::String(_) | Expr::Bool(_) | Expr::Ref(_) => {}
    }
}

// ---- Inference ----

/// Which targets accept a text.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Inference {
    /// target -> none when it accepts the text as it is, else the target it translates from; sorted
    pub fits: BTreeMap<String, Option<String>>,
    /// target -> its Issues, for the targets that do not accept the text; sorted
    pub outside: BTreeMap<String, Vec<Issue>>,
    /// (graph name, the targets that accept it as it is), in the order of the text
    pub graphs: Vec<(String, Vec<String>)>,
}

impl Inference {
    /// What an editor shows: `Compatible: …`, `Outside …: …`.
    pub fn lines(&self) -> Vec<String> {
        let mut native: Vec<String> = Vec::new();
        let mut translated: Vec<String> = Vec::new();
        for (t, v) in &self.fits {
            match v {
                None => native.push(t.clone()),
                Some(s) => translated.push(format!("{t} (translated from {s})")),
            }
        }
        native.extend(translated);
        let fits = if native.is_empty() {
            "none".to_owned()
        } else {
            native.join(", ")
        };
        let mut out = vec![format!("Compatible: {fits}")];
        for (t, issues) in &self.outside {
            let first = &issues[0];
            let more = if issues.len() > 1 {
                format!(" and {} more", issues.len() - 1)
            } else {
                String::new()
            };
            out.push(format!(
                "Outside {t}: {} {} (line {}){more}",
                first.what, first.name, first.line
            ));
        }
        out
    }
}

/// Which targets accept the text: as it is, or through one of their translators.
pub fn infer(file: &File) -> Inference {
    infer_in(file, None)
}

/// The same, the modules the text uses found by `resolve` first, then in the stdlib.
pub fn infer_with(file: &File, resolve: Resolver) -> Inference {
    infer_in(file, Some(resolve))
}

fn infer_in(file: &File, resolve: Option<Resolver>) -> Inference {
    let file = Rc::new(file.clone());
    let modules = Modules::new(resolve);
    let mut inf = Inference::default();
    // A variant of `blender` narrows the trees of some kinds (shaders, for each of today's): it is
    // tried only for a text that holds a graph of one of them. For another text it would only say
    // that the kind is not its own.
    let tried: Vec<&Target> = inferred_names()
        .into_iter()
        .filter_map(|n| load_target(n).ok())
        .filter(|t| !t.name.contains(' ') || file.graphs.iter().any(|g| t.kinds.contains(&g.kind)))
        .collect();
    for t in &tried {
        let issues = issues_of(&file, t, &modules);
        if issues.is_empty() {
            inf.fits.insert(t.name.clone(), None);
        } else {
            inf.outside.insert(t.name.clone(), issues);
        }
    }
    let outside: Vec<String> = inf.outside.keys().cloned().collect();
    for t in outside {
        let target = load_target(&t).expect("a target of the list");
        for source in target.translators.keys() {
            let native = matches!(inf.fits.get(source), Some(None));
            let Ok(from) = load_target(source) else {
                continue;
            };
            if native
                && translation_issues_in(&file, from, target, &modules)
                    .is_some_and(|i| i.is_empty())
            {
                inf.fits.insert(t.clone(), Some(source.clone()));
                inf.outside.remove(&t);
                break;
            }
        }
    }
    inf.graphs = file
        .graphs
        .iter()
        .enumerate()
        .map(|(i, g)| {
            let fit = tried
                .iter()
                .filter(|t| {
                    graph_issues_in(&file, i, t, &modules, &HashSet::new(), None).is_empty()
                })
                .map(|t| t.name.clone())
                .collect();
            (g.name.clone(), fit)
        })
        .collect();
    inf
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_issue_every_version_has_is_the_target_s_another_the_version_s() {
        // Two versions, as `blender` will hold with the catalog of Blender 5.2: the older has no Kuwahara
        let newer = load_target("blender@5.3").unwrap().clone();
        let mut older = newer.clone();
        older.name = "blender@5.2-lts".to_owned();
        let compositor = older.trees.get_mut("compositor").unwrap();
        compositor.nodes.retain(|n| n != "Kuwahara");
        let both = Target {
            name: "blender".to_owned(),
            kinds: newer.kinds.clone(),
            members: vec![older, newer],
            ..Target::default()
        };
        let f = base_node::parse(
            "compositor graph g(image: Color) -> Color {\n  return Kuwahara(Cube(image))\n}\n",
            "t.bn",
        )
        .unwrap();
        let said: Vec<(String, String)> = check_against(&f, &both, None)
            .into_iter()
            .map(|i| (i.name, i.target))
            .collect();
        assert_eq!(
            said,
            [
                ("Kuwahara".to_owned(), "blender@5.2-lts".to_owned()),
                ("Cube".to_owned(), "blender".to_owned())
            ]
        );
    }

    #[test]
    fn a_version_as_a_text_names_it() {
        let b = Blender {
            versions: vec!["5.2".to_owned(), "5.3".to_owned()],
            promised: vec!["5.2".to_owned(), "5.3".to_owned()],
            lts: vec!["5.2".to_owned()],
            variants: vec!["gltf".to_owned()],
            names: Vec::new(),
            targets: Vec::new(),
        };
        assert_eq!(b.name("5.2"), "blender@5.2-lts");
        assert_eq!(b.name("5.3"), "blender@5.3");
        assert_eq!(
            (b.alias("lts"), b.alias("latest")),
            (Some("5.2"), Some("5.3"))
        );
        assert!(
            b.refusal(Some("5.2-lts"), &[]).is_none()
                && b.refusal(Some("lts"), &["gltf"]).is_none()
        );
        let hint = |version: &str| match b.refusal(Some(version), &[]) {
            Some(Refusal::Unknown(hint)) => hint,
            _ => None,
        };
        assert_eq!(
            hint("5.2").as_deref(),
            Some("Blender 5.2 is an LTS: write 'blender@5.2-lts'")
        );
        assert_eq!(
            hint("5.3-lts").as_deref(),
            Some("Blender 5.3 is not an LTS: write 'blender@5.3'")
        );
    }

    #[test]
    fn the_bridges_of_every_target_are_built_in_and_parse() {
        let mut paths: Vec<&str> = targets()
            .flat_map(|t| t.bridges.iter().map(String::as_str))
            .collect();
        paths.sort();
        let built_in: Vec<&str> = BRIDGES.iter().map(|(p, _)| *p).collect();
        assert_eq!(paths, built_in);
        for (path, text) in BRIDGES {
            let on_disk = format!("{}/../targets/{path}", env!("CARGO_MANIFEST_DIR"));
            assert!(std::path::Path::new(&on_disk).is_file(), "{path}");
            assert!(base_node::parse(text, path).is_ok(), "{path}");
        }
    }
}
