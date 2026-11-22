//! Templates: `graph f<T: Float | Vector>(…)` and `f<Vector>(…)` read and print as in Python
//! (python/tests/test_templates.py, test_parse_and_print).

use base_node::ast::{AssignValue, Call, Expr, ReturnValue, Stmt};
use base_node::{format_source, parse};

const SRC: &str =
    "geometry graph blend<T: Float | Vector, U: Float | Color>(a: T, b: U) -> (value: T) {
  c = attribute_or<Vector>(\"rest\", a)
  return (value: a |> twice<T>())
}
";

#[test]
fn type_parameters_and_types_of_a_call() {
    let file = parse(SRC, "t.bn").unwrap();
    let g = &file.graphs[0];
    let params: Vec<(&str, Vec<&str>)> = g
        .type_params
        .iter()
        .map(|t| {
            (
                t.name.as_str(),
                t.types.iter().map(|s| s.as_str()).collect(),
            )
        })
        .collect();
    assert_eq!(
        params,
        vec![
            ("T", vec!["Float", "Vector"]),
            ("U", vec!["Float", "Color"])
        ]
    );
    match &g.body[0] {
        Stmt::Assign(a) => match &a.value {
            AssignValue::Expr(Expr::Call(c)) => {
                assert_eq!(c.type_args, Some(vec!["Vector".to_string()]))
            }
            other => panic!("not a call: {other:?}"),
        },
        other => panic!("not an assignment: {other:?}"),
    }
}

#[test]
fn printed_as_written() {
    assert_eq!(format_source(SRC, "t.bn").unwrap(), SRC);
}

#[test]
fn a_comparison_is_no_call_types() {
    let src = "geometry graph g(a: Float, b: Float) -> Bool {\n  return a < b\n}\n";
    assert_eq!(format_source(src, "t.bn").unwrap(), src);
}

#[test]
fn a_type_parameter_lists_its_types() {
    let err = parse(
        "geometry graph f<T>(x: T) -> (y: T) {\n  return (y: x)\n}\n",
        "t.bn",
    )
    .unwrap_err();
    assert!(
        format!("{err:?}").contains("a type parameter lists its types: <T: Float | Vector>"),
        "{err:?}"
    );
}

/// The first call named `name` in the statements, inside bodies and frames too.
fn find<'a>(stmts: &'a [Stmt], name: &str) -> Option<&'a Call> {
    fn in_expr<'a>(e: &'a Expr, name: &str) -> Option<&'a Call> {
        match e {
            Expr::Call(c) if c.name == name => Some(c),
            Expr::Call(c) => c.args.iter().find_map(|a| in_expr(&a.value, name)),
            Expr::Member(m) => in_expr(&m.target, name),
            _ => None,
        }
    }
    stmts.iter().find_map(|s| match s {
        Stmt::Assign(a) => match &a.value {
            AssignValue::Expr(e) => in_expr(e, name),
            AssignValue::BodyCall(b) => find(&b.body, name),
            AssignValue::NamelessGraph(g) => find(&g.body, name),
        },
        Stmt::Return(r) => match &r.value {
            ReturnValue::Expr(e) => in_expr(e, name),
            ReturnValue::Record(rec) => rec.fields.iter().find_map(|f| in_expr(&f.value, name)),
        },
        Stmt::Frame(f) => find(&f.body, name),
    })
}

/// What the arguments of the text's `Math(…)` are: comparisons, or a call with types.
fn math_args(src: &str) -> Vec<&'static str> {
    let file = parse(src, "t.bn").unwrap();
    let call = find(&file.graphs.last().unwrap().body, "Math").unwrap();
    call.args
        .iter()
        .map(|a| match &a.value {
            Expr::BinOp(_) => "compared",
            Expr::Call(c) if c.type_args.is_some() => "typed call",
            _ => "other",
        })
        .collect()
}

const HEAD: &str =
    "geometry graph g(a: Float, b: Float, c: Float, d: Float, \"Seed\" as s: Float) -> Float {\n";

#[test]
fn a_name_that_holds_a_value_is_no_template() {
    let compared = ["compared", "compared"];
    let math = |body: &str| math_args(&format!("{HEAD}{body}}}\n"));
    // An input, by its key
    assert_eq!(math("  return Math(a < b, c > (d))\n"), compared);
    assert_eq!(math("  return Math(s < b, c > (d))\n"), compared);
    // A name bound before, in the block or in a frame of it
    assert_eq!(math("  k = a\n  return Math(k < b, c > (d))\n"), compared);
    assert_eq!(
        math("  {\n    k = a\n  }\n  return Math(k < b, c > (d))\n"),
        compared
    );
    // Inside a body: its items, and the names around
    assert_eq!(
        math("  r = f(1, v: a) -> {\n    return Math(v < b, k > (v))\n  }\n  return r\n"),
        compared
    );
    assert_eq!(
        math("  h = graph(x: Float) -> Float {\n    return Math(x < a, b > (x))\n  }\n  return h(x: a)\n"),
        compared
    );
    // A name holds no value before its statement, after the body it is an item of, nor in
    // another graph
    assert_eq!(math("  return Math(k < b, c > (d))\n"), ["typed call"]);
    assert_eq!(
        math("  r = f(1, v: a) -> {\n    return v\n  }\n  return Math(v < b, c > (d))\n"),
        ["typed call"]
    );
    let other = "geometry graph h(k: Float) -> Float {\n  return k\n}\n\n\
                 geometry graph g(b: Float) -> Float {\n  return Math(k < b, b > (b))\n}\n";
    assert_eq!(math_args(other), ["typed call"]);
    // Two comparisons in a row are refused, not read as a call
    let err = parse(
        &format!("{HEAD}  x = a < b > (c)\n  return x\n}}\n"),
        "t.bn",
    )
    .unwrap_err();
    assert_eq!((err.diagnostics[0].line, err.diagnostics[0].col), (2, 13));
    // The types of a call, by a name that is none of the graph's values
    let src = "geometry graph pick<T: Float | Vector>(value: T, i: Int) -> (value: T) {
  return (value: index_mix<T>(value, i).value)
}
";
    let file = parse(src, "t.bn").unwrap();
    let call = find(&file.graphs[0].body, "index_mix").unwrap();
    assert_eq!(call.type_args, Some(vec!["T".to_string()]));
    assert_eq!(format_source(src, "t.bn").unwrap(), src);
}
