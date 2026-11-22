//! A name the printer writes, the lexer reads back as that name, wherever a name is written: the
//! test of python/tests/test_names.py, with the Rust core.
//!
//! The names are those of corpus/v1 and of the backends of Blender 5.2 and 5.3, those of
//! conformance/name-cases.json (adversarial and random ones) and random ones of this test. Each
//! is put where a name goes in a syntax tree, printed by the formatter, which decides bare or
//! quoted, and read back. A name the grammar takes no quote for (a binding, a `use`, an `as`) is
//! written by its key, which must be a bare identifier, its own key.

use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::sync::OnceLock;

use base_node::ast::{is_bare, is_identifier, is_word, key, RESERVED};
use base_node::{format_file, parse, tokenize, File, TokenKind};
use serde_json::{json, Value};

/// Every place a name is printed, in one text: graph, panel, input, `as`, output, binding, input
/// key, output access, setting, module path, frame, return field, `use` and its file.
const TEMPLATE: &str = "use m as n (k) from \"m.bn\"\n\ngeometry graph g(\"Panel\" {\n    \"P\" as templatealias: Float,\n    templateinput: Float\n  }) -> (o: Float) {\n  b = F[E, s: 1.0](i: templateinput).o\n  \"Frame\" {\n    c = m::h(b)\n  }\n  return (o: c)\n}\n";

const CALL: &str = "/graphs/0/body/0/Assign/value/Expr/Member/target/Call";
const FRAME_CALL: &str = "/graphs/0/body/1/Frame/body/0/Assign/value/Expr/Call";

/// Each string a syntax tree holds under `name`, `socket`, `alias` or `label`, and the enum
/// values and strings of the settings.
fn walk(v: &Value, out: &mut BTreeSet<String>) {
    match v {
        Value::Object(map) => {
            for field in ["name", "socket", "alias", "label"] {
                if let Some(Value::String(s)) = map.get(field) {
                    out.insert(s.clone());
                }
            }
            for value in map.values() {
                walk(value, out);
            }
        }
        Value::Array(items) => items.iter().for_each(|i| walk(i, out)),
        _ => {}
    }
}

fn root() -> &'static Path {
    Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/.."))
}

fn corpus(dir: &Path, out: &mut BTreeSet<String>) {
    for entry in fs::read_dir(dir).unwrap().flatten() {
        let path = entry.path();
        if path.is_dir() {
            corpus(&path, out);
        } else if path.extension().is_some_and(|x| x == "bn") {
            let text = fs::read_to_string(&path).unwrap();
            let file = parse(&text, path.to_str().unwrap()).unwrap();
            walk(&serde_json::to_value(&file).unwrap(), out);
        }
    }
}

/// (names, setting names) of the two backends: their nodes, sockets, settings, enum values and
/// the graphs of their modules.
fn backends() -> (BTreeSet<String>, BTreeSet<String>) {
    let (mut names, mut settings) = (BTreeSet::new(), BTreeSet::new());
    let text = |v: &Value| v.as_str().map(str::to_owned);
    for version in ["5.2", "5.3"] {
        let dir = root().join("targets/backends");
        let path = dir.join(format!("blender-{version}.json"));
        let data: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
        for nodes in data["kinds"].as_object().unwrap().values() {
            for node in nodes.as_array().unwrap() {
                names.extend(text(&node["name"]));
                names.extend(text(&node["label"]));
                for s in node["settings"].as_array().into_iter().flatten() {
                    settings.extend(text(&s["name"]));
                    for item in s["items"].as_array().into_iter().flatten() {
                        names.extend(text(&item["value"]));
                    }
                }
                let variants = node["variants"].as_array().cloned().unwrap_or_default();
                for shape in std::iter::once(node).chain(variants.iter()) {
                    for side in ["inputs", "outputs"] {
                        for sock in shape[side].as_array().into_iter().flatten() {
                            for field in ["name", "key", "identifier"] {
                                names.extend(text(&sock[field]));
                            }
                        }
                    }
                }
            }
        }
        for entry in fs::read_dir(dir.join(format!("blender-{version}")))
            .unwrap()
            .flatten()
        {
            let module: Value =
                serde_json::from_str(&fs::read_to_string(entry.path()).unwrap()).unwrap();
            names.extend(module.as_object().unwrap().keys().cloned());
        }
    }
    (names, settings)
}

fn cases() -> Vec<Value> {
    let path = root().join("conformance/name-cases.json");
    let doc: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    doc["cases"].as_array().unwrap().clone()
}

/// Names of characters of every kind, ASCII and beyond: a property test with no library.
fn random_names(count: usize) -> Vec<String> {
    let alphabet: Vec<char> = "aZ_09 -.:\"\\·⋅×²٣éΣ\u{301}\u{200d}🙏日".chars().collect();
    let mut state: u64 = 0x2545_f491_4f6c_dd1d;
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    (0..count)
        .map(|_| {
            let n = next() % 7;
            (0..n)
                .map(|_| {
                    let r = next();
                    if r % 10 < 6 {
                        alphabet[(r / 10) as usize % alphabet.len()]
                    } else {
                        char::from_u32((r >> 8) as u32 % 0x11_0000).unwrap_or('a')
                    }
                })
                .collect()
        })
        .collect()
}

/// Most names are words of ASCII letters, digits and `_`, which print and read alike: a few
/// hundred stand for the others, and every other name is tried.
fn names() -> &'static (Vec<String>, BTreeSet<String>) {
    static NAMES: OnceLock<(Vec<String>, BTreeSet<String>)> = OnceLock::new();
    NAMES.get_or_init(collect)
}

fn collect() -> (Vec<String>, BTreeSet<String>) {
    let mut all = BTreeSet::new();
    corpus(&root().join("corpus/v1"), &mut all);
    let (backend, settings) = backends();
    all.extend(backend);
    all.extend(settings.iter().cloned());
    all.extend(
        cases()
            .iter()
            .map(|c| c["name"].as_str().unwrap().to_owned()),
    );
    all.extend(random_names(3000));
    let plain = |n: &str| {
        n.chars()
            .next()
            .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
            && n.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
            && !RESERVED.contains(&n)
    };
    let mut out: Vec<String> = all.iter().filter(|n| !plain(n)).cloned().collect();
    out.extend(all.iter().filter(|n| plain(n)).step_by(20).cloned());
    (out, settings)
}

fn reference(name: &str) -> Value {
    json!({"Ref": {"name": name, "line": 0, "col": 0}})
}

fn ref_or_string(name: &str) -> Value {
    if is_word(name) {
        reference(name)
    } else {
        json!({"String": {"value": name, "line": 0, "col": 0}})
    }
}

/// A place a name is printed: where, the changes it makes (a pointer of the syntax tree and the
/// value put there), and what each of the pointers it reads must hold once printed and read back.
struct Place {
    name: &'static str,
    set: Vec<(String, Value)>,
    read: Vec<(String, Value)>,
}

fn place(name: &'static str, set: Vec<(String, Value)>) -> Place {
    let read = set.clone();
    Place { name, set, read }
}

fn at(path: &str, value: impl Into<Value>) -> (String, Value) {
    (path.to_owned(), value.into())
}

fn places(n: &str) -> Vec<Place> {
    let k = key(n);
    let panel = "/graphs/0/param_tree/0/Panel";
    let mut enum_value = place(
        "enum value",
        vec![at(&format!("{CALL}/settings/0/value"), ref_or_string(n))],
    );
    // Read back, a value is a name or a string, its position aside
    enum_value.read = vec![if is_word(n) {
        at(&format!("{CALL}/settings/0/value/Ref/name"), n)
    } else {
        at(&format!("{CALL}/settings/0/value/String/value"), n)
    }];
    vec![
        place("graph name", vec![at("/graphs/0/name", n)]),
        place("panel", vec![at(&format!("{panel}/name"), n)]),
        place(
            "input",
            vec![
                at(&format!("{panel}/items/1/Param/name"), n),
                at("/graphs/0/params/1/name", n),
            ],
        ),
        place(
            "as key",
            vec![
                at(&format!("{panel}/items/0/Param/name"), n),
                at(&format!("{panel}/items/0/Param/alias"), k.as_str()),
                at("/graphs/0/params/0/name", n),
                at("/graphs/0/params/0/alias", k.as_str()),
            ],
        ),
        place("output", vec![at("/graphs/0/outputs/0/name", n)]),
        place(
            "return field",
            vec![at("/graphs/0/body/2/Return/value/Record/fields/0/name", n)],
        ),
        place("input key", vec![at(&format!("{CALL}/args/0/name"), n)]),
        place(
            "output access",
            vec![at("/graphs/0/body/0/Assign/value/Expr/Member/socket", n)],
        ),
        enum_value,
        place(
            "module path",
            vec![at(&format!("{FRAME_CALL}/name"), format!("m::{n}"))],
        ),
        place("frame title", vec![at("/graphs/0/body/1/Frame/label", n)]),
        Place {
            name: "binding",
            set: vec![
                at("/graphs/0/body/0/Assign/name", k.as_str()),
                at(&format!("{FRAME_CALL}/args/0/value"), reference(&k)),
            ],
            read: vec![
                at("/graphs/0/body/0/Assign/name", k.as_str()),
                at(&format!("{FRAME_CALL}/args/0/value/Ref/name"), k.as_str()),
            ],
        },
        place("use", vec![at("/uses/0/names", json!([k]))]),
        place("use source", vec![at("/uses/0/source", n)]),
    ]
}

/// What of `places` does not read back: the name put in each of them, printed once.
fn mismatches(template: &Value, n: &str, places: &[&Place]) -> Vec<String> {
    let mut tree = template.clone();
    for p in places {
        for (path, value) in &p.set {
            *tree.pointer_mut(path).unwrap_or_else(|| panic!("{path}")) = value.clone();
        }
    }
    let file: File = serde_json::from_value(tree).unwrap();
    let text = format_file(&file);
    let back = match parse(&text, "names.bn") {
        Ok(f) => serde_json::to_value(&f).unwrap(),
        Err(e) if places.len() == 1 => {
            return vec![format!("{}: {n:?} is refused: {e}", places[0].name)];
        }
        // Which place makes the text unreadable: each on its own
        Err(_) => {
            return places
                .iter()
                .flat_map(|p| mismatches(template, n, &[p]))
                .collect();
        }
    };
    let mut out = Vec::new();
    for p in places {
        for (path, value) in &p.read {
            if back.pointer(path) != Some(value) {
                out.push(format!(
                    "{}: {n:?} read back as {:?}",
                    p.name,
                    back.pointer(path)
                ));
            }
        }
    }
    out
}

#[test]
fn every_name_reads_back_wherever_it_is_printed() {
    let template = serde_json::to_value(parse(TEMPLATE, "names.bn").unwrap()).unwrap();
    let (names, _) = names();
    let mut wrong = Vec::new();
    for n in names {
        let places = places(n);
        let all: Vec<&Place> = places.iter().collect();
        wrong.extend(mismatches(&template, n, &all));
    }
    assert!(
        wrong.is_empty(),
        "{} mismatches, of {} names:\n{}",
        wrong.len(),
        names.len(),
        wrong[..wrong.len().min(40)].join("\n")
    );
}

#[test]
fn a_setting_name_reads_back() {
    let template = serde_json::to_value(parse(TEMPLATE, "names.bn").unwrap()).unwrap();
    let (_, settings) = names();
    // The grammar takes no quoted setting name: every setting of Blender is written bare
    assert!(!settings.is_empty());
    for s in settings {
        assert!(is_bare(s), "{s}");
        let p = place(
            "setting",
            vec![at(&format!("{CALL}/settings/1/name"), s.as_str())],
        );
        assert_eq!(mismatches(&template, s, &[&p]), Vec::<String>::new());
    }
}

#[test]
fn a_key_is_a_bare_name_of_its_own() {
    for n in &names().0 {
        let k = key(n);
        assert!(is_bare(&k) && key(&k) == k, "{n:?} {k:?}");
        let tokens = tokenize(&k, "k", true).unwrap();
        assert_eq!(tokens.len(), 2, "{n:?} {k:?}");
        assert!(tokens[0].kind == TokenKind::Ident && tokens[0].text == k);
    }
}

#[test]
fn bare_is_what_the_lexer_reads_as_one_name() {
    for n in &names().0 {
        let tokens = if n.is_empty() {
            vec![]
        } else {
            tokenize(n, "n", false).unwrap()
        };
        let one = tokens.len() == 2 && tokens[0].kind == TokenKind::Ident && tokens[0].text == *n;
        assert_eq!(is_bare(n), one && !RESERVED.contains(&n.as_str()), "{n:?}");
        assert!(!one || is_identifier(n), "{n:?}");
    }
}

/// The key and the printed form of a name, as python/tests/test_names.py finds them.
#[test]
fn name_cases_read_as_python_reads_them() {
    let doc: Value = serde_json::from_str(
        &fs::read_to_string(root().join("conformance/name-cases.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(doc["unicode"], base_node::UNICODE_VERSION);
    for case in cases() {
        let n = case["name"].as_str().unwrap();
        assert_eq!(key(n), case["key"].as_str().unwrap(), "{n:?}");
        assert_eq!(is_bare(n), case["bare"].as_bool().unwrap(), "{n:?}");
        assert_eq!(is_word(n), case["word"].as_bool().unwrap(), "{n:?}");
    }
}
