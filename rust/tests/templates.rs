//! Templates: `graph f<T: Float | Vector>(…)` and `f<Vector>(…)` read and print as in Python
//! (python/tests/test_templates.py, test_parse_and_print).

use base_node::ast::{AssignValue, Expr, Stmt};
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
