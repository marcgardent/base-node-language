//! Tree -> text -> tree is exact: any string, inf and nan, a set of enum values read back as
//! written, as in Python (python/tests/test_exact.py). The cases about the text are shared
//! (conformance/exact-cases.json, read by conformance.rs); these look at the tree and the tokens.

use base_node::ast::{call_name, key, quote, snake, AssignValue, Expr, Stmt};
use base_node::format::format_expr;
use base_node::{format_source, parse, tokenize, TokenKind};

const HEAD: &str = "geometry graph g(a: Float) -> Float {\n";

/// The value of `x = …`, the first statement of a graph.
fn value(source: &str) -> Expr {
    let text = format!("{HEAD}  x = {source}\n  return a\n}}\n");
    let file = parse(&text, "x.bn").unwrap_or_else(|e| panic!("{e}"));
    match &file.graphs[0].body[0] {
        Stmt::Assign(a) => match &a.value {
            AssignValue::Expr(e) => e.clone(),
            other => panic!("{other:?}"),
        },
        other => panic!("{other:?}"),
    }
}

fn string_of(e: &Expr) -> String {
    match e {
        Expr::String(s) => s.value.clone(),
        other => panic!("{other:?}"),
    }
}

#[test]
fn any_string_reads_back_as_it_was() {
    let mut alphabet: Vec<char> = (0..0x80u8).map(char::from).collect();
    alphabet.extend(['é', '✓', '😀', '\u{2028}', '\u{feff}', '\u{10ffff}']);
    let mut seed: u64 = 7;
    let mut next = |below: usize| {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        (seed % below as u64) as usize
    };
    let mut strings: Vec<String> = ["", "\"", "\\", "\\u{41}", "\r\n", "\0", "\x7f"]
        .map(String::from)
        .to_vec();
    for _ in 0..500 {
        let len = next(12);
        strings.push((0..len).map(|_| alphabet[next(alphabet.len())]).collect());
    }
    for s in strings {
        let tokens = tokenize(&quote(&s), "q.bn", true).unwrap();
        assert_eq!(tokens.len(), 2, "{s:?}");
        assert_eq!((&tokens[0].kind, &tokens[0].text), (&TokenKind::String, &s));
        assert_eq!(tokens[0].width, quote(&s).chars().count());
    }
}

#[test]
fn the_canonical_escapes() {
    assert_eq!(quote("a\"b\\c"), r#""a\"b\\c""#);
    assert_eq!(quote("\n\t\r"), r#""\n\t\r""#);
    assert_eq!(quote("\0\x1b\x7f"), r#""\u{0}\u{1b}\u{7f}""#);
    assert_eq!(quote("é😀\u{2028}"), "\"é😀\u{2028}\"");
    assert_eq!(
        string_of(&value(r#""\u{1F600}\u{1f600}\u{000041}""#)),
        "😀😀A"
    );
    assert_eq!(string_of(&value("\"a\tb\"")), "a\tb");
}

#[test]
fn a_string_token_measures_its_source() {
    let tokens = tokenize(r#"x = "a\"b\u{1F600}" + y"#, "t.bn", true).unwrap();
    assert_eq!(tokens[2].text, "a\"b😀");
    assert_eq!((tokens[2].col, tokens[2].width), (5, 15));
    assert_eq!(tokens[3].col, 21);
}

#[test]
fn the_editor_reads_any_string() {
    for (line, text, width) in [
        ("\"abc", "abc", 4),
        (r#""a\qb""#, r"a\qb", 6),
        (r#""a\u{110000}"#, r"a\u{110000}", 12),
        ("\"ab\\", "ab\\", 4),
    ] {
        let t = &tokenize(line, "e.bn", false).unwrap()[0];
        assert_eq!((t.text.as_str(), t.width), (text, width), "{line}");
    }
}

#[test]
fn a_comment_after_an_escaped_string_stays_after_it() {
    let source = format!("{HEAD}  x = \"say \\\"hi\\\"\"  // a note\n  return a\n}}\n");
    assert_eq!(format_source(&source, "c.bn").unwrap(), source);
}

#[test]
fn an_unknown_escape_is_refused_at_its_backslash() {
    for escape in [
        r"\q",
        r"\u41",
        r"\u{}",
        r"\u{110000}",
        r"\u{d800}",
        r"\u{dfff}",
        r"\u{1234567}",
    ] {
        let e = tokenize(&format!("x = \"ok{escape}\""), "t.bn", true).unwrap_err();
        let d = &e.diagnostics[0];
        assert_eq!((d.line, d.col), (1, 8), "{escape}");
        assert!(d.message.starts_with("unknown escape '\\"), "{}", d.message);
        assert!(d.message.contains(r#"\", \\, \n, \t, \r and \u{…}"#));
    }
}

#[test]
fn inf_and_nan_are_floats() {
    let numbers: Vec<_> = ["inf", "-inf", "nan"]
        .iter()
        .map(|s| match value(s) {
            Expr::Number(n) => n,
            other => panic!("{other:?}"),
        })
        .collect();
    assert_eq!(numbers[0].value, f64::INFINITY);
    assert_eq!(numbers[1].value, f64::NEG_INFINITY);
    assert!(numbers[2].value.is_nan());
    assert!(numbers.iter().all(|n| !n.is_int));
    let printed: Vec<_> = numbers
        .iter()
        .map(|n| format_expr(&Expr::Number(n.clone()), 0))
        .collect();
    assert_eq!(printed, ["inf", "-inf", "nan"]);
    let mut minus_nan = numbers[2].clone();
    minus_nan.value = -f64::NAN;
    assert_eq!(format_expr(&Expr::Number(minus_nan), 0), "nan");
    let kinds: Vec<_> = tokenize("inf nan inf_x Inf nan2", "k.bn", true)
        .unwrap()
        .into_iter()
        .map(|t| t.kind)
        .collect();
    assert_eq!(
        kinds[..5],
        [
            TokenKind::Number,
            TokenKind::Number,
            TokenKind::Ident,
            TokenKind::Ident,
            TokenKind::Ident
        ]
    );
}

#[test]
fn a_setting_takes_inf() {
    let Expr::Call(c) = value("Value[value: -inf]()") else {
        panic!()
    };
    assert!(matches!(&c.settings[0].value, Expr::Number(n) if n.value == f64::NEG_INFINITY));
}

#[test]
fn inf_and_nan_are_reserved() {
    assert_eq!(snake("inf"), "inf_");
    assert_eq!(key("nan"), "nan_");
    assert_eq!(key("Inf"), "Inf");
    let text = format!("{HEAD}  r = repeat(2, nan: a) -> {{\n    return a\n  }}\n  return a\n}}\n");
    let e = parse(&text, "r.bn").unwrap_err();
    assert_eq!(
        e.diagnostics[0].message,
        "'nan' is a reserved word: choose another name"
    );
}

#[test]
fn a_qualified_name_after_the_module_is_quoted_when_not_identifiers() {
    assert_eq!(call_name("m::f"), "m::f");
    assert_eq!(call_name("m::a::b"), "m::a::b");
    assert_eq!(call_name("f"), "f");
    assert_eq!(call_name("m::Big Blend"), "m::\"Big Blend\"");
    assert_eq!(call_name("m::x::Big Blend"), "m::\"x::Big Blend\"");
    assert_eq!(call_name("m::true"), "m::\"true\"");
    assert_eq!(call_name("m::inf"), "m::\"inf\"");
    for name in [
        "m::Big Blend",
        "m::x::Big Blend",
        "m::say \"hi\"",
        "m::inf",
        "m::a::b",
    ] {
        let Expr::Call(c) = value(&format!("{}(a)", call_name(name))) else {
            panic!()
        };
        assert_eq!(c.name, name);
    }
}

#[test]
fn settings_hold_a_set_of_enum_values() {
    let read = |v: &str| {
        let Expr::Call(c) = value(&format!("HandleTypeSelection[mode: {v}]()")) else {
            panic!()
        };
        c.settings[0].value.clone()
    };
    let names = |e: &Expr| match e {
        Expr::Tuple(t) => t
            .items
            .iter()
            .map(|i| match i {
                Expr::Ref(r) => r.name.clone(),
                other => panic!("{other:?}"),
            })
            .collect::<Vec<_>>(),
        other => panic!("{other:?}"),
    };
    let (one, none, two) = (read("(LEFT,)"), read("()"), read("(LEFT, RIGHT)"));
    assert_eq!(names(&one), ["LEFT"]);
    assert!(names(&none).is_empty());
    assert_eq!(names(&two), ["LEFT", "RIGHT"]);
    assert!(matches!(read("(LEFT)"), Expr::Ref(r) if r.name == "LEFT"));
    let printed: Vec<_> = [&one, &none, &two]
        .iter()
        .map(|e| format_expr(e, 0))
        .collect();
    assert_eq!(printed, ["(LEFT,)", "()", "(LEFT, RIGHT)"]);
}

#[test]
fn a_one_item_tuple_spread_over_lines_keeps_its_comma() {
    let long = "A".repeat(100);
    let source = format!(
        "{HEAD}  x = HandleTypeSelection[\n    mode: (\n      {long},)]()\n  return a\n}}\n"
    );
    assert_eq!(format_source(&source, "l.bn").unwrap(), source);
}

#[test]
fn outside_settings_a_comma_makes_no_tuple() {
    assert!(matches!(value("(a,)"), Expr::Ref(_)));
}
