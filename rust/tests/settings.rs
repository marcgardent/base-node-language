//! Settings in brackets: `Name[SETTING, key: value](inputs)`, read by the core into `settings`, as
//! in Python (python/tests/test_settings.py). The shared cases of conformance/bracket-cases.json are
//! read by conformance.rs; these look at the tree.

use base_node::ast::{AssignValue, Call, Expr, Stmt};
use base_node::{parse, tokenize, TokenKind};

const HEAD: &str = "kind graph g(a: Float, s: String) -> Float {\n";

fn assigned(src: &str, n: usize) -> AssignValue {
    let file = parse(src, "s.bn").unwrap_or_else(|e| panic!("{e}"));
    match &file.graphs[0].body[n] {
        Stmt::Assign(a) => a.value.clone(),
        other => panic!("{other:?}"),
    }
}

/// The call of the first statement of a graph whose body is `line`, then `return a`.
fn call_of(line: &str) -> Call {
    match assigned(&format!("{HEAD}  {line}\n  return a\n}}\n"), 0) {
        AssignValue::Expr(Expr::Call(c)) => c,
        other => panic!("{other:?}"),
    }
}

fn refused(line: &str) -> (usize, usize, String) {
    let e = parse(&format!("{HEAD}  {line}\n  return a\n}}\n"), "s.bn").unwrap_err();
    let d = &e.diagnostics[0];
    (d.line, d.col, d.message.clone())
}

#[test]
fn brackets_are_tokens() {
    let kinds: Vec<TokenKind> = tokenize("M[X]()", "s.bn", true)
        .unwrap()
        .into_iter()
        .take(5)
        .map(|t| t.kind)
        .collect();
    assert_eq!(
        kinds,
        vec![
            TokenKind::Ident,
            TokenKind::Punct("[".into()),
            TokenKind::Ident,
            TokenKind::Punct("]".into()),
            TokenKind::Punct("(".into()),
        ]
    );
}

#[test]
fn settings_in_source_order_with_optional_keys() {
    let c = call_of("x = Math[ADD, use_clamp: true](Value: a, Value_001: 2.0)");
    let keys: Vec<Option<&str>> = c.settings.iter().map(|s| s.name.as_deref()).collect();
    assert_eq!(keys, vec![None, Some("use_clamp")]);
    assert!(matches!(&c.settings[0].value, Expr::Ref(r) if r.name == "ADD"));
    assert!(matches!(&c.settings[1].value, Expr::Bool(b) if b.value));
    let at: Vec<(usize, usize)> = c.settings.iter().map(|s| (s.line, s.col)).collect();
    assert_eq!(at, vec![(2, 12), (2, 17)]);
    assert_eq!(c.args.len(), 2);
}

#[test]
fn values_a_setting_takes() {
    let c = call_of(
        "x = T[-1, 2.5, \"4D\", false, _, (0.1, -0.2), Ramp((0.0, (1.0, 0.5, 0.0)), interpolation: EASE)]()",
    );
    let kinds: Vec<&str> = c
        .settings
        .iter()
        .map(|s| match &s.value {
            Expr::Number(_) => "Number",
            Expr::String(_) => "String",
            Expr::Bool(_) => "Bool",
            Expr::Ref(_) => "Ref",
            Expr::Tuple(_) => "Tuple",
            Expr::Call(_) => "Call",
            _ => "other",
        })
        .collect();
    assert_eq!(
        kinds,
        vec!["Number", "Number", "String", "Bool", "Ref", "Tuple", "Call"]
    );
    assert!(matches!(&c.settings[0].value, Expr::Number(n) if n.value == -1.0 && n.is_int));
    assert!(matches!(&c.settings[4].value, Expr::Ref(r) if r.name == "_"));
    let Expr::Call(ramp) = &c.settings[6].value else {
        panic!()
    };
    let names: Vec<Option<&str>> = ramp.args.iter().map(|a| a.name.as_deref()).collect();
    assert_eq!(names, vec![None, Some("interpolation")]);
    assert!(c.args.is_empty());
}

#[test]
fn body_call_and_pipe_and_template_take_settings() {
    let src = format!(
        "{HEAD}  r = each[FACE](a, item: a) -> {{\n    return item\n  }}\n  \
         p = a |> Store[INT, CURVE](name: \"i\")\n  t = pick<Vector>[POINT](s)\n  return a\n}}\n"
    );
    let names = |settings: &[base_node::ast::Setting]| -> Vec<String> {
        settings
            .iter()
            .map(|s| match &s.value {
                Expr::Ref(r) => r.name.clone(),
                other => panic!("{other:?}"),
            })
            .collect()
    };
    let AssignValue::BodyCall(body) = assigned(&src, 0) else {
        panic!()
    };
    assert_eq!(names(&body.settings), vec!["FACE"]);
    let AssignValue::Expr(Expr::Pipe(p)) = assigned(&src, 1) else {
        panic!()
    };
    let Expr::Call(step) = *p.call else { panic!() };
    assert_eq!(names(&step.settings), vec!["INT", "CURVE"]);
    let AssignValue::Expr(Expr::Call(t)) = assigned(&src, 2) else {
        panic!()
    };
    assert_eq!(t.type_args, Some(vec!["Vector".to_string()]));
    assert_eq!(names(&t.settings), vec!["POINT"]);
}

#[test]
fn a_call_without_brackets_has_no_settings() {
    let c = call_of("x = Math(Value: a, Value_001: 2.0)");
    assert!(c.settings.is_empty());
    assert_eq!(c.args.len(), 2);
}

#[test]
fn the_tree_holds_settings_as_their_own_field() {
    let c = call_of("x = Math[ADD, use_clamp: true](Value: a)");
    let json = serde_json::to_value(&c).unwrap();
    assert_eq!(
        json["settings"],
        serde_json::json!([
            {"name": null, "value": {"Ref": {"name": "ADD", "line": 2, "col": 12}}, "line": 2, "col": 12},
            {"name": "use_clamp", "value": {"Bool": {"value": true, "line": 2, "col": 28}}, "line": 2, "col": 17},
        ])
    );
    // A tree written before settings had their field reads with none
    let mut old = json.clone();
    old.as_object_mut().unwrap().remove("settings");
    let read: Call = serde_json::from_value(old).unwrap();
    assert!(read.settings.is_empty());
}

#[test]
fn printed_back() {
    let src = format!(
        "{HEAD}  x = Math[ADD, use_clamp: true](Value: a, Value_001: 2.0)\n  return x\n}}\n"
    );
    assert_eq!(base_node::format_source(&src, "s.bn").unwrap(), src);
}

#[test]
fn what_brackets_refuse() {
    for (line, at, says) in [
        ("x = Math[a](Value: 2.0)", (2, 12), "'a' holds a value"),
        (
            "x = Math[mode: (1, a)](Value: 2.0)",
            (2, 22),
            "'a' holds a value",
        ),
        ("x = Math[](Value: a)", (2, 11), "empty settings"),
        ("x = Math[ADD]", (3, 3), "'(' and the inputs"),
        (
            "x = Math[use_clamp: true, ADD](Value: a)",
            (2, 29),
            "positional setting after named",
        ),
    ] {
        let (l, c, message) = refused(line);
        assert_eq!((l, c), at, "{line}");
        assert!(message.contains(says), "{line}: {message}");
    }
}

#[test]
fn nesting_in_settings_is_limited() {
    let deep = format!("{}1.0{}", "(".repeat(40), ")".repeat(40));
    let (_, _, message) = refused(&format!("x = T[{deep}]()"));
    assert!(message.contains("nested too deeply"), "{message}");
}
