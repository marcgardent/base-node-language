//! A .bn text may come from anyone: reading it ends with a tree or an error, never a panic,
//! a stack overflow or a hang.
//!
//! The limits are those of spec/reference.md, "Limits"; python/tests/test_limits.py holds the same cases.

use std::fs;
use std::path::Path;

use base_node::{format_source, parse, tokenize, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES};

const HEAD: &str = "geometry graph g(a: Float, v: Vector) -> Float {\n  return ";
const TAIL: &str = "\n}\n";

/// The source of a shape nested n times.
fn shape(name: &str, n: usize) -> String {
    match name {
        "parentheses" => format!("{HEAD}{}a{}{TAIL}", "(".repeat(n), ")".repeat(n)),
        "minus" => format!("{HEAD}{}a{TAIL}", "-".repeat(n)),
        "not" => format!("{HEAD}{}a{TAIL}", "not ".repeat(n)),
        "calls" => format!("{HEAD}{}a{}{TAIL}", "abs(".repeat(n), ")".repeat(n)),
        "options" => format!("{HEAD}abs({}{}{TAIL}", "x(".repeat(n - 1), ")".repeat(n)),
        "frames" => format!(
            "geometry graph g(a: Float) -> Float {{\n{}{}  return a\n}}\n",
            "{\n".repeat(n),
            "}\n".repeat(n)
        ),
        "zones" => format!(
            "geometry graph g(a: Float) -> Float {{\n{}{}return a\n}}\n",
            "x = repeat(2, a: a) -> {\n".repeat(n),
            "return a\n}\n".repeat(n)
        ),
        "panels" => format!(
            "geometry graph g({}a: Float{}) -> Float {{\n  return a\n}}\n",
            "\"P\" { ".repeat(n),
            " }".repeat(n)
        ),
        _ => unreachable!(),
    }
}

const SHAPES: [&str; 8] = [
    "parentheses",
    "minus",
    "not",
    "calls",
    "options",
    "frames",
    "zones",
    "panels",
];

/// What stands side by side in the text and one inside another in the tree: n operators.
fn chain(name: &str, n: usize) -> String {
    let (first, step) = match name {
        "plus" => ("a", " + a"),
        "times" => ("a", " * a"),
        "and" => ("a", " and a"),
        "or" => ("a", " or a"),
        "pipe" => ("a", " |> abs()"),
        "member" => ("v", ".x"),
        _ => unreachable!(),
    };
    format!("{HEAD}{first}{}{TAIL}", step.repeat(n))
}

const CHAINS: [&str; 6] = ["plus", "times", "and", "or", "pipe", "member"];

fn message(source: &str) -> String {
    match parse(source, "<test>") {
        Ok(_) => "parsed".to_string(),
        Err(e) => e.diagnostics[0].message.clone(),
    }
}

#[test]
fn nesting_up_to_the_limit() {
    for name in SHAPES {
        let source = shape(name, MAX_NESTING);
        assert_eq!(message(&source), "parsed", "{name}");
        format_source(&source, "<test>").unwrap_or_else(|e| panic!("{name}: {e}"));
    }
}

#[test]
fn nesting_past_the_limit_is_an_error() {
    for name in SHAPES {
        for n in [MAX_NESTING + 1, 20_000] {
            let found = message(&shape(name, n));
            assert!(found.contains("nested too deeply"), "{name} {n}: {found}");
        }
    }
}

#[test]
fn chain_up_to_the_limit() {
    for name in CHAINS {
        let source = chain(name, MAX_HEIGHT - 1);
        assert_eq!(message(&source), "parsed", "{name}");
        format_source(&source, "<test>").unwrap_or_else(|e| panic!("{name}: {e}"));
    }
}

#[test]
fn chain_past_the_limit_is_an_error() {
    for name in CHAINS {
        for n in [MAX_HEIGHT, 20_000] {
            let found = message(&chain(name, n));
            assert!(found.contains("nested too deeply"), "{name} {n}: {found}");
        }
    }
}

#[test]
fn chains_inside_brackets_add_up() {
    // Neither the brackets nor one chain passes its limit; the tree they make does
    let nested = |levels: usize| {
        let step = format!("{})", " + a".repeat(MAX_HEIGHT / 8));
        format!(
            "{HEAD}{}a{}{TAIL}",
            "abs(".repeat(levels),
            step.repeat(levels)
        )
    };
    assert_eq!(message(&nested(7)), "parsed");
    assert!(message(&nested(9)).contains("nested too deeply"));
}

#[test]
fn number_too_large() {
    let nines = "9".repeat(100_000);
    for number in ["9223372036854775808", nines.as_str(), "1e999", "1.0e400"] {
        let found = message(&format!("{HEAD}{number}{TAIL}"));
        assert_eq!(found, "number too large", "{}", &number[..7]);
    }
    assert_eq!(
        message(&format!("{HEAD}9223372036854775807{TAIL}")),
        "parsed"
    );
    assert_eq!(message(&format!("{HEAD}1.7e308{TAIL}")), "parsed");
}

#[test]
fn source_too_large() {
    let padding = format!("// {}\n", "x".repeat(1020));
    let source = format!(
        "{}{HEAD}a{TAIL}",
        padding.repeat(MAX_SOURCE_BYTES / 1024 + 1)
    );
    assert!(message(&source).contains("source too large"));
    assert!(format_source(&source, "<test>").is_err());
    // Bytes of UTF-8 are counted, not characters
    let accents = format!("// {}\n{HEAD}a{TAIL}", "é".repeat(MAX_SOURCE_BYTES / 2));
    assert!(message(&accents).contains("source too large"));
}

fn corpus() -> Vec<String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    let mut sources = Vec::new();
    for folder in ["conformance", "python/tests/fixtures"] {
        let mut paths: Vec<_> = fs::read_dir(root.join(folder))
            .unwrap_or_else(|e| panic!("{folder}: {e}"))
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|x| x == "bn"))
            .collect();
        paths.sort();
        sources.extend(paths.iter().map(|p| fs::read_to_string(p).unwrap()));
    }
    assert!(sources.len() >= 7);
    sources
}

fn read(source: &str) {
    let _ = tokenize(source, "<test>", false);
    let _ = parse(source, "<test>");
    let _ = format_source(source, "<test>");
}

#[test]
fn text_cut_anywhere_never_panics() {
    // A look ahead must not read past the end of file: `x = graph() ->` and nothing after
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    for name in [
        "conformance/all_features.bn",
        "python/tests/fixtures/zones.bn",
        "python/tests/fixtures/bundles.bn",
    ] {
        let source = fs::read_to_string(root.join(name)).unwrap();
        for (end, _) in source.char_indices() {
            read(&source[..end]);
        }
    }
    for tail in [
        "x = graph() ->",
        "x = graph() -> (a: Float)",
        "x = closure(",
        "x = simulate()",
        "x = f(a()",
    ] {
        let source = format!("geometry graph g() -> Float {{\n  {tail}");
        assert_ne!(message(&source), "parsed", "{tail}");
    }
}

/// A small generator, the same on every run: the cases must not depend on a crate or on the clock.
struct Rng(u64);

impl Rng {
    fn below(&mut self, n: usize) -> usize {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        (self.0 % n as u64) as usize
    }
}

const FRAGMENTS: [&str; 37] = [
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    ",",
    ":",
    "::",
    "=",
    "->",
    "|>",
    ".",
    "..",
    "@",
    "#",
    "\"",
    "\n",
    "-",
    "not ",
    "closure(",
    "repeat(",
    "simulate(",
    "foreach(",
    "use ",
    " as ",
    " in ",
    "return ",
    "graph ",
    "é",
    "\0",
    "999999999999999999999999999999",
    "1e999",
    "//",
    "\\",
    "\\u{",
    "inf",
];

/// The source with a few pieces dropped, doubled or put in, cut on character boundaries.
fn mutated(source: &str, rng: &mut Rng) -> String {
    let mut chars: Vec<char> = source.chars().collect();
    for _ in 0..1 + rng.below(4) {
        let i = rng.below(chars.len());
        let j = (i + rng.below(13)).min(chars.len());
        let piece: Vec<char> = match rng.below(3) {
            0 => Vec::new(),
            1 => chars[i..j].iter().chain(&chars[i..j]).copied().collect(),
            _ => FRAGMENTS[rng.below(FRAGMENTS.len())].chars().collect(),
        };
        chars.splice(i..j, piece);
    }
    chars.into_iter().collect()
}

#[test]
fn mutated_sources_never_panic() {
    let sources = corpus();
    let mut rng = Rng(20261115);
    for _ in 0..3_000 {
        let source = &sources[rng.below(sources.len())];
        read(&mutated(source, &mut rng));
    }
}
